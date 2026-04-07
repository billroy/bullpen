"""Tests for server/events.py — socket event handlers."""

import os
import tempfile

import pytest

from server.app import create_app, socketio


@pytest.fixture
def client():
    """Create a Flask-SocketIO test client."""
    with tempfile.TemporaryDirectory(prefix="bullpen_test_") as ws:
        app = create_app(ws, no_browser=True)
        client = socketio.test_client(app)
        # Drain the state:init event
        client.get_received()
        yield client, app
        client.disconnect()


def get_event(client, name):
    """Find the first event with given name from received events."""
    for evt in client.get_received():
        if evt["name"] == name:
            return evt["args"][0]
    return None


def get_all_events(client, name):
    """Get all events with given name."""
    return [evt["args"][0] for evt in client.get_received() if evt["name"] == name]


class TestTaskEvents:
    def test_create_task(self, client):
        c, app = client
        c.emit("task:create", {"title": "Test Task", "type": "bug", "priority": "high"})
        task = get_event(c, "task:created")
        assert task is not None
        assert task["title"] == "Test Task"
        assert task["type"] == "bug"
        assert task["priority"] == "high"
        assert task["status"] == "inbox"
        assert task["id"]

        # Verify file was written
        path = os.path.join(app.config["bp_dir"], "tasks", f"{task['id']}.md")
        assert os.path.exists(path)

    def test_update_task(self, client):
        c, app = client
        c.emit("task:create", {"title": "Update Me"})
        task = get_event(c, "task:created")

        c.emit("task:update", {"id": task["id"], "status": "assigned", "priority": "urgent"})
        updated = get_event(c, "task:updated")
        assert updated is not None
        assert updated["status"] == "assigned"
        assert updated["priority"] == "urgent"
        assert updated["title"] == "Update Me"

    def test_delete_task(self, client):
        c, app = client
        c.emit("task:create", {"title": "Delete Me"})
        task = get_event(c, "task:created")

        c.emit("task:delete", {"id": task["id"]})
        deleted = get_event(c, "task:deleted")
        assert deleted is not None
        assert deleted["id"] == task["id"]

        # Verify file removed
        path = os.path.join(app.config["bp_dir"], "tasks", f"{task['id']}.md")
        assert not os.path.exists(path)

    def test_clear_output(self, client):
        c, app = client
        c.emit("task:create", {"title": "Clear Output", "description": "Keep this"})
        task = get_event(c, "task:created")

        # Add some agent output
        body_with_output = task["body"] + "\n## Agent Output\n\nSome output.\n"
        c.emit("task:update", {"id": task["id"], "body": body_with_output})
        c.get_received()  # drain

        c.emit("task:clear_output", {"id": task["id"]})
        cleared = get_event(c, "task:updated")
        assert cleared is not None
        assert "## Agent Output" not in cleared["body"]
        assert "Keep this" in cleared["body"]

    def test_create_with_tags(self, client):
        c, _ = client
        c.emit("task:create", {"title": "Tagged", "tags": ["backend", "api"]})
        task = get_event(c, "task:created")
        assert task["tags"] == ["backend", "api"]

    def test_update_missing_id(self, client):
        c, _ = client
        c.emit("task:update", {"status": "done"})
        err = get_event(c, "error")
        assert err is not None
        assert "requires id" in err["message"]

    def test_delete_missing_id(self, client):
        c, _ = client
        c.emit("task:delete", {})
        err = get_event(c, "error")
        assert err is not None

    def test_full_lifecycle(self, client):
        """Create → update → delete lifecycle."""
        c, app = client
        # Create
        c.emit("task:create", {"title": "Lifecycle Task"})
        task = get_event(c, "task:created")
        task_id = task["id"]

        # Update
        c.emit("task:update", {"id": task_id, "status": "in_progress"})
        updated = get_event(c, "task:updated")
        assert updated["status"] == "in_progress"

        # Delete
        c.emit("task:delete", {"id": task_id})
        deleted = get_event(c, "task:deleted")
        assert deleted["id"] == task_id

        # Verify gone from disk
        path = os.path.join(app.config["bp_dir"], "tasks", f"{task_id}.md")
        assert not os.path.exists(path)
