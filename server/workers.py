"""Worker state machine, queue management, agent execution."""

import collections
import json
import os
import random
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass

from server.agents import get_adapter
from server.locks import write_lock as _write_lock
from server.persistence import read_json, write_json, atomic_write
from server.usage import (
    TOKEN_FIELDS,
    build_usage_entry,
    build_usage_update,
    extract_stream_usage_event,
    usage_to_legacy_tokens,
)
from server import tasks as task_mod
from server.model_aliases import normalize_model
from server.prompt_hardening import (
    TRUST_MODE_UNTRUSTED,
    harden_agent_argv,
    normalize_trust_mode,
    render_untrusted_text_block,
    render_worker_trust_instructions,
)
from server.worker_types import get_worker_type, normalize_layout
from server.validation import VALID_PRIORITIES, MAX_TAGS, MAX_TAG_LEN, MAX_TITLE, MAX_DESCRIPTION

MAX_HANDOFF_DEPTH = 10
# Feature switch: keep depth-limit logic available, but disable enforcement by default.
ENFORCE_HANDOFF_CHAIN_LIMIT = False
SHELL_WORKER_EXIT_BLOCKED = 78
SHELL_OUTPUT_ARTIFACT_LIMIT = 1_048_576
TASK_BODY_LIMIT = 1_048_576
SHELL_OUTPUT_EXCERPT_BYTES = 65_536
SHELL_SECRET_ENV_MARKERS = (
    "TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL", "PASSPHRASE",
)


def _handoff_depth_limit_reached(depth):
    """Return True when handoff depth should be blocked."""
    return ENFORCE_HANDOFF_CHAIN_LIMIT and depth >= MAX_HANDOFF_DEPTH


def _normalize_worker_name(name):
    """Normalize a worker name for case- and whitespace-insensitive matching."""
    return (name or "").strip().casefold()


