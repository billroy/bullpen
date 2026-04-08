"""Worker state machine, queue management, agent execution."""

import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

from server.agents import get_adapter
from server.locks import write_lock as _write_lock
from server.persistence import read_json, write_json, atomic_write
from server import tasks as task_mod

MAX_HANDOFF_DEPTH = 10


# Active subprocesses keyed by (workspace_id, slot_index)
_processes = {}
_process_lock = threading.Lock()


def _ws_emit(socketio, event, payload, ws_id=None):
    """Emit a socket event with workspaceId attached, scoped to workspace room."""
    if ws_id and isinstance(payload, dict):
        payload["workspaceId"] = ws_id
    socketio.emit(event, payload, to=ws_id)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_layout(bp_dir):
    return read_json(os.path.join(bp_dir, "layout.json"))


def _save_layout(bp_dir, layout):
    write_json(os.path.join(bp_dir, "layout.json"), layout)


def create_auto_task(bp_dir, slot_index, worker, socketio=None):
    """Create an ephemeral task for a self-directed worker with no queue."""
    worker_name = worker.get("name", "Worker")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    title = f"[Auto] {worker_name} — {timestamp}"

    task = task_mod.create_task(bp_dir, title, task_type="chore")
    assign_task(bp_dir, slot_index, task["id"], socketio)
    return task


def assign_task(bp_dir, slot_index, task_id, socketio=None, ws_id=None):
    """Add task to worker's queue, update ticket status."""
    layout = _load_layout(bp_dir)
    worker = layout["slots"][slot_index]
    if not worker:
        raise ValueError(f"No worker in slot {slot_index}")

    # Update task ticket
    task_mod.update_task(bp_dir, task_id, {
        "assigned_to": str(slot_index),
        "status": "assigned",
    })

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


def start_worker(bp_dir, slot_index, socketio=None, ws_id=None):
    """Dequeue next task and invoke agent."""
    layout = _load_layout(bp_dir)
    worker = layout["slots"][slot_index]
    if not worker:
        return

    queue = worker.get("task_queue", [])
    if not queue:
        # Auto-create a task for manual start with empty queue
        auto_task = create_auto_task(bp_dir, slot_index, worker, socketio)
        # Re-read layout since assign_task modified it
        layout = _load_layout(bp_dir)
        worker = layout["slots"][slot_index]
        queue = worker.get("task_queue", [])
        if not queue:
            return

    task_id = queue[0]
    task = task_mod.read_task(bp_dir, task_id)
    if not task:
        # Task was deleted, remove from queue and try next
        queue.pop(0)
        _save_layout(bp_dir, layout)
        if queue:
            start_worker(bp_dir, slot_index, socketio, ws_id)
        return

    # Update state
    worker["state"] = "working"
    worker["started_at"] = _now_iso()
    task_mod.update_task(bp_dir, task_id, {"status": "in_progress"})
    _save_layout(bp_dir, layout)

    if socketio:
        updated_task = task_mod.read_task(bp_dir, task_id)
        _ws_emit(socketio, "task:updated", updated_task, ws_id)
        _ws_emit(socketio, "layout:updated", layout, ws_id)

    # Build prompt
    prompt = _assemble_prompt(bp_dir, worker, task)
    workspace = os.path.dirname(bp_dir)  # workspace is parent of .bullpen

    # Worktree setup
    agent_cwd = workspace
    if worker.get("use_worktree"):
        try:
            agent_cwd = _setup_worktree(workspace, bp_dir, task_id)
        except Exception as e:
            _on_agent_error(bp_dir, slot_index, task_id, f"Worktree setup failed: {e}", socketio, ws_id=ws_id)
            return

    # Get adapter
    adapter = get_adapter(worker.get("agent", "claude"))
    if not adapter:
        _on_agent_error(bp_dir, slot_index, task_id, f"Unknown agent: {worker.get('agent')}", socketio, ws_id=ws_id)
        return

    model = worker.get("model", "claude-sonnet-4-6")
    argv = adapter.build_argv(prompt, model, agent_cwd)

    # Launch subprocess in background thread
    config = read_json(os.path.join(bp_dir, "config.json"))
    timeout = config.get("agent_timeout_seconds", 600)

    thread = threading.Thread(
        target=_run_agent,
        args=(bp_dir, slot_index, task_id, argv, prompt, adapter, timeout, agent_cwd, socketio, ws_id),
        daemon=True,
    )
    thread.start()


