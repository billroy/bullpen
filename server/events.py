"""Socket event handlers."""

import threading

from flask import request
from flask_socketio import emit

from server import tasks as task_mod


# Single-writer queue to serialize mutations
_write_lock = threading.Lock()


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