def _terminate_proc(proc, *, force=False):
    """Terminate a subprocess, killing the full process tree where possible."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        try:
            pgid = os.getpgid(proc.pid)
            if pgid != os.getpgrp():
                os.killpg(pgid, signal.SIGKILL if force else signal.SIGTERM)
            else:
                (proc.kill if force else proc.terminate)()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                (proc.kill if force else proc.terminate)()
            except OSError:
                pass


def _stop_proc_with_timeout(proc, *, graceful_timeout=5, force_timeout=5):
    """Best-effort subprocess shutdown that never waits forever."""
    if proc is None or proc.poll() is not None:
        return True
    _terminate_proc(proc)
    try:
        proc.wait(timeout=graceful_timeout)
        return True
    except subprocess.TimeoutExpired:
        _terminate_proc(proc, force=True)
        try:
            proc.wait(timeout=force_timeout)
            return True
        except subprocess.TimeoutExpired:
            return proc.poll() is not None


# Active subprocesses keyed by (workspace_id, slot_index)
_processes = {}
_process_lock = threading.Lock()
_cancelled_runs = set()


def _request_process_shutdown(proc):
    """Stop a subprocess in the background so UI actions can return immediately."""
    if proc is None or proc.poll() is not None:
        return

    def _shutdown():
        _stop_proc_with_timeout(proc)

    threading.Thread(target=_shutdown, daemon=True).start()


def _detach_process_entry(ws_id, slot_index=None, *, task_id=None):
    """Remove a tracked process entry and mark that specific run cancelled."""
    with _process_lock:
        target_key = None
        target_entry = None

        if slot_index is not None:
            entry = _processes.get((ws_id, slot_index))
            if entry and (task_id is None or entry.get("task_id") == task_id):
                target_key = (ws_id, slot_index)
                target_entry = entry

        if target_entry is None:
            for key, entry in list(_processes.items()):
                proc_ws_id, proc_slot = key
                if ws_id is not None and proc_ws_id != ws_id:
                    continue
                if slot_index is not None and proc_slot != slot_index:
                    continue
                if task_id is not None and entry.get("task_id") != task_id:
                    continue
                target_key = key
                target_entry = entry
                break

        if target_key is not None:
            _processes.pop(target_key, None)
        if target_entry and target_entry.get("run_id"):
            _cancelled_runs.add(target_entry["run_id"])
        return target_entry


def _consume_cancelled_run(run_id):
    """Return True exactly once for runs a human explicitly stopped/yanked."""
    if not run_id:
        return False
    with _process_lock:
        if run_id not in _cancelled_runs:
            return False
        _cancelled_runs.remove(run_id)
        return True


def _ws_emit(socketio, event, payload, ws_id=None):
    """Emit a socket event with workspaceId attached, scoped to workspace room."""
    if ws_id and isinstance(payload, dict):
        payload["workspaceId"] = ws_id
    socketio.emit(event, payload, to=ws_id)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _worker_trust_mode(worker):
    return normalize_trust_mode((worker or {}).get("trust_mode"))


def _auto_actions_allowed(worker):
    return _worker_trust_mode(worker) != TRUST_MODE_UNTRUSTED


def _shell_workers_enabled(bp_dir):
    env_value = os.environ.get("BULLPEN_ENABLE_SHELL_WORKERS")
    if env_value is not None:
        return env_value.strip().lower() not in ("0", "false", "no", "off")
    try:
        config = read_json(os.path.join(bp_dir, "config.json"))
    except Exception:
        return True
    features = config.get("features") if isinstance(config.get("features"), dict) else {}
    return features.get("shell_workers_enabled", True) is not False


def _load_layout(bp_dir):
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    try:
        config = read_json(os.path.join(bp_dir, "config.json"))
    except Exception:
        config = {}
    return normalize_layout(layout, config=config)


def _save_layout(bp_dir, layout):
    try:
        config = read_json(os.path.join(bp_dir, "config.json"))
    except Exception:
        config = {}
    normalized = normalize_layout(layout, config=config)
    layout.clear()
    layout.update(normalized)
    write_json(os.path.join(bp_dir, "layout.json"), layout)


def check_watch_columns(bp_dir, task_status, socketio=None, ws_id=None, exclude_task_id=None):
    """Check if any on_queue workers are watching the given column and claim tasks.

    Called after any task status change. Scans for idle on_queue workers whose
    watch_column matches task_status, then assigns the oldest unclaimed task
    in that column to the least-recently-active matching worker.

    Args:
        bp_dir: Path to .bullpen directory.
        task_status: The column/status that just received a task.
        socketio: Socket.IO instance for emitting updates.
        ws_id: Workspace ID for scoped emits.
        exclude_task_id: Task ID to skip (e.g. when the task was just explicitly
            assigned via another path and shouldn't be double-claimed).
    """
    try:
        layout = _load_layout(bp_dir)
    except FileNotFoundError:
        return
    slots = layout.get("slots", [])

    # Find eligible watchers: on_queue, watching this column, idle, empty queue,
    # not paused. An on_queue worker that already has a queued task is not
    # available for a fresh claim, even if its state has not yet flipped from
    # idle to working.
    watchers = []
    for i, slot in enumerate(slots):
        if (slot
                and slot.get("activation") == "on_queue"
                and slot.get("watch_column") == task_status
                and slot.get("state") == "idle"
                and not slot.get("task_queue")
                and not slot.get("paused")):
            watchers.append((i, slot))

    if not watchers:
        return

    # Sort by least-recently-active (oldest last_trigger_time first, None = never)
    def _lra_key(item):
        t = item[1].get("last_trigger_time")
        return t if t is not None else 0
    watchers.sort(key=_lra_key)

    # Find unclaimed tasks in the watched column
    from server.tasks import list_tasks
    all_tasks = list_tasks(bp_dir)
    unclaimed = [
        t for t in all_tasks
        if t.get("status") == task_status
        and not t.get("assigned_to")
        and t["id"] != exclude_task_id
    ]
    if not unclaimed:
        return

    # Sort by creation time (oldest first) for FIFO
    unclaimed.sort(key=lambda t: t.get("created_at", ""))

    # Assign one task per idle watcher, round-robin
    for (slot_idx, _watcher), task in zip(watchers, unclaimed):
        assign_task(bp_dir, slot_idx, task["id"], socketio, ws_id)


def _refill_from_watch_column(bp_dir, slot_index, socketio=None, ws_id=None):
    """When an on_queue worker returns to idle with an empty queue, check its
    watch_column for unclaimed tasks and claim the oldest one."""
    try:
        layout = _load_layout(bp_dir)
    except FileNotFoundError:
        return
    worker = layout["slots"][slot_index]
    if not worker:
        return
    if (worker.get("activation") != "on_queue"
            or worker.get("watch_column") is None
            or worker.get("paused")
            or worker.get("task_queue")):
        return

    from server.tasks import list_tasks
    all_tasks = list_tasks(bp_dir)
    unclaimed = [
        t for t in all_tasks
        if t.get("status") == worker["watch_column"]
        and not t.get("assigned_to")
    ]
    if not unclaimed:
        return

    unclaimed.sort(key=lambda t: t.get("created_at", ""))
    assign_task(bp_dir, slot_index, unclaimed[0]["id"], socketio, ws_id)


def create_auto_task(bp_dir, slot_index, worker, socketio=None, ws_id=None,
                     trigger_kind="manual", trigger_label=None, scheduled_at=None):
    """Create an ephemeral task for a self-directed worker with no queue.

    ws_id must be propagated so the resulting agent process is registered
    under the caller's workspace key; otherwise yank_from_worker cannot
    find and kill the process when the task is pulled out of in_progress.
    """
    worker_name = worker.get("name", "Worker")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    label = trigger_label or trigger_kind or "manual"
    title = f"[Auto] {worker_name} - {label} - {timestamp}"
    synthetic_key = f"{slot_index}:{trigger_kind}:{scheduled_at or timestamp}"

    body = (
        f"Worker: {worker_name}\n"
        f"Worker type: {worker.get('type', 'ai')}\n"
        f"Trigger kind: {trigger_kind}\n"
        f"Workspace: {os.path.dirname(bp_dir)}\n"
    )
    if scheduled_at:
        body += f"Scheduled at: {scheduled_at}\n"

    task = task_mod.create_task(
        bp_dir,
        title,
        description=body,
        task_type="chore",
        priority="normal",
        tags=["synthetic", "worker-run", "scheduled" if trigger_kind in ("at_time", "on_interval") else "manual"],
    )
    task = task_mod.update_task(bp_dir, task["id"], {
        "synthetic_run": True,
        "trigger_kind": trigger_kind,
        "synthetic_run_key": synthetic_key,
        **({"scheduled_at": scheduled_at} if scheduled_at else {}),
    })
    if socketio:
        _ws_emit(socketio, "task:created", task, ws_id)
    assign_task(bp_dir, slot_index, task["id"], socketio, ws_id)
    return task


def assign_task(bp_dir, slot_index, task_id, socketio=None, ws_id=None, preserve_handoff_depth=False):
    """Add task to worker's queue, update ticket status.

    By default, assignment starts a fresh run chain and resets handoff depth.
    Internal worker-to-worker handoffs should set preserve_handoff_depth=True.
    """
    layout = _load_layout(bp_dir)
    worker = layout["slots"][slot_index]
    if not worker:
        raise ValueError(f"No worker in slot {slot_index}")

    # Update task ticket
    updates = {
        "assigned_to": str(slot_index),
        "status": "assigned",
    }
    if not preserve_handoff_depth:
        updates["handoff_depth"] = 0
    task_mod.update_task(bp_dir, task_id, updates)

    # Add to queue
    if task_id not in worker.get("task_queue", []):
        worker.setdefault("task_queue", []).append(task_id)

    _save_layout(bp_dir, layout)

    if socketio:
        task = task_mod.read_task(bp_dir, task_id)
        _ws_emit(socketio, "task:updated", task, ws_id)
        _ws_emit(socketio, "layout:updated", layout, ws_id)

    # Check if worker should auto-start
    activation = worker.get("activation", "on_drop")
    if activation in ("on_drop", "on_queue") and worker.get("state") == "idle":
        start_worker(bp_dir, slot_index, socketio, ws_id)
    elif activation == "manual" and socketio:
        _ws_emit(socketio, "toast", {
            "message": f"Task queued on {worker.get('name', 'worker')}. Use Run to start this manual worker.",
            "level": "info",
        }, ws_id)


def start_worker(bp_dir, slot_index, socketio=None, ws_id=None):
    """Dispatch the next run to the worker-type-specific backend.

    This is the shared entry point for every runnable worker type. It reads
    the slot, resolves its type, and delegates to the appropriate runner.
    Both AI and Shell runners share the same lifecycle helpers
    (`_begin_run` / `_commit_run_start`) and the same completion/retry
    pipeline (`_on_agent_success` / `_on_agent_error`).
    """
    try:
        layout = _load_layout(bp_dir)
    except FileNotFoundError:
        return
    slots = layout.get("slots", [])
    if slot_index >= len(slots):
        return
    worker = slots[slot_index]
    if not worker:
        return
    worker_type = get_worker_type(worker.get("type", "ai"))
    if worker_type.type_id == "ai":
        _run_ai_worker(bp_dir, slot_index, socketio, ws_id)
        return
    if worker_type.type_id == "shell":
        _run_shell_worker(bp_dir, slot_index, socketio, ws_id)
        return
    if worker_type.type_id == "service":
        from server import service_worker as service_worker_mod
        service_worker_mod.run_service_order(bp_dir, slot_index, socketio, ws_id)
        return
    # Unknown or not-yet-runnable types (eval, unknown) surface a toast and
    # never enter the lifecycle.
    if socketio:
        errors = worker_type.validate_config(worker)
        message = errors[0] if errors else f"{worker_type.type_id} workers are not implemented yet."
        _ws_emit(socketio, "toast", {
            "message": f"{worker.get('name', 'Worker')} cannot run yet: {message}",
            "level": "warning",
        }, ws_id)


def _begin_run(bp_dir, slot_index, *, trigger_kind="manual", trigger_label="manual",
               socketio=None, ws_id=None):
    """Shared lifecycle preamble for every runnable worker type.

    Loads the layout, handles the empty-queue synthetic-ticket path, and
    resolves the head task. Returns (layout, worker, task, task_id) when a
    run should proceed, or None when it should not (no task, worker missing,
    or a recursive start_worker already spawned the run via assign_task).

    This does not transition state to `working`; callers do type-specific
    preflight (adapter availability, command validation, payload prep) first
    and then call `_commit_run_start` once they are committed to launching.
    """
    try:
        layout = _load_layout(bp_dir)
    except FileNotFoundError:
        return None
    slots = layout.get("slots", [])
    if slot_index >= len(slots):
        return None
    worker = slots[slot_index]
    if not worker:
        return None

    queue = worker.get("task_queue", [])
    if not queue:
        create_auto_task(
            bp_dir, slot_index, worker, socketio, ws_id,
            trigger_kind=trigger_kind, trigger_label=trigger_label,
        )
        # Re-read layout since assign_task mutated it.
        layout = _load_layout(bp_dir)
        slots = layout.get("slots", [])
        worker = slots[slot_index] if slot_index < len(slots) else None
        # For on_drop/on_queue workers, assign_task already recursively
        # invoked start_worker and spawned the run. Returning here avoids a
        # duplicate launch that would leak a second process on yank/stop.
        if worker and worker.get("state") == "working":
            return None
        queue = worker.get("task_queue", []) if worker else []
        if not queue:
            return None

    task_id = queue[0]
    task = task_mod.read_task(bp_dir, task_id)
    if not task:
        # Task was deleted, remove from queue and try the next one.
        queue.pop(0)
        _save_layout(bp_dir, layout)
        if queue:
            start_worker(bp_dir, slot_index, socketio, ws_id)
        return None

    return layout, worker, task, task_id


def _commit_run_start(bp_dir, layout, worker, task_id, socketio, ws_id):
    """Transition a run to `working` / `in_progress` and emit updates.

    Called by type-specific runners after preflight succeeds and they are
    committed to launching a subprocess.
    """
    worker["state"] = "working"
    worker["started_at"] = _now_iso()
    task_mod.update_task(bp_dir, task_id, {"status": "in_progress"})
    _save_layout(bp_dir, layout)

    if socketio:
        updated_task = task_mod.read_task(bp_dir, task_id)
        _ws_emit(socketio, "task:updated", updated_task, ws_id)
        _ws_emit(socketio, "layout:updated", layout, ws_id)


def _run_ai_worker(bp_dir, slot_index, socketio, ws_id):
    """AI worker backend: resolves adapter, assembles prompt, launches agent."""
    begun = _begin_run(bp_dir, slot_index, socketio=socketio, ws_id=ws_id)
    if begun is None:
        return
    layout, worker, task, task_id = begun

    # Resolve adapter before committing state so a missing local CLI surfaces a
    # clean setup error instead of a raw FileNotFoundError and does not leave
    # the task stuck in `in_progress`.
    agent_name = worker.get("agent", "claude")
    adapter = get_adapter(agent_name)
    if not adapter:
        _block_agent_start_failure(
            bp_dir, slot_index, task_id, f"Unknown agent: {agent_name}", socketio, ws_id,
        )
        return
    if not adapter.available():
        _block_agent_start_failure(
            bp_dir, slot_index, task_id, adapter.unavailable_message(), socketio, ws_id,
        )
        return

    model = normalize_model(worker.get("agent", "claude"), worker.get("model", "claude-sonnet-4-6"))
    worker["model"] = model

    _commit_run_start(bp_dir, layout, worker, task_id, socketio, ws_id)

    prompt = _assemble_prompt(bp_dir, worker, task)
    workspace = os.path.dirname(bp_dir)  # workspace is parent of .bullpen

    agent_cwd = workspace
    if worker.get("use_worktree"):
        try:
            agent_cwd = _setup_worktree(workspace, bp_dir, task_id)
        except Exception as e:
            _on_agent_error(bp_dir, slot_index, task_id, f"Worktree setup failed: {e}", socketio, ws_id=ws_id)
            return

    argv = adapter.build_argv(prompt, model, agent_cwd, bp_dir=bp_dir)
    argv = harden_agent_argv(agent_name, argv, trust_mode=_worker_trust_mode(worker))

    config = read_json(os.path.join(bp_dir, "config.json"))
    timeout = config.get("agent_timeout_seconds", 600)

    thread = threading.Thread(
        target=_run_agent,
        args=(bp_dir, slot_index, task_id, argv, prompt, adapter, timeout, agent_cwd, socketio, ws_id),
        daemon=True,
    )
    thread.start()


@dataclass
class PreparedShellRun:
    argv: list
    cwd: str
    env: dict
    stdin_text: str | None
    timeout: int
    delivery: str
    delivery_fallback_from: str | None = None
    body_file: str | None = None
    prelude_lines: list | None = None


@dataclass
class ShellResult:
    outcome: str
    disposition: str | None = None
    reason: str | None = None
    ticket_updates: dict | None = None


def _run_shell_worker(bp_dir, slot_index, socketio=None, ws_id=None):
    """Shell worker backend: validates config, prepares payload, launches shell."""
    try:
        layout = _load_layout(bp_dir)
    except FileNotFoundError:
        return
    slots = layout.get("slots", [])
    if slot_index >= len(slots):
        return
    worker = slots[slot_index]
    if not worker:
        return

    if not _shell_workers_enabled(bp_dir):
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": "Shell workers are disabled for this workspace.",
                "level": "warning",
            }, ws_id)
        return

    # Shell preflight runs before the empty-queue auto-task path so a
    # misconfigured worker does not pull in a synthetic ticket just to block
    # it on the same missing-command error.
    errors = _validate_shell_worker(worker, bp_dir)
    if errors:
        queue = worker.get("task_queue", [])
        if not queue:
            if socketio:
                _ws_emit(socketio, "toast", {
                    "message": errors[0],
                    "level": "warning",
                }, ws_id)
            return
        _block_agent_start_failure(bp_dir, slot_index, queue[0], errors[0], socketio, ws_id)
        return

    begun = _begin_run(bp_dir, slot_index, socketio=socketio, ws_id=ws_id)
    if begun is None:
        return
    layout, worker, task, task_id = begun

    workspace = os.path.dirname(bp_dir)
    try:
        prepared = _prepare_shell_run(bp_dir, workspace, slot_index, worker, task)
    except Exception as exc:
        _on_agent_error(bp_dir, slot_index, task_id, str(exc), socketio, ws_id=ws_id, non_retryable=True)
        return

    _commit_run_start(bp_dir, layout, worker, task_id, socketio, ws_id)

    thread = threading.Thread(
        target=_run_shell,
        args=(bp_dir, slot_index, task_id, worker, prepared, socketio, ws_id),
        daemon=True,
    )
    thread.start()


def _validate_shell_worker(worker, bp_dir):
    errors = []
    if not str(worker.get("command") or "").strip():
        errors.append("Shell workers require a command.")
    for item in worker.get("env") or []:
        key = str((item or {}).get("key") or "").strip()
        if key == "BULLPEN_MCP_TOKEN":
            errors.append("BULLPEN_MCP_TOKEN cannot be configured for Shell workers.")
    return errors


def _shell_payload(task, worker, slot_index, workspace):
    return {
        "id": task.get("id"),
        "title": task.get("title", ""),
        "filename": f"{task.get('id')}.md" if task.get("id") else "",
        "project": workspace,
        "status": task.get("status", ""),
        "type": task.get("type", "task"),
        "priority": task.get("priority", "normal"),
        "tags": task.get("tags") or [],
        "body": task.get("body", ""),
        "history": task.get("history") or [],
        "worker": {
            "name": worker.get("name", "Worker"),
            "slot_index": slot_index,
            "coord": {
                "row": worker.get("row"),
                "col": worker.get("col"),
            },
        },
    }


def _resolve_shell_cwd(workspace, configured_cwd):
    configured_cwd = str(configured_cwd or "").strip()
    cwd = os.path.join(workspace, configured_cwd) if configured_cwd and not os.path.isabs(configured_cwd) else (configured_cwd or workspace)
    real = os.path.realpath(cwd)
    root = os.path.realpath(workspace)
    if real != root and not real.startswith(root + os.sep):
        raise ValueError("Shell worker cwd escapes the workspace.")
    if not os.path.isdir(real):
        raise ValueError("Shell worker cwd does not exist.")
    return real


def _is_secret_env_name(name):
    upper = str(name or "").upper()
    return any(marker in upper for marker in SHELL_SECRET_ENV_MARKERS)


def _minimal_shell_env(configured_env):
    if sys.platform == "win32":
        allowed = {"PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"}
        inherited = {
            key: value for key, value in os.environ.items()
            if key.upper() in allowed and not _is_secret_env_name(key)
        }
    else:
        inherited = {
            key: value for key, value in os.environ.items()
            if (key in {"PATH", "HOME", "LANG", "TZ"} or key.startswith("LC_"))
            and not _is_secret_env_name(key)
        }

    inherited.pop("BULLPEN_MCP_TOKEN", None)
    for item in configured_env or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        if key == "BULLPEN_MCP_TOKEN":
            raise ValueError("BULLPEN_MCP_TOKEN cannot be configured for Shell workers.")
        inherited[key] = str(item.get("value") or "")
    return inherited


def _argv_json_limit():
    if sys.platform == "win32":
        return 24 * 1024
    try:
        return max(0, int(os.sysconf("SC_ARG_MAX")) - 4096)
    except (AttributeError, ValueError, OSError):
        return 128 * 1024


def _prepare_shell_run(bp_dir, workspace, slot_index, worker, task):
    payload = _shell_payload(task, worker, slot_index, workspace)
    payload_json = json.dumps(payload, ensure_ascii=False)
    payload_json.encode("utf-8")

    cwd = _resolve_shell_cwd(workspace, worker.get("cwd"))
    env = _minimal_shell_env(worker.get("env"))
    delivery = worker.get("ticket_delivery") or "stdin-json"
    fallback_from = None
    stdin_text = None
    body_file = None
    prelude_lines = []

    command = str(worker.get("command") or "")
    if sys.platform == "win32":
        argv = ["cmd.exe", "/c", command]
    else:
        argv = ["/bin/sh", "-c", command]

    if delivery == "argv-json":
        payload_bytes = len(payload_json.encode("utf-8"))
        limit = _argv_json_limit()
        if payload_bytes > limit:
            fallback_from = "argv-json"
            delivery = "stdin-json"
            prelude_lines.append(
                f"[bullpen] payload {payload_bytes // 1024 + 1}KiB > argv limit, using stdin-json"
            )
        elif sys.platform == "win32":
            argv.append(payload_json)
        else:
            argv.extend(["bullpen", payload_json])

    if delivery == "stdin-json":
        stdin_text = payload_json
    elif delivery == "env-vars":
        fd, body_file = tempfile.mkstemp(prefix="bullpen_ticket_body_")
        with os.fdopen(fd, "w") as handle:
            handle.write(task.get("body", ""))
        env.update({
            "BULLPEN_TICKET_ID": str(task.get("id") or ""),
            "BULLPEN_TICKET_TITLE": str(task.get("title") or ""),
            "BULLPEN_TICKET_FILENAME": f"{task.get('id')}.md" if task.get("id") else "",
            "BULLPEN_PROJECT": workspace,
            "BULLPEN_TICKET_STATUS": str(task.get("status") or ""),
            "BULLPEN_TICKET_PRIORITY": str(task.get("priority") or ""),
            "BULLPEN_TICKET_TAGS": json.dumps(task.get("tags") or []),
            "BULLPEN_TICKET_BODY_FILE": body_file,
        })

    return PreparedShellRun(
        argv=argv,
        cwd=cwd,
        env=env,
        stdin_text=stdin_text,
        timeout=max(1, min(int(worker.get("timeout_seconds") or 60), 600)),
        delivery=delivery,
        delivery_fallback_from=fallback_from,
        body_file=body_file,
        prelude_lines=prelude_lines,
    )


def _block_agent_start_failure(bp_dir, slot_index, task_id, error_msg, socketio=None, ws_id=None):
    """Block a task when its agent cannot be launched at all.

    This is intentionally not routed through _on_agent_error: missing binaries
    and unknown adapters are setup problems, so retrying just burns time and
    leaves users with a cryptic failure.
    """
    layout = _load_layout(bp_dir)
    worker = None
    if slot_index < len(layout.get("slots", [])):
        worker = layout["slots"][slot_index]

    if worker:
        queue = worker.get("task_queue", [])
        if task_id in queue:
            queue.remove(task_id)
        worker["state"] = "idle"
        _save_layout(bp_dir, layout)

    task_mod.update_task(bp_dir, task_id, {
        "status": "blocked",
        "assigned_to": "",
    })
    _append_output(bp_dir, task_id, worker or {"name": "Agent"}, f"[BLOCKED] {error_msg}")

    if socketio:
        task = task_mod.read_task(bp_dir, task_id)
        _ws_emit(socketio, "task:updated", task, ws_id)
        _ws_emit(socketio, "layout:updated", layout, ws_id)


def stop_worker(bp_dir, slot_index, socketio=None, ws_id=None):
    """Stop a working agent. Task goes back to Assigned."""
    layout = _load_layout(bp_dir)
    worker = layout["slots"][slot_index]
    proc = None
    if worker:
        worker["state"] = "idle"
        queue = worker.get("task_queue", [])
        if queue:
            task_id = queue[0]
            entry = _detach_process_entry(ws_id, slot_index, task_id=task_id)
            proc = entry["proc"] if entry else None
            task_mod.update_task(bp_dir, task_id, {"status": "assigned"})
            if socketio:
                task = task_mod.read_task(bp_dir, task_id)
                _ws_emit(socketio, "task:updated", task, ws_id)
        else:
            entry = _detach_process_entry(ws_id, slot_index)
            proc = entry["proc"] if entry else None

        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "layout:updated", layout, ws_id)
    _request_process_shutdown(proc)


def yank_from_worker(bp_dir, task_id, socketio=None, ws_id=None):
    """Remove a task from its owning worker's queue, killing the agent if running.

    Called when a human drags a task out of assigned/in_progress to a human column.
    Returns True if the task was found in a worker queue, False otherwise.
    """
    layout = _load_layout(bp_dir)
    slots = layout.get("slots", [])
    task = task_mod.read_task(bp_dir, task_id)

    queue_slots = []
    for i, slot in enumerate(slots):
        if slot and task_id in slot.get("task_queue", []):
            queue_slots.append(i)

    assigned_slot = None
    if task and task.get("assigned_to") not in (None, ""):
        try:
            candidate = int(task.get("assigned_to"))
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and 0 <= candidate < len(slots) and slots[candidate]:
            assigned_slot = candidate

    process_slot = None
    with _process_lock:
        for (proc_ws_id, proc_slot), entry in _processes.items():
            if ws_id is not None and proc_ws_id != ws_id:
                continue
            if entry.get("task_id") == task_id:
                process_slot = proc_slot
                break

    slot_index = queue_slots[0] if queue_slots else assigned_slot
    if slot_index is None:
        slot_index = process_slot
    if slot_index is None or slot_index >= len(slots) or not slots[slot_index]:
        return False

    worker = slots[slot_index]
    queue = worker.get("task_queue", [])
    is_front = queue and queue[0] == task_id
    is_running = (
        (worker.get("state") == "working" and (is_front or assigned_slot == slot_index))
        or process_slot == slot_index
    )

    # Kill the subprocess if this task is actively running
    proc = None
    if is_running:
        if worker.get("type") == "service":
            from server import service_worker as service_worker_mod
            service_worker_mod.cancel_service_order(bp_dir, ws_id, slot_index, task_id, socketio)
        entry = _detach_process_entry(ws_id, slot_index, task_id=task_id)
        if entry is None:
            entry = _detach_process_entry(ws_id, task_id=task_id)
        proc = entry["proc"] if entry else None
        worker["state"] = "idle"

    # Remove every stale queue reference, not just the first one found.
    for slot in slots:
        if not slot:
            continue
        slot_queue = slot.get("task_queue", [])
        while task_id in slot_queue:
            slot_queue.remove(task_id)

    _save_layout(bp_dir, layout)

    if socketio:
        _ws_emit(socketio, "layout:updated", layout, ws_id)

    # If worker was running this task and has more queued, advance
    if is_running and queue and worker.get("activation") in ("on_drop", "on_queue"):
        start_worker(bp_dir, slot_index, socketio, ws_id)

    _request_process_shutdown(proc)

    return True


def _assemble_prompt(bp_dir, worker, task):
    """Build the full prompt for the agent."""
    parts = [render_worker_trust_instructions(_worker_trust_mode(worker))]

    # Workspace prompt
    wp_path = os.path.join(bp_dir, "workspace_prompt.md")
    if os.path.exists(wp_path):
        wp = open(wp_path).read().strip()
        if wp:
            parts.append(render_untrusted_text_block("Workspace Context", wp, "WORKSPACE_CONTEXT"))

    # Bullpen prompt
    bp_path = os.path.join(bp_dir, "bullpen_prompt.md")
    if os.path.exists(bp_path):
        bp = open(bp_path).read().strip()
        if bp:
            parts.append(render_untrusted_text_block("Bullpen Context", bp, "BULLPEN_CONTEXT"))

    # Expertise prompt
    expertise = worker.get("expertise_prompt", "")
    if expertise:
        parts.append(f"## Your Role\n\n{expertise}")

    # Task body
    parts.append(f"## Task Metadata\n\nTitle: {task.get('title', 'Untitled')}")
    if task.get("id"):
        parts.append(
            f"Task ID: `{task['id']}`. If you need to add notes or update "
            f"the body of this ticket, call `mcp__bullpen__update_ticket` "
            f"with this ID directly (do not search by title). "
            f"Do NOT change the ticket's `status` — the worker will set the "
            f"final status based on its configured output."
        )
    parts.append(f"Type: {task.get('type', 'task')}")
    parts.append(f"Priority: {task.get('priority', 'normal')}")
    if task.get("tags"):
        parts.append(f"Tags: {', '.join(task['tags'])}")
    if task.get("body"):
        parts.append(render_untrusted_text_block("Ticket Body", task["body"], "TASK_BODY"))

    prompt = "\n\n".join(parts)

    # Truncate
    config_path = os.path.join(bp_dir, "config.json")
    if os.path.exists(config_path):
        config = read_json(config_path)
        max_chars = config.get("max_prompt_chars", 100000)
    else:
        max_chars = 100000

    if len(prompt) > max_chars:
        prompt = prompt[:max_chars] + "\n\n[Prompt truncated]"

    return prompt


def _auto_commit(cwd, task_title, task_id):
    """Stage all changes and commit. Returns commit hash or None."""
    # Stage all changes
    result = subprocess.run(
        ["git", "add", "-A"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None

    # Check if there's anything to commit
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode == 0:
        # Nothing staged
        return None

    # Commit
    msg = f"bullpen: {task_title} [{task_id}]"
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None

    # Get commit hash
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _auto_pr(cwd, task_title, task_id, branch_name):
    """Push branch and create PR. Returns PR URL or error string."""
    if not shutil.which("gh"):
        return "Error: gh CLI not available"

    # Push branch
    result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return f"Push failed: {result.stderr.strip()}"

    # Create PR
    result = subprocess.run(
        ["gh", "pr", "create",
         "--title", f"bullpen: {task_title}",
         "--body", f"Task: {task_id}"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return f"PR creation failed: {result.stderr.strip()}"

    return result.stdout.strip()


def _setup_worktree(workspace, bp_dir, task_id):
    """Create a git worktree for isolated agent execution. Returns worktree path."""
    # Verify workspace is a git repo
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=workspace, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Workspace is not a git repository")

    worktree_dir = os.path.join(bp_dir, "worktrees", task_id)
    branch_name = f"bullpen/{task_id}"

    os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)

    result = subprocess.run(
        ["git", "worktree", "add", worktree_dir, "-b", branch_name],
        cwd=workspace, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")

    return worktree_dir


MAX_OUTPUT_BUFFER = 100_000  # 100KB server-side buffer for live display
MAX_LINE_LEN = 10_000  # 10KB per line cap
MAX_EMIT_LINES = 500  # per-batch cap sent to clients; prevents flooding the UI
MAX_CAPTURED_LINES = 5_000  # cap on stdout/stderr/combined lists held in memory
MAX_TOTAL_OUTPUT_BYTES = 10 * 1024 * 1024  # 10MB runaway-output ceiling
LIVE_TOKEN_EMIT_INTERVAL_SECONDS = 0.5


class CompletedProcessCapture:
    """Captured subprocess result used by worker-type adapters."""

    def __init__(self, *, stdout, stderr, returncode, timed_out, combined_lines):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timed_out = timed_out
        self.combined_lines = combined_lines


class SubprocessRunner:
    """Launch, stream, capture, timeout, and register a worker subprocess."""

    def __init__(
        self,
        *,
        bp_dir,
        slot_index,
        task_id,
        argv,
        cwd,
        env=None,
        stdin_text,
        timeout,
        socketio=None,
        ws_id=None,
        line_formatter=None,
        line_observer=None,
    ):
        self.bp_dir = bp_dir
        self.slot_index = slot_index
        self.task_id = task_id
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.stdin_text = stdin_text
        self.timeout = timeout
        self.socketio = socketio
        self.ws_id = ws_id
        self.line_formatter = line_formatter or (lambda line: line.rstrip("\n"))
        self.line_observer = line_observer
        self.timed_out = False
        self.run_id = None
        self.proc = None

    def run(self):
        popen_kwargs = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=self.env,
            text=True,
            bufsize=1,
            **popen_kwargs,
        )
        self.proc = proc
        self.run_id = _timestamp_id()

        entry = {
            "proc": proc,
            "buffer": [],
            "task_id": self.task_id,
            "buffer_size": 0,
            "run_id": self.run_id,
        }
        with _process_lock:
            _processes[(self.ws_id, self.slot_index)] = entry

        try:
            if self.stdin_text is not None:
                proc.stdin.write(self.stdin_text)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        self.output_exceeded = False

        def _watchdog():
            self.timed_out = True
            if proc.poll() is None:
                _terminate_proc(proc)

        timer = threading.Timer(self.timeout, _watchdog)
        timer.daemon = True
        timer.start()

        stdout_lines = collections.deque(maxlen=MAX_CAPTURED_LINES)
        stderr_lines = collections.deque(maxlen=MAX_CAPTURED_LINES)
        combined_lines = collections.deque(maxlen=MAX_CAPTURED_LINES)
        batch = []
        batch_lock = threading.Lock()
        last_emit = [time.time()]
        total_bytes = [0]

        def _trim_batch_for_emit(lines):
            """Cap lines per emit so a runaway process can't blow up the client.

            V8's argument stack caps spread-push around 100k–500k args; we also
            don't want to ship megabytes of text per Socket.IO frame. Keep the
            tail and prepend a dropped-count marker.
            """
            if len(lines) <= MAX_EMIT_LINES:
                return lines
            dropped = len(lines) - MAX_EMIT_LINES
            return [f"[… {dropped} lines dropped …]"] + lines[-MAX_EMIT_LINES:]

        def _append_stream_line(line, sink, stream_name):
            sink.append(line)
            if self.line_observer:
                self.line_observer(line, stream_name, proc)

            # Runaway-output ceiling: once we've seen too many bytes, stop
            # reading and kill the proc. Prevents a `yes`-style process from
            # pinning the reader thread and buffering indefinitely.
            total_bytes[0] += len(line)
            if (
                not self.output_exceeded
                and total_bytes[0] > MAX_TOTAL_OUTPUT_BYTES
            ):
                self.output_exceeded = True
                if proc.poll() is None:
                    _terminate_proc(proc)

            display_line = line
            if len(display_line) > MAX_LINE_LEN:
                display_line = display_line[:MAX_LINE_LEN] + "[line truncated]\n"

            display = self.line_formatter(display_line)
            if display is None:
                return

            for display_line in display.split("\n"):
                combined_lines.append(display_line)

                with _process_lock:
                    entry = _processes.get((self.ws_id, self.slot_index))
                    if entry:
                        entry["buffer"].append(display_line)
                        entry["buffer_size"] += len(display_line) + 1
                        while entry["buffer_size"] > MAX_OUTPUT_BUFFER and entry["buffer"]:
                            removed = entry["buffer"].pop(0)
                            entry["buffer_size"] -= len(removed) + 1

                to_emit = None
                with batch_lock:
                    batch.append(display_line)
                    now = time.time()
                    if self.socketio and now - last_emit[0] >= 0.2:
                        to_emit = _trim_batch_for_emit(batch)
                        batch.clear()
                        last_emit[0] = now
                if self.socketio and to_emit:
                    _ws_emit(self.socketio, "worker:output", {
                        "slot": self.slot_index,
                        "lines": to_emit,
                    }, self.ws_id)

        def _drain_stderr():
            try:
                while True:
                    line = proc.stderr.readline()
                    if not line:
                        break
                    _append_stream_line(line, stderr_lines, "stderr")
            except (ValueError, OSError):
                pass

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                _append_stream_line(line, stdout_lines, "stdout")
        except (ValueError, OSError):
            pass

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _stop_proc_with_timeout(proc)
        timer.cancel()
        stderr_thread.join(timeout=2)

        to_emit = None
        with batch_lock:
            if self.socketio and batch:
                to_emit = _trim_batch_for_emit(batch)
                batch.clear()
        if self.socketio and to_emit:
            _ws_emit(self.socketio, "worker:output", {
                "slot": self.slot_index,
                "lines": to_emit,
            }, self.ws_id)

        return CompletedProcessCapture(
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            returncode=proc.returncode,
            timed_out=self.timed_out or self.output_exceeded,
            combined_lines=list(combined_lines),
        )


def _run_shell(bp_dir, slot_index, task_id, worker_snapshot, prepared, socketio, ws_id=None):
    started = time.time()
    runner = None
    try:
        prelude = "\n".join(prepared.prelude_lines or [])
        runner = SubprocessRunner(
            bp_dir=bp_dir,
            slot_index=slot_index,
            task_id=task_id,
            argv=prepared.argv,
            cwd=prepared.cwd,
            env=prepared.env,
            stdin_text=prepared.stdin_text,
            timeout=prepared.timeout,
            socketio=socketio,
            ws_id=ws_id,
            line_formatter=lambda line: line.rstrip("\n"),
        )
        if prelude and socketio:
            _ws_emit(socketio, "worker:output", {"slot": slot_index, "lines": prelude.splitlines()}, ws_id)
        completed = runner.run()
        duration_ms = int((time.time() - started) * 1000)

        if prelude:
            completed.stdout = prelude + "\n" + completed.stdout
            completed.combined_lines = prelude.splitlines() + completed.combined_lines

        if completed.timed_out:
            result = ShellResult(outcome="error", reason="timeout")
        else:
            result = _parse_shell_result(bp_dir, worker_snapshot, completed)

        record = _append_shell_run_record(
            bp_dir,
            task_id,
            worker_snapshot,
            slot_index,
            result,
            completed,
            prepared,
            duration_ms,
        )

        if socketio:
            _ws_emit(socketio, "worker:output:done", {
                "slot": slot_index,
                "lines": [line.rstrip("\n") for line in completed.combined_lines],
                "reason": result.reason,
            }, ws_id)

        if result.outcome == "success":
            if result.ticket_updates:
                _apply_shell_ticket_updates(bp_dir, task_id, result.ticket_updates)
            _on_agent_success(
                bp_dir,
                slot_index,
                task_id,
                "",
                socketio,
                agent_cwd=None,
                ws_id=ws_id,
                usage={},
                disposition_override=result.disposition,
                output_appender=lambda _worker: None,
                allow_auto_actions=False,
                run_id=runner.run_id,
            )
        elif result.outcome == "reroute":
            _on_agent_error(
                bp_dir,
                slot_index,
                task_id,
                result.reason or "Shell worker requested blocked disposition",
                socketio,
                output="",
                ws_id=ws_id,
                non_retryable=True,
                run_id=runner.run_id,
            )
        else:
            _on_agent_error(
                bp_dir,
                slot_index,
                task_id,
                result.reason or f"Shell command failed with exit code {completed.returncode}",
                socketio,
                output="",
                ws_id=ws_id,
                non_retryable=False,
                run_id=runner.run_id,
            )
    except Exception as exc:
        _on_agent_error(
            bp_dir,
            slot_index,
            task_id,
            str(exc),
            socketio,
            ws_id=ws_id,
            run_id=runner.run_id if runner else None,
        )
    finally:
        if prepared.body_file:
            try:
                os.unlink(prepared.body_file)
            except OSError:
                pass
        with _process_lock:
            entry = _processes.get((ws_id, slot_index))
            if entry and entry.get("run_id") == (runner.run_id if runner else None):
                _processes.pop((ws_id, slot_index), None)


def _parse_shell_result(bp_dir, worker, completed):
    stdout_text = (completed.stdout or "").strip()
    parsed = None
    if stdout_text:
        try:
            candidate = json.loads(stdout_text)
            if isinstance(candidate, dict):
                parsed = candidate
        except json.JSONDecodeError:
            parsed = None

    if completed.returncode == SHELL_WORKER_EXIT_BLOCKED:
        return ShellResult(
            outcome="reroute",
            disposition="blocked",
            reason=_json_reason(parsed) or f"Shell command exited {SHELL_WORKER_EXIT_BLOCKED}",
        )
    if completed.returncode != 0:
        return ShellResult(
            outcome="error",
            reason=_json_reason(parsed) or f"Shell command exited {completed.returncode}",
        )

    if not parsed:
        return ShellResult(outcome="success", disposition=None, reason=None, ticket_updates=None)

    disposition = parsed.get("disposition")
    if disposition is not None:
        disposition = str(disposition)
        if not _valid_disposition(bp_dir, disposition):
            return ShellResult(outcome="error", reason=f"Invalid disposition: {disposition}")

    reason = parsed.get("reason")
    if reason is not None and not isinstance(reason, str):
        return ShellResult(outcome="error", reason="Invalid reason in Shell worker result")

    try:
        ticket_updates = _validate_shell_ticket_updates(parsed.get("ticket_updates"))
    except ValueError as exc:
        return ShellResult(outcome="error", reason=str(exc))

    return ShellResult(
        outcome="success",
        disposition=disposition,
        reason=reason,
        ticket_updates=ticket_updates,
    )


def _json_reason(parsed):
    if isinstance(parsed, dict) and isinstance(parsed.get("reason"), str):
        return parsed["reason"]
    return None


def _valid_disposition(bp_dir, disposition):
    value = str(disposition or "").strip()
    folded = value.casefold()
    if folded in {"review", "done", "blocked"}:
        return True
    try:
        config = read_json(os.path.join(bp_dir, "config.json"))
    except Exception:
        config = {}
    column_keys = {
        str(col.get("key")) for col in config.get("columns", [])
        if isinstance(col, dict) and col.get("key")
    }
    if value in column_keys:
        return True
    if folded.startswith("worker:"):
        return bool(value[len("worker:"):].strip())
    if folded.startswith("pass:"):
        return value[len("pass:"):].strip().casefold() in {"left", "right", "up", "down", "random"}
    if folded.startswith("random:"):
        return True
    return False


def _validate_shell_ticket_updates(updates):
    if updates is None:
        return None
    if not isinstance(updates, dict):
        raise ValueError("ticket_updates must be an object")
    allowed = {"title", "priority", "tags", "body_append"}
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"ticket_updates contains disallowed field: {sorted(unknown)[0]}")
    clean = {}
    if "title" in updates:
        title = str(updates["title"])
        if len(title) > MAX_TITLE:
            raise ValueError("ticket_updates.title is too long")
        clean["title"] = title
    if "priority" in updates:
        priority = str(updates["priority"])
        if priority not in VALID_PRIORITIES:
            raise ValueError("ticket_updates.priority is invalid")
        clean["priority"] = priority
    if "tags" in updates:
        tags = updates["tags"]
        if not isinstance(tags, list):
            raise ValueError("ticket_updates.tags must be a list")
        if len(tags) > MAX_TAGS:
            raise ValueError("ticket_updates.tags has too many entries")
        clean_tags = []
        for tag in tags:
            if not isinstance(tag, str):
                raise ValueError("ticket_updates.tags entries must be strings")
            if len(tag) > MAX_TAG_LEN:
                raise ValueError("ticket_updates.tags contains an overlong tag")
            clean_tags.append(tag)
        clean["tags"] = clean_tags
    if "body_append" in updates:
        body_append = str(updates["body_append"])
        if len(body_append) > MAX_DESCRIPTION:
            raise ValueError("ticket_updates.body_append is too long")
        clean["body_append"] = body_append
    return clean


def _apply_shell_ticket_updates(bp_dir, task_id, updates):
    updates = dict(updates or {})
    body_append = updates.pop("body_append", None)
    if body_append:
        task = task_mod.read_task(bp_dir, task_id)
        body = task.get("body", "") if task else ""
        updates["body"] = body.rstrip() + "\n\n" + body_append + "\n"
    if updates:
        task_mod.update_task(bp_dir, task_id, updates)


def _cap_bytes(text, limit=SHELL_OUTPUT_ARTIFACT_LIMIT):
    data = (text or "").encode("utf-8", errors="replace")
    if len(data) <= limit:
        return data, False, len(data)
    marker = b"\n[bullpen output truncated]\n"
    return data[: max(0, limit - len(marker))] + marker, True, len(data)


def _decode_artifact(data):
    return data.decode("utf-8", errors="replace")


def _output_excerpt(text):
    data = (text or "").encode("utf-8", errors="replace")
    if len(data) <= SHELL_OUTPUT_EXCERPT_BYTES * 2:
        return _decode_artifact(data)
    head = data[:SHELL_OUTPUT_EXCERPT_BYTES]
    tail = data[-SHELL_OUTPUT_EXCERPT_BYTES:]
    return _decode_artifact(head) + "\n\n[bullpen middle output omitted]\n\n" + _decode_artifact(tail)


def _append_shell_run_record(bp_dir, task_id, worker, slot_index, result, completed, prepared, duration_ms):
    task = task_mod.read_task(bp_dir, task_id)
    if not task:
        return None

    output_block_id = f"shell-run-{_timestamp_id()}-slot{slot_index}"
    artifact_dir = os.path.join(bp_dir, "logs", "worker-runs", task_id)
    os.makedirs(artifact_dir, exist_ok=True)

    stdout_data, stdout_truncated, stdout_observed = _cap_bytes(completed.stdout)
    stderr_data, stderr_truncated, stderr_observed = _cap_bytes(completed.stderr)
    stdout_path = os.path.join(artifact_dir, f"{output_block_id}.stdout.log")
    stderr_path = os.path.join(artifact_dir, f"{output_block_id}.stderr.log")
    atomic_write(stdout_path, _decode_artifact(stdout_data))
    atomic_write(stderr_path, _decode_artifact(stderr_data))

    stdout_rel = os.path.relpath(stdout_path, os.path.dirname(bp_dir)).replace(os.sep, "/")
    stderr_rel = os.path.relpath(stderr_path, os.path.dirname(bp_dir)).replace(os.sep, "/")
    timestamp = _now_iso()
    history = list(task.get("history") or [])
    row = {
        "timestamp": timestamp,
        "event": "worker_run",
        "worker_type": "shell",
        "worker_name": worker.get("name", "Shell"),
        "worker_slot": slot_index,
        "task_id": task_id,
        "outcome": result.outcome,
        "disposition": result.disposition or worker.get("disposition", "review"),
        "reason": result.reason,
        "exit_code": completed.returncode,
        "duration_ms": duration_ms,
        "delivery": prepared.delivery,
        "delivery_fallback_from": prepared.delivery_fallback_from,
        "stdout_bytes": len(stdout_data),
        "stderr_bytes": len(stderr_data),
        "stdout_observed_bytes": stdout_observed,
        "stderr_observed_bytes": stderr_observed,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "stdout_artifact": stdout_rel,
        "stderr_artifact": stderr_rel,
        "body_excerpt_truncated": False,
        "output_block_id": output_block_id,
    }
    history.append(row)

    body = task.get("body", "")
    marker = "## Worker Output"
    idx = body.find(marker)
    if idx < 0:
        desc_part = body.rstrip()
        meta_part = ""
    else:
        desc_part = body[:idx].rstrip()
        meta_part = body[idx:].rstrip()

    meta_block = _build_shell_metadata_block(
        timestamp, worker, result, completed, prepared, row, stdout_rel, stderr_rel
    )

    def _assemble(desc_block):
        if desc_part:
            new_desc = desc_part + "\n\n" + desc_block
        else:
            new_desc = desc_block
        if meta_part:
            new_meta = meta_part + "\n\n" + meta_block
        else:
            new_meta = f"{marker}\n\n" + meta_block
        return new_desc.rstrip() + "\n\n" + new_meta.rstrip() + "\n"

    desc_block = _build_shell_description_block(timestamp, worker, completed, excerpt=False)
    proposed = _assemble(desc_block)
    if len(proposed.encode("utf-8", errors="replace")) > TASK_BODY_LIMIT:
        row["body_excerpt_truncated"] = True
        desc_block = _build_shell_description_block(timestamp, worker, completed, excerpt=True)
        proposed = _assemble(desc_block)
    if len(proposed.encode("utf-8", errors="replace")) > TASK_BODY_LIMIT:
        desc_block = _build_shell_description_stub(timestamp, worker, row, stdout_rel, stderr_rel)
        proposed = _assemble(desc_block)

    task_mod.update_task(bp_dir, task_id, {"history": history, "body": proposed})
    return row


def _build_shell_description_block(timestamp, worker, completed, excerpt):
    stdout_text = _output_excerpt(completed.stdout) if excerpt else (completed.stdout or "")
    stderr_text = _output_excerpt(completed.stderr) if excerpt else (completed.stderr or "")
    return (
        f"### {timestamp} - {worker.get('name', 'Shell')} (shell)\n\n"
        "#### stdout\n\n"
        "```text\n"
        f"{stdout_text}\n"
        "```\n\n"
        "#### stderr\n\n"
        "```text\n"
        f"{stderr_text}\n"
        "```\n"
    )


def _build_shell_description_stub(timestamp, worker, row, stdout_rel, stderr_rel):
    return (
        f"### {timestamp} - {worker.get('name', 'Shell')} (shell)\n\n"
        f"stdout bytes: {row['stdout_bytes']} (observed {row['stdout_observed_bytes']})\n"
        f"stderr bytes: {row['stderr_bytes']} (observed {row['stderr_observed_bytes']})\n"
        f"stdout artifact: {stdout_rel}\n"
        f"stderr artifact: {stderr_rel}\n"
        "[Output omitted from ticket body; see artifacts.]\n"
    )


def _build_shell_metadata_block(timestamp, worker, result, completed, prepared, row, stdout_rel, stderr_rel):
    return (
        f"### {timestamp} - {worker.get('name', 'Shell')} (shell)\n\n"
        f"Outcome: {result.outcome}\n"
        f"Disposition: {result.disposition or worker.get('disposition', 'review')}\n"
        f"Reason: {result.reason or 'none'}\n"
        f"Exit code: {completed.returncode}\n"
        f"Duration: {row['duration_ms'] / 1000:.3f}s\n"
        f"Delivery: {prepared.delivery}\n"
        f"stdout artifact: {stdout_rel}\n"
        f"stderr artifact: {stderr_rel}\n"
    )


def is_non_retryable_provider_error(provider, *texts):
    """Return True when provider output indicates retrying will not help."""
    provider = (provider or "").strip().lower()
    haystack = "\n".join([t for t in texts if isinstance(t, str)]).lower()
    if not haystack:
        return False

    if provider == "gemini":
        phrases = (
            "you have exhausted your capacity on this model",
            "exhausted your capacity",
            "resource has been exhausted",
            "quota exceeded",
            "exceeded your current quota",
            "retrying with exponential backoff",
            "exponential backoff",
        )
        return any(phrase in haystack for phrase in phrases)

    return False


def get_output_buffer(ws_id, slot_index):
    """Return the output buffer entry for a running process, or None."""
    with _process_lock:
        return _processes.get((ws_id, slot_index))


def _coerce_non_negative_int(value):
    """Convert value to non-negative int or return None."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


def _merge_live_usage_max(base, extra):
    """Merge normalized usage snapshots using per-field max values."""
    merged = {}
    for field in TOKEN_FIELDS:
        best = None
        for src in (base, extra):
            if not isinstance(src, dict):
                continue
            n = _coerce_non_negative_int(src.get(field))
            if n is None:
                continue
            best = n if best is None else max(best, n)
        if best is not None:
            merged[field] = best
    return merged


def _observe_provider_failure(adapter, line, proc, force_fail_message):
    if force_fail_message[0] is not None:
        return
    if not is_non_retryable_provider_error(adapter.name, line):
        return
    force_fail_message[0] = (
        "Gemini model capacity exhausted. "
        "Try gemini-2.5-flash or wait and retry later."
    )
    if proc.poll() is None:
        try:
            _terminate_proc(proc)
        except OSError:
            pass


def _run_agent(bp_dir, slot_index, task_id, argv, prompt, adapter, timeout, workspace, socketio, ws_id=None):
    """Run agent subprocess with streaming stdout and handle completion."""
    runner = None
    try:
        force_fail_message = [None]
        live_usage = [{}]
        last_live_tokens = [None]
        last_live_emit_at = [0.0]
        _deferred_timer = [None]

        def _emit_token_update(tokens):
            """Emit a task:updated event with the given token count."""
            task = task_mod.read_task(bp_dir, task_id)
            if not task or task.get("status") != "in_progress":
                return
            task["tokens"] = tokens
            _ws_emit(socketio, "task:updated", task, ws_id)
            last_live_tokens[0] = tokens
            last_live_emit_at[0] = time.time()

        def _deferred_emit():
            """Fire the pending token update after the throttle interval."""
            _deferred_timer[0] = None
            tokens = usage_to_legacy_tokens(live_usage[0])
            if tokens <= 0:
                return
            if last_live_tokens[0] is not None and tokens == last_live_tokens[0]:
                return
            _emit_token_update(tokens)

        def _maybe_emit_live_usage(line):
            if not socketio:
                return
            try:
                obj = json.loads((line or "").strip())
            except json.JSONDecodeError:
                return
            live_update = extract_stream_usage_event(adapter.name, obj)
            if not live_update:
                return

            live_usage[0] = _merge_live_usage_max(live_usage[0], live_update)
            tokens = usage_to_legacy_tokens(live_usage[0])
            if tokens <= 0:
                return

            if last_live_tokens[0] is not None and tokens == last_live_tokens[0]:
                return

            now = time.time()
            elapsed = now - last_live_emit_at[0]
            if elapsed < LIVE_TOKEN_EMIT_INTERVAL_SECONDS:
                # Throttled — schedule a deferred emit so this update is not lost.
                if _deferred_timer[0] is None:
                    delay = LIVE_TOKEN_EMIT_INTERVAL_SECONDS - elapsed
                    t = threading.Timer(delay, _deferred_emit)
                    t.daemon = True
                    _deferred_timer[0] = t
                    t.start()
                return

            # Cancel any pending deferred emit — we're emitting now.
            if _deferred_timer[0] is not None:
                _deferred_timer[0].cancel()
                _deferred_timer[0] = None

            _emit_token_update(tokens)

        try:
            stdin_text = prompt if adapter.prompt_via_stdin() else None
            def _observe_agent_line(line, stream, proc):
                _maybe_emit_live_usage(line)
                _observe_provider_failure(adapter, line, proc, force_fail_message)

            runner = SubprocessRunner(
                bp_dir=bp_dir,
                slot_index=slot_index,
                task_id=task_id,
                argv=argv,
                cwd=workspace,
                stdin_text=stdin_text,
                timeout=timeout,
                socketio=socketio,
                ws_id=ws_id,
                line_formatter=adapter.format_stream_line,
                line_observer=_observe_agent_line,
            )
            completed = runner.run()
        except FileNotFoundError:
            _block_agent_start_failure(
                bp_dir, slot_index, task_id, adapter.unavailable_message(), socketio, ws_id,
            )
            return

        stderr = completed.stderr

        if completed.timed_out:
            _on_agent_error(
                bp_dir,
                slot_index,
                task_id,
                "Agent timed out",
                socketio,
                ws_id=ws_id,
                run_id=runner.run_id if runner else None,
            )
            return

        stdout = completed.stdout
        exit_code = completed.returncode
        result = adapter.parse_output(stdout, stderr, exit_code)
        if force_fail_message[0] and not result.get("output"):
            result = {
                "success": False,
                "output": result.get("output", ""),
                "error": force_fail_message[0],
                "usage": result.get("usage", {}),
            }

        # Log the invocation
        _write_log(bp_dir, slot_index, task_id, prompt, result)

        # Emit final output so focus view always has complete data
        if socketio:
            final_lines = [l.rstrip("\n") for l in completed.combined_lines]
            _ws_emit(socketio, "worker:output:done", {"slot": slot_index, "lines": final_lines}, ws_id)

        if result["success"]:
            _on_agent_success(
                bp_dir,
                slot_index,
                task_id,
                result["output"],
                socketio,
                workspace,
                ws_id,
                result.get("usage", {}),
                run_id=runner.run_id if runner else None,
            )
        else:
            error_text = result.get("error", "Unknown error")
            output_text = result.get("output", "")
            _on_agent_error(
                bp_dir,
                slot_index,
                task_id,
                error_text,
                socketio,
                output_text,
                ws_id,
                non_retryable=is_non_retryable_provider_error(adapter.name, error_text, output_text, stderr),
                run_id=runner.run_id if runner else None,
            )

    except Exception as e:
        _on_agent_error(
            bp_dir,
            slot_index,
            task_id,
            str(e),
            socketio,
            ws_id=ws_id,
            run_id=runner.run_id if runner else None,
        )
    finally:
        with _process_lock:
            entry = _processes.get((ws_id, slot_index))
            if entry and entry.get("run_id") == (runner.run_id if runner else None):
                _processes.pop((ws_id, slot_index), None)
        # Clean up temp MCP config file if one was generated
        for i, arg in enumerate(argv):
            if arg == "--mcp-config" and i + 1 < len(argv):
                try:
                    os.unlink(argv[i + 1])
                except OSError:
                    pass
                break


def _pass_to_direction(bp_dir, slot_index, task_id, direction, layout, socketio, ws_id):
    """Pass a task to the worker in the given direction (up/down/left/right).

    Direction "random" picks uniformly from the four directions that have a worker
    neighbor; if none exist the task moves to Blocked. If no worker occupies the
    adjacent coordinate or the target is out of bounds, the task moves to Blocked.
    """
    config = read_json(os.path.join(bp_dir, "config.json"))
    grid = config.get("grid", {})
    try:
        cols = int(grid.get("cols", 4) or 4)
    except (TypeError, ValueError):
        cols = 4
    if cols <= 0:
        cols = 4

    slots = layout.get("slots", [])
    worker = slots[slot_index] if slot_index < len(slots) else None
    if worker:
        try:
            row = int(worker.get("row", slot_index // cols))
            col = int(worker.get("col", slot_index % cols))
        except (TypeError, ValueError):
            row = slot_index // cols
            col = slot_index % cols
    else:
        row = slot_index // cols
        col = slot_index % cols

    if direction == "random":
        def _neighbor_has_worker(tr, tc):
            for i, candidate in enumerate(slots):
                if not candidate:
                    continue
                try:
                    cr = int(candidate.get("row", i // cols))
                    cc = int(candidate.get("col", i % cols))
                except (TypeError, ValueError):
                    cr = i // cols
                    cc = i % cols
                if cr == tr and cc == tc:
                    return True
            return False

        candidates = []
        for d, (dr, dc) in (("up", (-1, 0)), ("down", (1, 0)), ("left", (0, -1)), ("right", (0, 1))):
            if _neighbor_has_worker(row + dr, col + dc):
                candidates.append(d)

        if not candidates:
            task = task_mod.read_task(bp_dir, task_id)
            msg = "\n\n**Pass random direction: no worker in any direction.** Task moved to blocked.\n"
            body = (task.get("body", "") if task else "") + msg
            task_mod.update_task(bp_dir, task_id, {
                "status": "blocked",
                "assigned_to": "",
                "body": body,
            })
            _save_layout(bp_dir, layout)
            if socketio:
                _ws_emit(socketio, "toast", {
                    "message": f"Task \"{task.get('title', task_id) if task else task_id}\" blocked: no neighbor worker in any direction",
                    "level": "warning",
                }, ws_id)
            return

        direction = random.choice(candidates)

    if direction == "up":
        target_row, target_col = row - 1, col
    elif direction == "down":
        target_row, target_col = row + 1, col
    elif direction == "left":
        target_row, target_col = row, col - 1
    elif direction == "right":
        target_row, target_col = row, col + 1
    else:
        target_row, target_col = -1, -1

    task = task_mod.read_task(bp_dir, task_id)
    limit = 100000
    if not (-limit <= target_row <= limit and -limit <= target_col <= limit):
        msg = f"\n\n**Pass {direction}: no slot in that direction.** Task moved to blocked.\n"
        body = (task.get("body", "") if task else "") + msg
        task_mod.update_task(bp_dir, task_id, {
            "status": "blocked",
            "assigned_to": "",
            "body": body,
        })
        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": f"Task \"{task.get('title', task_id) if task else task_id}\" blocked: no worker {direction}",
                "level": "warning",
            }, ws_id)
        return

    target_slot = None
    target_worker = None
    for i, candidate in enumerate(slots):
        if not candidate:
            continue
        try:
            candidate_row = int(candidate.get("row", i // cols))
            candidate_col = int(candidate.get("col", i % cols))
        except (TypeError, ValueError):
            candidate_row = i // cols
            candidate_col = i % cols
        if candidate_row == target_row and candidate_col == target_col:
            target_slot = i
            target_worker = candidate
            break

    # Empty slot → blocked
    if not target_worker:
        msg = f"\n\n**Pass {direction}: no worker at target slot.** Task moved to blocked.\n"
        body = (task.get("body", "") if task else "") + msg
        task_mod.update_task(bp_dir, task_id, {
            "status": "blocked",
            "assigned_to": "",
            "body": body,
        })
        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": f"Task \"{task.get('title', task_id) if task else task_id}\" blocked: no worker {direction}",
                "level": "warning",
            }, ws_id)
        return

    # Hand off to the target worker
    depth = task.get("handoff_depth", 0) if task else 0
    if _handoff_depth_limit_reached(depth):
        msg = f"\n\n**Handoff chain exceeded max depth ({MAX_HANDOFF_DEPTH}).** Task moved to blocked.\n"
        body = (task.get("body", "") if task else "") + msg
        task_mod.update_task(bp_dir, task_id, {
            "status": "blocked",
            "assigned_to": "",
            "body": body,
        })
        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": f"Task \"{task.get('title', task_id) if task else task_id}\" blocked: handoff depth exceeded",
                "level": "warning",
            }, ws_id)
        return

    task_mod.update_task(bp_dir, task_id, {"handoff_depth": depth + 1})
    _save_layout(bp_dir, layout)
    assign_task(bp_dir, target_slot, task_id, socketio, ws_id, preserve_handoff_depth=True)


def _on_agent_success(
    bp_dir,
    slot_index,
    task_id,
    output,
    socketio,
    agent_cwd=None,
    ws_id=None,
    usage=None,
    disposition_override=None,
    output_appender=None,
    allow_auto_actions=True,
    run_id=None,
):
    """Handle successful agent completion."""
    if _consume_cancelled_run(run_id):
        return
    try:
        with _write_lock:
            layout = _load_layout(bp_dir)
            worker = layout["slots"][slot_index]
            if not worker:
                return

            # Accumulate structured model usage and backward-compatible token totals.
            if usage:
                task = task_mod.read_task(bp_dir, task_id)
                if task:
                    usage_entry = build_usage_entry(
                        source="worker",
                        provider=worker.get("agent", ""),
                        model=worker.get("model"),
                        slot=slot_index,
                        usage=usage,
                    )
                    if usage_entry:
                        usage_update = build_usage_update(task, usage_entry)
                        if usage_update:
                            task_mod.update_task(bp_dir, task_id, usage_update)

            # Append output to task. Shell workers write structured Worker Output
            # blocks before entering this shared success path.
            if output_appender:
                output_appender(worker)
            else:
                _append_output(bp_dir, task_id, worker, output)

            # Auto-commit if enabled
            if allow_auto_actions and _auto_actions_allowed(worker) and worker.get("auto_commit") and agent_cwd:
                task = task_mod.read_task(bp_dir, task_id)
                task_title = task.get("title", "untitled") if task else "untitled"
                commit_hash = _auto_commit(agent_cwd, task_title, task_id)
                if commit_hash:
                    _append_output(bp_dir, task_id, worker, f"Commit: {commit_hash}")

                    # Auto-PR if enabled (requires worktree + auto-commit)
                    if worker.get("auto_pr") and worker.get("use_worktree"):
                        branch_name = f"bullpen/{task_id}"
                        pr_result = _auto_pr(agent_cwd, task_title, task_id, branch_name)
                        _append_output(bp_dir, task_id, worker, f"PR: {pr_result}")

            # Remove from queue
            queue = worker.get("task_queue", [])
            if queue and queue[0] == task_id:
                queue.pop(0)

            # Disposition: move task to target column or hand off to another worker
            disposition = disposition_override or worker.get("disposition", "review")
            handed_off = False
            if disposition.startswith("worker:"):
                target_name = disposition[len("worker:"):].strip()
                # Set worker idle BEFORE handoff (which saves its own layout)
                worker["state"] = "idle"
                _handoff_to_worker(bp_dir, task_id, target_name, layout, socketio, ws_id)
                handed_off = True
            elif disposition.startswith("pass:"):
                direction = disposition[len("pass:"):]
                worker["state"] = "idle"
                _pass_to_direction(bp_dir, slot_index, task_id, direction, layout, socketio, ws_id)
                handed_off = True
            elif disposition.startswith("random:"):
                target_name = disposition[len("random:"):].strip()
                worker["state"] = "idle"
                _pass_to_random_worker(bp_dir, slot_index, task_id, target_name, layout, socketio, ws_id)
                handed_off = True
            else:
                task_mod.update_task(bp_dir, task_id, {
                    "status": disposition,
                    "assigned_to": "",
                    "handoff_depth": 0,
                })

            if not handed_off:
                # Set worker idle and save (handoff path already did this)
                worker["state"] = "idle"
                _save_layout(bp_dir, layout)

            if socketio:
                task = task_mod.read_task(bp_dir, task_id)
                # Reload layout after potential handoff to get current state
                layout = _load_layout(bp_dir) if handed_off else layout
                _ws_emit(socketio, "task:updated", task, ws_id)
                _ws_emit(socketio, "layout:updated", layout, ws_id)
                _ws_emit(socketio, "files:changed", {}, ws_id)

            has_more = queue and worker.get("activation") in ("on_drop", "on_queue")
            disposition_status = None if handed_off else disposition

        # Outside lock to avoid deadlock with start_worker / assign_task
        if has_more:
            start_worker(bp_dir, slot_index, socketio, ws_id)
        else:
            # Idle refill: if this on_queue worker's queue is empty, look for more
            _refill_from_watch_column(bp_dir, slot_index, socketio, ws_id)

        # Notify watchers of the disposition column (e.g. worker A finishes → "review",
        # worker B watches "review" → auto-claims)
        if disposition_status:
            check_watch_columns(bp_dir, disposition_status, socketio, ws_id)
    except Exception as exc:
        _on_agent_error(
            bp_dir,
            slot_index,
            task_id,
            str(exc),
            socketio,
            ws_id=ws_id,
            non_retryable=True,
            max_retries_override=0,
            run_id=run_id,
        )


def _handoff_to_worker(bp_dir, task_id, target_name, layout, socketio, ws_id):
    """Hand off a completed task to another worker by name (weak binding)."""
    task = task_mod.read_task(bp_dir, task_id)
    depth = task.get("handoff_depth", 0) if task else 0

    if _handoff_depth_limit_reached(depth):
        msg = f"\n\n**Handoff chain exceeded max depth ({MAX_HANDOFF_DEPTH}).** Task moved to blocked.\n"
        body = (task.get("body", "") if task else "") + msg
        task_mod.update_task(bp_dir, task_id, {
            "status": "blocked",
            "assigned_to": "",
            "body": body,
        })
        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": f"Task \"{task.get('title', task_id)}\" blocked: handoff depth exceeded",
                "level": "warning",
            }, ws_id)
        return

    # Find target worker by name (case-insensitive, whitespace-insensitive)
    target_slot = None
    normalized_target = _normalize_worker_name(target_name)
    for i, slot in enumerate(layout.get("slots", [])):
        if slot and _normalize_worker_name(slot.get("name")) == normalized_target:
            target_slot = i
            break

    if target_slot is None:
        msg = f"\n\n**Handoff target \"{target_name}\" not found.** Task moved to blocked.\n"
        body = (task.get("body", "") if task else "") + msg
        task_mod.update_task(bp_dir, task_id, {
            "status": "blocked",
            "assigned_to": "",
            "body": body,
        })
        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": f"Task \"{task.get('title', task_id)}\" blocked: worker \"{target_name}\" not found",
                "level": "warning",
            }, ws_id)
        return

    # Increment depth and hand off
    task_mod.update_task(bp_dir, task_id, {"handoff_depth": depth + 1})
    # Save layout before assign_task (which reloads it)
    _save_layout(bp_dir, layout)
    assign_task(bp_dir, target_slot, task_id, socketio, ws_id, preserve_handoff_depth=True)