def stop_worker(bp_dir, slot_index, socketio=None, ws_id=None):
    """Stop a working agent. Task goes back to Assigned."""
    with _process_lock:
        entry = _processes.get((ws_id, slot_index))
        proc = entry["proc"] if entry else None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    layout = _load_layout(bp_dir)
    worker = layout["slots"][slot_index]
    if worker:
        worker["state"] = "idle"
        queue = worker.get("task_queue", [])
        if queue:
            task_id = queue[0]
            task_mod.update_task(bp_dir, task_id, {"status": "assigned"})
            if socketio:
                task = task_mod.read_task(bp_dir, task_id)
                _ws_emit(socketio, "task:updated", task, ws_id)

        _save_layout(bp_dir, layout)
        if socketio:
            _ws_emit(socketio, "layout:updated", layout, ws_id)


def _assemble_prompt(bp_dir, worker, task):
    """Build the full prompt for the agent."""
    parts = []

    # Workspace prompt
    wp_path = os.path.join(bp_dir, "workspace_prompt.md")
    if os.path.exists(wp_path):
        wp = open(wp_path).read().strip()
        if wp:
            parts.append(f"## Workspace Context\n\n{wp}")

    # Bullpen prompt
    bp_path = os.path.join(bp_dir, "bullpen_prompt.md")
    if os.path.exists(bp_path):
        bp = open(bp_path).read().strip()
        if bp:
            parts.append(f"## Bullpen Context\n\n{bp}")

    # Expertise prompt
    expertise = worker.get("expertise_prompt", "")
    if expertise:
        parts.append(f"## Your Role\n\n{expertise}")

    # Task body
    parts.append(f"## Task: {task.get('title', 'Untitled')}\n")
    parts.append(f"Type: {task.get('type', 'task')}")
    parts.append(f"Priority: {task.get('priority', 'normal')}")
    if task.get("tags"):
        parts.append(f"Tags: {', '.join(task['tags'])}")
    if task.get("body"):
        parts.append(f"\n{task['body']}")

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


def get_output_buffer(ws_id, slot_index):
    """Return the output buffer entry for a running process, or None."""
    with _process_lock:
        return _processes.get((ws_id, slot_index))


