"""Socket event handlers."""

import logging
import os
import subprocess
import threading

from flask import request
from flask_socketio import emit

from server import tasks as task_mod
from server.persistence import read_json, write_json, atomic_write
from server.profiles import create_profile, list_profiles
from server.teams import save_team, load_team, list_teams
from server import workers as worker_mod
from server.locks import write_lock as _write_lock
from server.validation import (
    ValidationError, validate_task_create, validate_task_update,
    validate_id, validate_slot, validate_worker_configure,
    validate_payload_size, validate_config_update, validate_worker_move,
    validate_layout_update, validate_team_name,
)


def _load_layout(bp_dir):
    return read_json(os.path.join(bp_dir, "layout.json"))


def _save_layout(bp_dir, layout):
    write_json(os.path.join(bp_dir, "layout.json"), layout)


def register_events(socketio, app):
    """Register all socket.io event handlers."""

    def _resolve(data):
        """Resolve workspaceId from event data, return (workspace_id, bp_dir)."""
        manager = app.config["manager"]
        ws_id = data.get("workspaceId") if isinstance(data, dict) else None
        if not ws_id:
            ws_id = app.config["startup_workspace_id"]
        return ws_id, manager.get_bp_dir(ws_id)

    def _emit(event, payload, ws_id):
        """Emit an event with workspaceId attached, scoped to workspace room."""
        if isinstance(payload, dict):
            payload["workspaceId"] = ws_id
        socketio.emit(event, payload, to=ws_id)

    def with_lock(fn):
        """Execute fn under write lock, emit error on failure."""
        def wrapper(data):
            with _write_lock:
                try:
                    return fn(data)
                except ValidationError as e:
                    emit("error", {"message": str(e)})
                except Exception as e:
                    logging.exception("Unhandled error in %s", fn.__name__)
                    emit("error", {"message": "An internal error occurred"})
        wrapper.__name__ = fn.__name__
        return wrapper

    # --- Task events ---

    @socketio.on("task:create")
    @with_lock
    def on_task_create(data):
        ws_id, bp_dir = _resolve(data)
        clean = validate_task_create(data)
        task = task_mod.create_task(
            bp_dir,
            title=clean["title"],
            description=clean["description"],
            task_type=clean["type"],
            priority=clean["priority"],
            tags=clean["tags"],
        )
        _emit("task:created", task, ws_id)

        # Check if any on_queue workers are watching the new task's column
        if task.get("status"):
            worker_mod.check_watch_columns(
                bp_dir, task["status"], socketio, ws_id,
            )

    @socketio.on("task:update")
    @with_lock
    def on_task_update(data):
        ws_id, bp_dir = _resolve(data)
        task_id, fields = validate_task_update(data)
        task = task_mod.update_task(bp_dir, task_id, fields)
        _emit("task:updated", task, ws_id)

        # If status changed, check if any on_queue workers are watching that column
        if "status" in fields:
            worker_mod.check_watch_columns(
                bp_dir, fields["status"], socketio, ws_id,
            )

    @socketio.on("task:delete")
    @with_lock
    def on_task_delete(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data)
        task_mod.delete_task(bp_dir, task_id)
        _emit("task:deleted", {"id": task_id}, ws_id)

    @socketio.on("task:archive")
    @with_lock
    def on_task_archive(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data)
        task_mod.archive_task(bp_dir, task_id)
        _emit("task:deleted", {"id": task_id}, ws_id)

    @socketio.on("task:archive-done")
    @with_lock
    def on_task_archive_done(data):
        ws_id, bp_dir = _resolve(data)
        archived = task_mod.archive_done_tasks(bp_dir)
        for task_id in archived:
            _emit("task:deleted", {"id": task_id}, ws_id)

    @socketio.on("task:clear_output")
    @with_lock
    def on_task_clear_output(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data)
        task = task_mod.clear_task_output(bp_dir, task_id)
        _emit("task:updated", task, ws_id)

    # --- Worker / Layout events ---

    @socketio.on("worker:add")
    @with_lock
    def on_worker_add(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        slot_index = validate_slot(data, max_slots=200)
        profile_id = data.get("profile")

        if profile_id is None:
            emit("error", {"message": "worker:add requires profile"})
            return

        # Get profile data for defaults
        from server.profiles import get_profile
        profile = get_profile(bp_dir, profile_id)
        if not profile:
            emit("error", {"message": f"Profile not found: {profile_id}"})
            return

        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = config.get("grid", {}).get("cols", 6)
        row = slot_index // cols
        col = slot_index % cols

        # Suggest a unique display name
        base_name = profile["name"]
        existing_names = {s["name"] for s in layout["slots"] if s}
        candidate = base_name
        suffix = 2
        while candidate in existing_names:
            candidate = f"{base_name} {suffix}"
            suffix += 1

        worker = {
            "row": row,
            "col": col,
            "profile": profile_id,
            "name": candidate,
            "agent": profile.get("default_agent", "claude"),
            "model": profile.get("default_model", "claude-sonnet-4-6"),
            "activation": "on_drop",
            "disposition": "review",
            "watch_column": None,
            "expertise_prompt": profile.get("expertise_prompt", ""),
            "max_retries": 1,
            "use_worktree": False,
            "auto_commit": False,
            "auto_pr": False,
            "trigger_time": None,
            "trigger_interval_minutes": None,
            "trigger_every_day": False,
            "last_trigger_time": None,
            "paused": False,
            "task_queue": [],
            "state": "idle",
        }

        # Ensure slots list is large enough
        while len(layout["slots"]) <= slot_index:
            layout["slots"].append(None)

        layout["slots"][slot_index] = worker
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:remove")
    @with_lock
    def on_worker_remove(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        slot_index = data.get("slot")

        if slot_index is None or slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:remove requires valid slot"})
            return

        layout["slots"][slot_index] = None
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:move")
    @with_lock
    def on_worker_move(data):
        ws_id, bp_dir = _resolve(data)
        from_slot, to_slot = validate_worker_move(data)
        layout = _load_layout(bp_dir)

        # Ensure slots list is large enough
        max_slot = max(from_slot, to_slot)
        while len(layout["slots"]) <= max_slot:
            layout["slots"].append(None)

        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = config.get("grid", {}).get("cols", 6)

        # Swap
        layout["slots"][from_slot], layout["slots"][to_slot] = (
            layout["slots"][to_slot], layout["slots"][from_slot]
        )

        # Update row/col
        for i in [from_slot, to_slot]:
            if layout["slots"][i]:
                layout["slots"][i]["row"] = i // cols
                layout["slots"][i]["col"] = i % cols

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:duplicate")
    @with_lock
    def on_worker_duplicate(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        slot_index = data.get("slot")

        if slot_index is None or slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:duplicate requires valid slot"})
            return

        source = layout["slots"][slot_index]
        if not source:
            emit("error", {"message": "No worker in slot"})
            return

        # Find first empty slot
        config = read_json(os.path.join(bp_dir, "config.json"))
        rows = config.get("grid", {}).get("rows", 4)
        cols = config.get("grid", {}).get("cols", 6)
        total = rows * cols

        while len(layout["slots"]) < total:
            layout["slots"].append(None)

        target = None
        for i in range(total):
            if layout["slots"][i] is None:
                target = i
                break

        if target is None:
            emit("error", {"message": "No empty slot available"})
            return

        # Generate unique name
        base_name = source["name"]
        existing_names = {s["name"] for s in layout["slots"] if s}
        candidate = f"{base_name} copy"
        suffix = 2
        while candidate in existing_names:
            candidate = f"{base_name} copy {suffix}"
            suffix += 1

        # Clone worker config, reset runtime state
        clone = {
            "row": target // cols,
            "col": target % cols,
            "profile": source.get("profile"),
            "name": candidate,
            "agent": source.get("agent", "claude"),
            "model": source.get("model", "claude-sonnet-4-6"),
            "activation": source.get("activation", "on_drop"),
            "disposition": source.get("disposition", "review"),
            "watch_column": source.get("watch_column"),
            "expertise_prompt": source.get("expertise_prompt", ""),
            "max_retries": source.get("max_retries", 1),
            "use_worktree": source.get("use_worktree", False),
            "auto_commit": source.get("auto_commit", False),
            "auto_pr": source.get("auto_pr", False),
            "trigger_time": source.get("trigger_time"),
            "trigger_interval_minutes": source.get("trigger_interval_minutes"),
            "trigger_every_day": source.get("trigger_every_day", False),
            "last_trigger_time": None,
            "paused": False,
            "task_queue": [],
            "state": "idle",
        }

        layout["slots"][target] = clone
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:configure")
    @with_lock
    def on_worker_configure(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        slot_index, fields = validate_worker_configure(data, max_slots=200)

        if slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:configure requires valid slot"})
            return

        worker = layout["slots"][slot_index]
        if not worker:
            emit("error", {"message": "No worker in slot"})
            return

        for k, v in fields.items():
            if k not in ("task_queue", "state"):
                worker[k] = v

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

        # If activation or watch_column changed, check for unclaimed tasks
        if ("activation" in fields or "watch_column" in fields):
            if (worker.get("activation") == "on_queue"
                    and worker.get("watch_column")
                    and worker.get("state") == "idle"
                    and not worker.get("paused")):
                worker_mod.check_watch_columns(
                    bp_dir, worker["watch_column"], socketio, ws_id,
                )

    @socketio.on("layout:update")
    @with_lock
    def on_layout_update(data):
        ws_id, bp_dir = _resolve(data)
        grid = validate_layout_update(data)
        config = read_json(os.path.join(bp_dir, "config.json"))

        if grid is not None:
            config["grid"] = grid
            write_json(os.path.join(bp_dir, "config.json"), config)

        _emit("config:updated", config, ws_id)

    @socketio.on("config:update")
    @with_lock
    def on_config_update(data):
        ws_id, bp_dir = _resolve(data)
        sanitized = validate_config_update(data)
        config = read_json(os.path.join(bp_dir, "config.json"))

        for k, v in sanitized.items():
            config[k] = v

        write_json(os.path.join(bp_dir, "config.json"), config)
        _emit("config:updated", config, ws_id)

    @socketio.on("prompt:update")
    @with_lock
    def on_prompt_update(data):
        ws_id, bp_dir = _resolve(data)
        prompt_type = data.get("type")  # "workspace" or "bullpen"
        content = data.get("content", "")

        if prompt_type not in ("workspace", "bullpen"):
            emit("error", {"message": "prompt:update requires type 'workspace' or 'bullpen'"})
            return

        path = os.path.join(bp_dir, f"{prompt_type}_prompt.md")
        atomic_write(path, content)
        _emit("prompt:updated", {"type": prompt_type, "content": content}, ws_id)

    @socketio.on("profile:create")
    @with_lock
    def on_profile_create(data):
        ws_id, bp_dir = _resolve(data)
        profile = create_profile(bp_dir, data)
        profiles = list_profiles(bp_dir)
        _emit("profiles:updated", profiles, ws_id)

    # --- Team events ---

    @socketio.on("team:save")
    @with_lock
    def on_team_save(data):
        ws_id, bp_dir = _resolve(data)
        name = validate_team_name(data.get("name"))
        layout = _load_layout(bp_dir)
        save_team(bp_dir, name, layout)
        teams = list_teams(bp_dir)
        _emit("teams:updated", teams, ws_id)

    @socketio.on("team:load")
    @with_lock
    def on_team_load(data):
        ws_id, bp_dir = _resolve(data)
        name = validate_team_name(data.get("name"))
        team_layout = load_team(bp_dir, name)
        if not team_layout:
            emit("error", {"message": f"Team not found: {name}"})
            return
        _save_layout(bp_dir, team_layout)
        _emit("layout:updated", team_layout, ws_id)

    # --- Execution events ---

    @socketio.on("task:assign")
    @with_lock
    def on_task_assign(data):
        ws_id, bp_dir = _resolve(data)
        task_id = data.get("task_id")
        slot = data.get("slot")
        if task_id is None or slot is None:
            emit("error", {"message": "task:assign requires task_id and slot"})
            return
        worker_mod.assign_task(bp_dir, slot, task_id, socketio, ws_id)

    @socketio.on("worker:start")
    @with_lock
    def on_worker_start(data):
        ws_id, bp_dir = _resolve(data)
        slot = data.get("slot")
        if slot is None:
            emit("error", {"message": "worker:start requires slot"})
            return
        worker_mod.start_worker(bp_dir, slot, socketio, ws_id)

    @socketio.on("worker:stop")
    @with_lock
    def on_worker_stop(data):
        ws_id, bp_dir = _resolve(data)
        slot = data.get("slot")
        if slot is None:
            emit("error", {"message": "worker:stop requires slot"})
            return
        worker_mod.stop_worker(bp_dir, slot, socketio, ws_id)

    # --- Output streaming events ---

    @socketio.on("worker:output:request")
    def on_worker_output_request(data):
        ws_id, bp_dir = _resolve(data)
        slot = data.get("slot")
        entry = worker_mod.get_output_buffer(ws_id, slot)
        if entry:
            emit("worker:output:catchup", {
                "slot": slot,
                "lines": list(entry["buffer"]),
                "workspaceId": ws_id,
            })

    # --- Project events ---

    @socketio.on("project:add")
    @with_lock
    def on_project_add(data):
        manager = app.config["manager"]
        path = data.get("path", "").strip()
        if not path:
            emit("error", {"message": "project:add requires path"})
            return
        try:
            ws_id = manager.register_project(path)
        except ValueError as e:
            emit("error", {"message": str(e)})
            return

        ws = manager.get(ws_id)

        # Start scheduler for new workspace
        from server.scheduler import Scheduler
        if not ws.scheduler:
            scheduler = Scheduler(ws.bp_dir, socketio, ws_id=ws_id)
            scheduler.start()
            ws.scheduler = scheduler

        # Reconcile new workspace
        from server.app import reconcile, load_state
        reconcile(ws.bp_dir)

        # Send state for the new workspace to all clients
        state = load_state(ws.bp_dir, ws.path)
        state["workspaceId"] = ws_id
        socketio.emit("state:init", state)

        # Broadcast updated project list
        socketio.emit("projects:updated", manager.list_projects())

    @socketio.on("project:remove")
    @with_lock
    def on_project_remove(data):
        manager = app.config["manager"]
        ws_id = data.get("workspaceId")
        if not ws_id:
            emit("error", {"message": "project:remove requires workspaceId"})
            return

        # Don't allow removing the startup workspace
        if ws_id == app.config["startup_workspace_id"]:
            emit("error", {"message": "Cannot remove the startup project"})
            return

        manager.remove_project(ws_id)
        socketio.emit("project:removed", {"workspaceId": ws_id})
        socketio.emit("projects:updated", manager.list_projects())

    @socketio.on("project:list")
    def on_project_list(data=None):
        manager = app.config["manager"]
        emit("projects:updated", manager.list_projects())

    # --- Chat events ---

    # In-memory chat sessions: sessionId -> list of {role, content}
    _chat_sessions = {}
    _chat_lock = threading.Lock()

    def _run_chat(session_id, message, argv, adapter, response_collector, workspace=None):
        """Run chat agent subprocess, emit streaming lines, then emit done."""
        collected = []
        # Extract temp MCP config path for cleanup (written by adapter.build_argv)
        mcp_config_path = None
        for i, arg in enumerate(argv):
            if arg == "--mcp-config" and i + 1 < len(argv):
                mcp_config_path = argv[i + 1]
                break
        try:
            popen_kwargs = dict(
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            if workspace:
                popen_kwargs["cwd"] = workspace
            proc = subprocess.Popen(argv, **popen_kwargs)
            prompt = response_collector["prompt"]
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

            batch = []
            batch_lock = threading.Lock()
            import time
            last_emit = [time.time()]

            def _drain_stdout():
                for line in proc.stdout:
                    display = adapter.format_stream_line(line)
                    if display is None:
                        continue
                    for dl in display.split("\n"):
                        collected.append(dl)
                        to_emit = None
                        with batch_lock:
                            batch.append(dl)
                            now = time.time()
                            if now - last_emit[0] >= 0.2:
                                to_emit = list(batch)
                                batch.clear()
                                last_emit[0] = now
                        if to_emit:
                            socketio.emit("chat:output", {"sessionId": session_id, "lines": to_emit})

            def _drain_stderr():
                try:
                    for line in proc.stderr:
                        line = line.rstrip()
                        if line:
                            logging.warning("chat agent stderr [%s]: %s", session_id, line)
                except Exception:
                    pass

            t_err = threading.Thread(target=_drain_stderr, daemon=True)
            t_err.start()
            _drain_stdout()
            proc.wait()
            t_err.join(timeout=2)

            # Flush remaining batch
            with batch_lock:
                if batch:
                    socketio.emit("chat:output", {"sessionId": session_id, "lines": list(batch)})
                    batch.clear()

            full_response = "\n".join(collected).strip()

            # Update session history
            with _chat_lock:
                if session_id in _chat_sessions:
                    _chat_sessions[session_id].append({"role": "user", "content": message})
                    _chat_sessions[session_id].append({"role": "assistant", "content": full_response})

            socketio.emit("chat:done", {"sessionId": session_id})

        except Exception as e:
            logging.exception("Chat agent error for session %s", session_id)
            socketio.emit("chat:error", {"sessionId": session_id, "message": str(e)})
        finally:
            if mcp_config_path:
                try:
                    os.unlink(mcp_config_path)
                except OSError:
                    pass

    @socketio.on("chat:send")
    def on_chat_send(data):
        from server.agents import get_adapter as _get_adapter
        session_id = data.get("sessionId", "")
        provider = data.get("provider", "claude")
        model = data.get("model", "claude-sonnet-4-6")
        message = (data.get("message") or "").strip()
        ws_id, bp_dir = _resolve(data)

        if not session_id or not message:
            emit("chat:error", {"sessionId": session_id, "message": "sessionId and message are required"})
            return
        if len(message) > 100_000:
            emit("chat:error", {"sessionId": session_id, "message": "Message too long"})
            return

        adapter = _get_adapter(provider)
        if not adapter:
            emit("chat:error", {"sessionId": session_id, "message": f"Unknown provider: {provider}"})
            return

        # Build prompt with conversation history
        with _chat_lock:
            if session_id not in _chat_sessions:
                _chat_sessions[session_id] = []
            history = list(_chat_sessions[session_id])

        parts = [
            "You are a Bullpen project assistant. You have MCP tools for managing tickets:",
            "- list_tickets: List tickets, optionally filtered by status.",
            "- create_ticket: Create a new ticket.",
            "- update_ticket: Update an existing ticket's fields.",
            "",
            "IMPORTANT: Always use these MCP tools for ticket operations. Do NOT read "
            ".bullpen/tasks/ files directly — those are internal storage. The MCP tools "
            "ensure the UI updates in real time.",
            "",
        ]
        if history:
            parts.append("Conversation history:")
            parts.append("")
            for turn in history:
                role = "Human" if turn["role"] == "user" else "Assistant"
                parts.append(f"{role}: {turn['content']}")
            parts.append("")
        parts.append(f"Human: {message}")
        full_prompt = "\n".join(parts)

        workspace = os.path.dirname(bp_dir)
        argv = adapter.build_argv(full_prompt, model, workspace, bp_dir=bp_dir)

        response_collector = {"prompt": full_prompt}
        thread = threading.Thread(
            target=_run_chat,
            args=(session_id, message, argv, adapter, response_collector),
            kwargs={"workspace": workspace},
            daemon=True,
        )
        thread.start()

    @socketio.on("chat:clear")
    def on_chat_clear(data):
        session_id = data.get("sessionId", "")
        with _chat_lock:
            _chat_sessions.pop(session_id, None)
        emit("chat:cleared", {"sessionId": session_id})