def _pass_to_random_worker(bp_dir, slot_index, task_id, target_name, layout, socketio, ws_id):
    """Pass a completed task to a random worker whose name matches target_name.

    Blank target_name matches any worker. The sender is excluded from candidates.
    If no candidate exists, the task moves to Blocked.
    """
    task = task_mod.read_task(bp_dir, task_id)
    depth = task.get("handoff_depth", 0) if task else 0

    if _handoff_depth_limit_reached(depth):
        msg = f"\n\n**Handoff chain exceeded max depth ({MAX_HANDOFF_DEPTH}).** Task moved to blocked.\n"
        body = (task.get("body", "") if task else "") + msg
        task_mod.update_task(bp_dir, task_id, {
            "status": "blocked",
            "assigned_to": "",
            "body": body,
        })
        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": f"Task \"{task.get('title', task_id) if task else task_id}\" blocked: handoff depth exceeded",
                "level": "warning",
            }, ws_id)
        return

    candidates = []
    normalized_target = _normalize_worker_name(target_name)
    for i, slot in enumerate(layout.get("slots", [])):
        if not slot or i == slot_index:
            continue
        if not normalized_target or _normalize_worker_name(slot.get("name")) == normalized_target:
            candidates.append(i)

    if not candidates:
        label = f"matching \"{target_name}\"" if target_name else "available"
        msg = f"\n\n**Random pass: no worker {label}.** Task moved to blocked.\n"
        body = (task.get("body", "") if task else "") + msg
        task_mod.update_task(bp_dir, task_id, {
            "status": "blocked",
            "assigned_to": "",
            "body": body,
        })
        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "toast", {
                "message": f"Task \"{task.get('title', task_id) if task else task_id}\" blocked: no random worker {label}",
                "level": "warning",
            }, ws_id)
        return

    target_slot = random.choice(candidates)
    task_mod.update_task(bp_dir, task_id, {"handoff_depth": depth + 1})
    _save_layout(bp_dir, layout)
    assign_task(bp_dir, target_slot, task_id, socketio, ws_id, preserve_handoff_depth=True)