def _run_agent(bp_dir, slot_index, task_id, argv, prompt, adapter, timeout, workspace, socketio, ws_id=None):
    """Run agent subprocess with streaming stdout and handle completion."""
    timed_out = False

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            text=True,
        )

        entry = {"proc": proc, "buffer": [], "task_id": task_id, "buffer_size": 0}
        with _process_lock:
            _processes[(ws_id, slot_index)] = entry

        # Write prompt to stdin, then close so agent can begin
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass  # Agent may have exited immediately

        # Watchdog timer to kill process on timeout
        def _watchdog():
            nonlocal timed_out
            timed_out = True
            if proc.poll() is None:
                proc.kill()

        timer = threading.Timer(timeout, _watchdog)
        timer.daemon = True
        timer.start()

        # Stream stdout line by line
        output_lines = []
        batch = []
        last_emit = time.time()

        try:
            for line in proc.stdout:
                if len(line) > MAX_LINE_LEN:
                    line = line[:MAX_LINE_LEN] + "[line truncated]\n"
                output_lines.append(line)
                stripped = line.rstrip("\n")
                batch.append(stripped)

                # Append to server-side buffer (cap at MAX_OUTPUT_BUFFER)
                with _process_lock:
                    e = _processes.get((ws_id, slot_index))
                    if e:
                        e["buffer"].append(stripped)
                        e["buffer_size"] += len(stripped) + 1
                        while e["buffer_size"] > MAX_OUTPUT_BUFFER and e["buffer"]:
                            removed = e["buffer"].pop(0)
                            e["buffer_size"] -= len(removed) + 1

                # Batch emit every 200ms
                now = time.time()
                if socketio and now - last_emit >= 0.2:
                    _ws_emit(socketio, "worker:output", {"slot": slot_index, "lines": batch}, ws_id)
                    last_emit = now
                    batch = []
        except (ValueError, OSError):
            pass  # stdout closed

        # Flush remaining batch
        if socketio and batch:
            _ws_emit(socketio, "worker:output", {"slot": slot_index, "lines": batch}, ws_id)

        # Wait for process to finish and read stderr
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        timer.cancel()

        stderr = ""
        try:
            stderr = proc.stderr.read()
        except (ValueError, OSError):
            pass

        if timed_out:
            _on_agent_error(bp_dir, slot_index, task_id, "Agent timed out", socketio, ws_id=ws_id)
            return

        stdout = "".join(output_lines)
        exit_code = proc.returncode
        result = adapter.parse_output(stdout, stderr, exit_code)

        # Log the invocation
        _write_log(bp_dir, slot_index, task_id, prompt, result)

        if result["success"]:
            _on_agent_success(bp_dir, slot_index, task_id, result["output"], socketio, workspace, ws_id)
        else:
            _on_agent_error(bp_dir, slot_index, task_id, result.get("error", "Unknown error"), socketio, result.get("output", ""), ws_id)

    except Exception as e:
        _on_agent_error(bp_dir, slot_index, task_id, str(e), socketio, ws_id=ws_id)
    finally:
        with _process_lock:
            _processes.pop((ws_id, slot_index), None)


def _on_agent_success(bp_dir, slot_index, task_id, output, socketio, agent_cwd=None, ws_id=None):
    """Handle successful agent completion."""
    with _write_lock:
        layout = _load_layout(bp_dir)
        worker = layout["slots"][slot_index]
        if not worker:
            return

        # Append output to task
        _append_output(bp_dir, task_id, worker, output)

        # Auto-commit if enabled
        if worker.get("auto_commit") and agent_cwd:
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
        disposition = worker.get("disposition", "review")
        handed_off = False
        if disposition.startswith("worker:"):
            target_name = disposition[len("worker:"):]
            # Set worker idle BEFORE handoff (which saves its own layout)
            worker["state"] = "idle"
            _handoff_to_worker(bp_dir, task_id, target_name, layout, socketio, ws_id)
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

    # Auto-advance outside lock to avoid deadlock with start_worker
    if has_more:
        start_worker(bp_dir, slot_index, socketio, ws_id)


def _handoff_to_worker(bp_dir, task_id, target_name, layout, socketio, ws_id):
    """Hand off a completed task to another worker by name (weak binding)."""
    task = task_mod.read_task(bp_dir, task_id)
    depth = task.get("handoff_depth", 0) if task else 0

    if depth >= MAX_HANDOFF_DEPTH:
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

    # Find target worker by name
    target_slot = None
    for i, slot in enumerate(layout.get("slots", [])):
        if slot and slot.get("name") == target_name:
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
    assign_task(bp_dir, target_slot, task_id, socketio, ws_id)


def _on_agent_error(bp_dir, slot_index, task_id, error_msg, socketio, output="", ws_id=None):
    """Handle agent failure. Retry or block."""
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

        max_retries = worker.get("max_retries", 1)
        task = task_mod.read_task(bp_dir, task_id)
        if not task:
            return

        # Count existing retries from history
        history = task.get("history", [])
        retry_count = sum(1 for h in history if h.get("event") == "retry")

        if retry_count < max_retries:
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

            task_mod.update_task(bp_dir, task_id, {
                "status": "blocked",
                "assigned_to": "",
            })

            if output:
                _append_output(bp_dir, task_id, worker, f"[BLOCKED] {error_msg}\n\n{output}")
            else:
                _append_output(bp_dir, task_id, worker, f"[BLOCKED] {error_msg}")

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
