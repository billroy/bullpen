"""Worker state machine, queue management, agent execution."""

import os
import subprocess
import threading
import time
from datetime import datetime, timezone

from server.agents import get_adapter
from server.persistence import read_json, write_json, atomic_write
from server import tasks as task_mod


# Active subprocesses keyed by slot index
_processes = {}
_process_lock = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_layout(bp_dir):
    return read_json(os.path.join(bp_dir, "layout.json"))


def _save_layout(bp_dir, layout):
    write_json(os.path.join(bp_dir, "layout.json"), layout)


def assign_task(bp_dir, slot_index, task_id, socketio=None):
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
        socketio.emit("task:updated", task)
        socketio.emit("layout:updated", layout)

    # Check if worker should auto-start
    activation = worker.get("activation", "on_drop")
    if activation in ("on_drop", "on_queue") and worker.get("state") == "idle":
        start_worker(bp_dir, slot_index, socketio)


def start_worker(bp_dir, slot_index, socketio=None):
    """Dequeue next task and invoke agent."""
    layout = _load_layout(bp_dir)
    worker = layout["slots"][slot_index]
    if not worker:
        return

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
            start_worker(bp_dir, slot_index, socketio)
        return

    # Update state
    worker["state"] = "working"
    task_mod.update_task(bp_dir, task_id, {"status": "in_progress"})
    _save_layout(bp_dir, layout)

    if socketio:
        updated_task = task_mod.read_task(bp_dir, task_id)
        socketio.emit("task:updated", updated_task)
        socketio.emit("layout:updated", layout)

    # Build prompt
    prompt = _assemble_prompt(bp_dir, worker, task)
    workspace = os.path.dirname(bp_dir)  # workspace is parent of .bullpen

    # Get adapter
    adapter = get_adapter(worker.get("agent", "claude"))
    if not adapter:
        _on_agent_error(bp_dir, slot_index, task_id, f"Unknown agent: {worker.get('agent')}", socketio)
        return

    model = worker.get("model", "sonnet")
    argv = adapter.build_argv(prompt, model, workspace)

    # Launch subprocess in background thread
    config = read_json(os.path.join(bp_dir, "config.json"))
    timeout = config.get("agent_timeout_seconds", 600)

    thread = threading.Thread(
        target=_run_agent,
        args=(bp_dir, slot_index, task_id, argv, prompt, adapter, timeout, workspace, socketio),
        daemon=True,
    )
    thread.start()


def stop_worker(bp_dir, slot_index, socketio=None):
    """Stop a working agent. Task goes back to Assigned."""
    with _process_lock:
        proc = _processes.get(slot_index)
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
                socketio.emit("task:updated", task)

        _save_layout(bp_dir, layout)
        if socketio:
            socketio.emit("layout:updated", layout)


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


def _run_agent(bp_dir, slot_index, task_id, argv, prompt, adapter, timeout, workspace, socketio):
    """Run agent subprocess and handle completion."""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            text=True,
        )

        with _process_lock:
            _processes[slot_index] = proc

        # Write prompt to stdin
        try:
            stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            _on_agent_error(bp_dir, slot_index, task_id, "Agent timed out", socketio)
            return

        exit_code = proc.returncode
        result = adapter.parse_output(stdout, stderr, exit_code)

        # Log the invocation
        _write_log(bp_dir, slot_index, task_id, prompt, result)

        if result["success"]:
            _on_agent_success(bp_dir, slot_index, task_id, result["output"], socketio)
        else:
            _on_agent_error(bp_dir, slot_index, task_id, result.get("error", "Unknown error"), socketio, result.get("output", ""))

    except Exception as e:
        _on_agent_error(bp_dir, slot_index, task_id, str(e), socketio)
    finally:
        with _process_lock:
            _processes.pop(slot_index, None)


def _on_agent_success(bp_dir, slot_index, task_id, output, socketio):
    """Handle successful agent completion."""
    layout = _load_layout(bp_dir)
    worker = layout["slots"][slot_index]
    if not worker:
        return

    # Append output to task
    _append_output(bp_dir, task_id, worker, output)

    # Remove from queue
    queue = worker.get("task_queue", [])
    if queue and queue[0] == task_id:
        queue.pop(0)

    # Disposition: move task to target column
    disposition = worker.get("disposition", "review")
    task_mod.update_task(bp_dir, task_id, {
        "status": disposition,
        "assigned_to": "",
    })

    # Set worker idle and check for next task
    worker["state"] = "idle"
    _save_layout(bp_dir, layout)

    if socketio:
        task = task_mod.read_task(bp_dir, task_id)
        socketio.emit("task:updated", task)
        socketio.emit("layout:updated", layout)

    # Auto-advance if more tasks in queue
    if queue and worker.get("activation") in ("on_drop", "on_queue"):
        start_worker(bp_dir, slot_index, socketio)


def _on_agent_error(bp_dir, slot_index, task_id, error_msg, socketio, output=""):
    """Handle agent failure. Retry or block."""
    layout = _load_layout(bp_dir)
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
        delay = 5 * (retry_count + 1)
        history.append({"timestamp": _now_iso(), "event": "retry", "detail": error_msg})
        task_mod.update_task(bp_dir, task_id, {"history": history})

        if output:
            _append_output(bp_dir, task_id, worker, f"[ERROR] {error_msg}\n\n{output}")

        # Schedule retry
        def do_retry():
            time.sleep(delay)
            start_worker(bp_dir, slot_index, socketio)

        threading.Thread(target=do_retry, daemon=True).start()
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
            socketio.emit("task:updated", task)
            socketio.emit("layout:updated", layout)

        # Try next task in queue
        if queue and worker.get("activation") in ("on_drop", "on_queue"):
            start_worker(bp_dir, slot_index, socketio)


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

    content = f"Task: {task_id}\nTimestamp: {_now_iso()}\nSuccess: {result['success']}\n\n"
    content += f"--- Prompt (truncated) ---\n{log_prompt}\n\n"
    content += f"--- Output ---\n{result.get('output', '')}\n"
    if result.get("error"):
        content += f"\n--- Error ---\n{result['error']}\n"

    atomic_write(log_path, content)