def _on_agent_error(
    bp_dir,
    slot_index,
    task_id,
    error_msg,
    socketio,
    output="",
    ws_id=None,
    non_retryable=False,
    max_retries_override=None,
    run_id=None,
):
    """Handle agent failure. Retry or block."""
    if _consume_cancelled_run(run_id):
        return
    should_retry = False
    retry_delay = 0
    should_advance = False

    with _write_lock:
        try:
            layout = _load_layout(bp_dir)
        except FileNotFoundError:
            return
        worker = layout["slots"][slot_index]
        if not worker:
            return

        # If the task was removed from the queue externally (e.g. a human
        # dragged it out of in_progress mid-run), skip retry — otherwise
        # start_worker would find an empty queue and create a spurious
        # auto-task. Agent self-updates no longer trigger yank (see
        # on_task_update in events.py), so this path is rare.
        queue = worker.get("task_queue", [])
        if task_id not in queue:
            return

        max_retries = worker.get("max_retries", 1) if max_retries_override is None else max_retries_override
        task = task_mod.read_task(bp_dir, task_id)
        if not task:
            return

        # Count existing retries from history
        history = task.get("history", [])
        retry_count = sum(1 for h in history if h.get("event") == "retry")

        if (not non_retryable) and retry_count < max_retries:
            # Retry with backoff
            retry_delay = 5 * (retry_count + 1)
            history.append({"timestamp": _now_iso(), "event": "retry", "detail": error_msg})
            task_mod.update_task(bp_dir, task_id, {"history": history})

            if output:
                _append_output(bp_dir, task_id, worker, f"[ERROR] {error_msg}\n\n{output}")

            should_retry = True
        else:
            # Max retries exceeded — block task
            queue = worker.get("task_queue", [])
            if queue and queue[0] == task_id:
                queue.pop(0)

            if output:
                _append_output(bp_dir, task_id, worker, f"[BLOCKED] {error_msg}\n\n{output}")
            else:
                _append_output(bp_dir, task_id, worker, f"[BLOCKED] {error_msg}")

            task_mod.update_task(bp_dir, task_id, {
                "status": "blocked",
                "assigned_to": "",
            })

            worker["state"] = "idle"
            _save_layout(bp_dir, layout)

            if socketio:
                task = task_mod.read_task(bp_dir, task_id)
                _ws_emit(socketio, "task:updated", task, ws_id)
                _ws_emit(socketio, "layout:updated", layout, ws_id)

            should_advance = queue and worker.get("activation") in ("on_drop", "on_queue")

    # Schedule retry or advance outside lock
    if should_retry:
        def do_retry():
            time.sleep(retry_delay)
            start_worker(bp_dir, slot_index, socketio, ws_id)
        threading.Thread(target=do_retry, daemon=True).start()
    elif should_advance:
        start_worker(bp_dir, slot_index, socketio, ws_id)
    else:
        # Idle refill for on_queue workers with empty queue
        _refill_from_watch_column(bp_dir, slot_index, socketio, ws_id)

    # Notify watchers of "blocked" column (unlikely but consistent)
    if not should_retry:
        check_watch_columns(bp_dir, "blocked", socketio, ws_id)


