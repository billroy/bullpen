"""Socket event handlers."""

import os
import threading

from flask import request
from flask_socketio import emit

from server import tasks as task_mod
from server.persistence import read_json, write_json, atomic_write
from server.profiles import create_profile, list_profiles
from server.teams import save_team, load_team, list_teams
from server import workers as worker_mod


# Single-writer queue to serialize mutations
_write_lock = threading.Lock()


def _load_layout(bp_dir):
    return read_json(os.path.join(bp_dir, "layout.json"))


def _save_layout(bp_dir, layout):
    write_json(os.path.join(bp_dir, "layout.json"), layout)


def register_events(socketio, app):
    """Register all socket.io event handlers."""

    def with_lock(fn):
        """Execute fn under write lock, emit error on failure."""
        def wrapper(data):
            with _write_lock:
                try:
                    return fn(data)
                except Exception as e:
                    emit("error", {"message": str(e)})
        wrapper.__name__ = fn.__name__
        return wrapper

    # --- Task events ---

    @socketio.on("task:create")
    @with_lock
    def on_task_create(data):
        bp_dir = app.config["bp_dir"]
        task = task_mod.create_task(
            bp_dir,
            title=data.get("title", "Untitled"),
            description=data.get("description", ""),
            task_type=data.get("type", "task"),
            priority=data.get("priority", "normal"),
            tags=data.get("tags", []),
        )
        socketio.emit("task:created", task)

    @socketio.on("task:update")
    @with_lock
    def on_task_update(data):
        bp_dir = app.config["bp_dir"]
        task_id = data.get("id")
        if not task_id:
            emit("error", {"message": "task:update requires id"})
            return
        fields = {k: v for k, v in data.items() if k != "id"}
        task = task_mod.update_task(bp_dir, task_id, fields)
        socketio.emit("task:updated", task)

    @socketio.on("task:delete")
    @with_lock
    def on_task_delete(data):
        bp_dir = app.config["bp_dir"]
        task_id = data.get("id")
        if not task_id:
            emit("error", {"message": "task:delete requires id"})
            return
        task_mod.delete_task(bp_dir, task_id)
        socketio.emit("task:deleted", {"id": task_id})

    @socketio.on("task:clear_output")
    @with_lock
    def on_task_clear_output(data):
        bp_dir = app.config["bp_dir"]
        task_id = data.get("id")
        if not task_id:
            emit("error", {"message": "task:clear_output requires id"})
            return
        task = task_mod.clear_task_output(bp_dir, task_id)
        socketio.emit("task:updated", task)

    # --- Worker / Layout events ---

    @socketio.on("worker:add")
    @with_lock
    def on_worker_add(data):
        bp_dir = app.config["bp_dir"]
        layout = _load_layout(bp_dir)
        slot_index = data.get("slot")
        profile_id = data.get("profile")

        if slot_index is None or profile_id is None:
            emit("error", {"message": "worker:add requires slot and profile"})
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

        worker = {
            "row": row,
            "col": col,
            "profile": profile_id,
            "name": profile["name"],
            "agent": profile.get("default_agent", "claude"),
            "model": profile.get("default_model", "sonnet"),
            "activation": "on_drop",
            "disposition": "review",
            "watch_column": None,
            "expertise_prompt": profile.get("expertise_prompt", ""),
            "max_retries": 1,
            "task_queue": [],
            "state": "idle",
        }

        # Ensure slots list is large enough
        while len(layout["slots"]) <= slot_index:
            layout["slots"].append(None)

        layout["slots"][slot_index] = worker
        _save_layout(bp_dir, layout)
        socketio.emit("layout:updated", layout)

    @socketio.on("worker:remove")
    @with_lock
    def on_worker_remove(data):
        bp_dir = app.config["bp_dir"]
        layout = _load_layout(bp_dir)
        slot_index = data.get("slot")

        if slot_index is None or slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:remove requires valid slot"})
            return

        layout["slots"][slot_index] = None
        _save_layout(bp_dir, layout)
        socketio.emit("layout:updated", layout)

    @socketio.on("worker:move")
    @with_lock
    def on_worker_move(data):
        bp_dir = app.config["bp_dir"]
        layout = _load_layout(bp_dir)
        from_slot = data.get("from")
        to_slot = data.get("to")

        if from_slot is None or to_slot is None:
            emit("error", {"message": "worker:move requires from and to"})
            return

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
        socketio.emit("layout:updated", layout)

    @socketio.on("worker:configure")
    @with_lock
    def on_worker_configure(data):
        bp_dir = app.config["bp_dir"]
        layout = _load_layout(bp_dir)
        slot_index = data.get("slot")

        if slot_index is None or slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:configure requires valid slot"})
            return

        worker = layout["slots"][slot_index]
        if not worker:
            emit("error", {"message": "No worker in slot"})
            return

        fields = data.get("fields", {})
        for k, v in fields.items():
            if k not in ("task_queue", "state"):  # don't allow overwriting runtime state
                worker[k] = v

        _save_layout(bp_dir, layout)
        socketio.emit("layout:updated", layout)

    @socketio.on("layout:update")
    @with_lock
    def on_layout_update(data):
        bp_dir = app.config["bp_dir"]
        config = read_json(os.path.join(bp_dir, "config.json"))

        if "grid" in data:
            config["grid"] = data["grid"]
            write_json(os.path.join(bp_dir, "config.json"), config)

        socketio.emit("config:updated", config)

    @socketio.on("config:update")
    @with_lock
    def on_config_update(data):
        bp_dir = app.config["bp_dir"]
        config = read_json(os.path.join(bp_dir, "config.json"))

        for k, v in data.items():
            config[k] = v

        write_json(os.path.join(bp_dir, "config.json"), config)
        socketio.emit("config:updated", config)

    @socketio.on("prompt:update")
    @with_lock
    def on_prompt_update(data):
        bp_dir = app.config["bp_dir"]
        prompt_type = data.get("type")  # "workspace" or "bullpen"
        content = data.get("content", "")

        if prompt_type not in ("workspace", "bullpen"):
            emit("error", {"message": "prompt:update requires type 'workspace' or 'bullpen'"})
            return

        path = os.path.join(bp_dir, f"{prompt_type}_prompt.md")
        atomic_write(path, content)
        socketio.emit("prompt:updated", {"type": prompt_type, "content": content})

    @socketio.on("profile:create")
    @with_lock
    def on_profile_create(data):
        bp_dir = app.config["bp_dir"]
        profile = create_profile(bp_dir, data)
        profiles = list_profiles(bp_dir)
        socketio.emit("profiles:updated", profiles)

    # --- Team events ---

    @socketio.on("team:save")
    @with_lock
    def on_team_save(data):
        bp_dir = app.config["bp_dir"]
        name = data.get("name")
        if not name:
            emit("error", {"message": "team:save requires name"})
            return
        layout = _load_layout(bp_dir)
        save_team(bp_dir, name, layout)
        teams = list_teams(bp_dir)
        socketio.emit("teams:updated", teams)

    @socketio.on("team:load")
    @with_lock
    def on_team_load(data):
        bp_dir = app.config["bp_dir"]
        name = data.get("name")
        if not name:
            emit("error", {"message": "team:load requires name"})
            return
        team_layout = load_team(bp_dir, name)
        if not team_layout:
            emit("error", {"message": f"Team not found: {name}"})
            return
        _save_layout(bp_dir, team_layout)
        socketio.emit("layout:updated", team_layout)

    # --- Execution events ---

    @socketio.on("task:assign")
    @with_lock
    def on_task_assign(data):
        bp_dir = app.config["bp_dir"]
        task_id = data.get("task_id")
        slot = data.get("slot")
        if task_id is None or slot is None:
            emit("error", {"message": "task:assign requires task_id and slot"})
            return
        worker_mod.assign_task(bp_dir, slot, task_id, socketio)

    @socketio.on("worker:start")
    @with_lock
    def on_worker_start(data):
        bp_dir = app.config["bp_dir"]
        slot = data.get("slot")
        if slot is None:
            emit("error", {"message": "worker:start requires slot"})
            return
        worker_mod.start_worker(bp_dir, slot, socketio)

    @socketio.on("worker:stop")
    @with_lock
    def on_worker_stop(data):
        bp_dir = app.config["bp_dir"]
        slot = data.get("slot")
        if slot is None:
            emit("error", {"message": "worker:stop requires slot"})
            return
        worker_mod.stop_worker(bp_dir, slot, socketio)