def _append_output(bp_dir, task_id, worker, output):
    """Append agent output to task under ## Agent Output heading."""
    task = task_mod.read_task(bp_dir, task_id)
    if not task:
        return

    body = task.get("body", "")
    timestamp = _now_iso()
    worker_name = worker.get("name", "Agent")
    agent_info = f"{worker.get('agent', '?')}/{worker.get('model', '?')}"

    header = f"\n### {timestamp} — {worker_name} ({agent_info})\n\n"

    # Cap output at 50KB
    if len(output) > 50000:
        output = output[:50000] + "\n\n[Output truncated at 50KB]"

    if "## Agent Output" not in body:
        body = body.rstrip() + "\n\n## Agent Output\n"

    body += header + output + "\n"

    task_mod.update_task(bp_dir, task_id, {"body": body})


def _write_log(bp_dir, slot_index, task_id, prompt, result):
    """Write an agent invocation log."""
    logs_dir = os.path.join(bp_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Enforce max 100 log files per slot
    prefix = f"slot-{slot_index}-"
    existing = sorted(f for f in os.listdir(logs_dir) if f.startswith(prefix))
    while len(existing) >= 100:
        os.remove(os.path.join(logs_dir, existing.pop(0)))

    timestamp = _now_iso().replace(":", "-")
    log_name = f"{prefix}{timestamp}.log"
    log_path = os.path.join(logs_dir, log_name)

    # Truncate prompt in log
    log_prompt = prompt[:500] + "..." if len(prompt) > 500 else prompt

    output_text = result.get('output', '')
    content = f"Task: {task_id}\nTimestamp: {_now_iso()}\nSuccess: {result['success']}\n"
    content += f"Output length: {len(output_text)} chars\n\n"
    content += f"--- Prompt (truncated) ---\n{log_prompt}\n\n"
    content += f"--- Output ---\n{output_text}\n"
    if result.get("error"):
        content += f"\n--- Error ---\n{result['error']}\n"

    atomic_write(log_path, content)
