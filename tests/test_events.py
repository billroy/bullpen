"""Tests for server/events.py — socket event handlers."""

import os
import tempfile
import time

import pytest

from server.agents import register_adapter
from server.agents.base import AgentAdapter
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


class ChatUsageAdapter(AgentAdapter):
    @property
    def name(self):
        return "chat-usage-mock"

    def available(self):
        return True

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        import sys
        script = (
            "import json; "
            "print(json.dumps({'type':'result','is_error':False,'result':'ok',"
            "'usage':{'input_tokens':11,'output_tokens':7,'cached_input_tokens':3}}))"
        )
        return [sys.executable, "-c", script]

    def parse_output(self, stdout, stderr, exit_code):
        return {"success": True, "output": stdout.strip(), "error": None, "usage": {}}

    def format_stream_line(self, line):
        return None


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

    def test_archive_task(self, client):
        c, app = client
        c.emit("task:create", {"title": "Archive Me"})
        task = get_event(c, "task:created")

        c.emit("task:archive", {"id": task["id"]})
        deleted = get_event(c, "task:deleted")
        assert deleted is not None
        assert deleted["id"] == task["id"]

        # Verify moved to archive
        src = os.path.join(app.config["bp_dir"], "tasks", f"{task['id']}.md")
        dst = os.path.join(app.config["bp_dir"], "tasks", "archive", f"{task['id']}.md")
        assert not os.path.exists(src)
        assert os.path.exists(dst)

    def test_archive_done_tasks(self, client):
        c, app = client
        # Create a done task and an active task
        c.emit("task:create", {"title": "Done Task"})
        t1 = get_event(c, "task:created")
        c.emit("task:update", {"id": t1["id"], "status": "done"})
        c.get_received()

        c.emit("task:create", {"title": "Active Task"})
        t2 = get_event(c, "task:created")

        c.emit("task:archive-done", {})
        events = get_all_events(c, "task:deleted")
        archived_ids = {e["id"] for e in events}
        assert t1["id"] in archived_ids
        assert t2["id"] not in archived_ids

        # Active task still on disk
        active_path = os.path.join(app.config["bp_dir"], "tasks", f"{t2['id']}.md")
        assert os.path.exists(active_path)


class TestWorkerEvents:
    def test_add_worker(self, client):
        c, app = client
        c.emit("worker:add", {"slot": 0, "profile": "feature-architect"})
        layout = get_event(c, "layout:updated")
        assert layout is not None
        assert layout["slots"][0] is not None
        assert layout["slots"][0]["profile"] == "feature-architect"
        assert layout["slots"][0]["name"] == "Feature Architect"
        assert layout["slots"][0]["state"] == "idle"

    def test_add_worker_persists(self, client):
        c, app = client
        c.emit("worker:add", {"slot": 2, "profile": "code-reviewer"})
        c.get_received()

        # Verify layout.json updated
        from server.persistence import read_json
        layout = read_json(os.path.join(app.config["bp_dir"], "layout.json"))
        assert layout["slots"][2]["profile"] == "code-reviewer"

    def test_remove_worker(self, client):
        c, _ = client
        c.emit("worker:add", {"slot": 0, "profile": "feature-architect"})
        c.get_received()

        c.emit("worker:remove", {"slot": 0})
        layout = get_event(c, "layout:updated")
        assert layout["slots"][0] is None

    def test_move_worker(self, client):
        c, _ = client
        c.emit("worker:add", {"slot": 0, "profile": "feature-architect"})
        c.get_received()

        c.emit("worker:move", {"from": 0, "to": 3})
        layout = get_event(c, "layout:updated")
        assert layout["slots"][0] is None
        assert layout["slots"][3] is not None
        assert layout["slots"][3]["profile"] == "feature-architect"

    def test_configure_worker(self, client):
        c, _ = client
        c.emit("worker:add", {"slot": 0, "profile": "feature-architect"})
        c.get_received()

        c.emit("worker:configure", {"slot": 0, "fields": {
            "activation": "on_queue",
            "watch_column": "inbox",
            "max_retries": 3,
        }})
        layout = get_event(c, "layout:updated")
        worker = layout["slots"][0]
        assert worker["activation"] == "on_queue"
        assert worker["watch_column"] == "inbox"
        assert worker["max_retries"] == 3

    def test_configure_at_time_activation(self, client):
        c, app = client
        # Add a worker first
        c.emit("profile:create", {
            "id": "timer-test", "name": "Timer Test",
            "default_agent": "claude", "default_model": "sonnet",
            "color_hint": "blue", "expertise_prompt": "Timer test.",
        })
        c.get_received()
        c.emit("worker:add", {"slot": 0, "profile": "timer-test"})
        c.get_received()

        c.emit("worker:configure", {"slot": 0, "fields": {
            "activation": "at_time",
            "trigger_time": "09:30",
            "trigger_every_day": True,
        }})
        layout = get_event(c, "layout:updated")
        worker = layout["slots"][0]
        assert worker["activation"] == "at_time"
        assert worker["trigger_time"] == "09:30"
        assert worker["trigger_every_day"] is True

    def test_configure_on_interval_activation(self, client):
        c, app = client
        c.emit("profile:create", {
            "id": "interval-test", "name": "Interval Test",
            "default_agent": "claude", "default_model": "sonnet",
            "color_hint": "blue", "expertise_prompt": "Interval test.",
        })
        c.get_received()
        c.emit("worker:add", {"slot": 0, "profile": "interval-test"})
        c.get_received()

        c.emit("worker:configure", {"slot": 0, "fields": {
            "activation": "on_interval",
            "trigger_interval_minutes": 30,
        }})
        layout = get_event(c, "layout:updated")
        worker = layout["slots"][0]
        assert worker["activation"] == "on_interval"
        assert worker["trigger_interval_minutes"] == 30

    def test_add_worker_invalid_profile(self, client):
        c, _ = client
        c.emit("worker:add", {"slot": 0, "profile": "nonexistent"})
        err = get_event(c, "error")
        assert err is not None
        assert "not found" in err["message"]

    def test_configure_worker_disposition(self, client):
        """Worker disposition can be set to a worker: target."""
        c, _ = client
        c.emit("worker:add", {"slot": 0, "profile": "feature-architect"})
        c.get_received()

        c.emit("worker:configure", {"slot": 0, "fields": {
            "disposition": "worker:Code Reviewer",
        }})
        layout = get_event(c, "layout:updated")
        assert layout["slots"][0]["disposition"] == "worker:Code Reviewer"

    def test_configure_worker_normalizes_legacy_claude_haiku_model(self, client):
        c, _ = client
        c.emit("worker:add", {"slot": 0, "profile": "feature-architect"})
        c.get_received()

        c.emit("worker:configure", {"slot": 0, "fields": {
            "model": "claude-haiku-4-6",
        }})
        layout = get_event(c, "layout:updated")
        assert layout["slots"][0]["model"] == "claude-haiku-4-5-20251001"


class TestChatEvents:
    def test_chat_logs_structured_usage_and_tokens(self, client):
        c, app = client
        register_adapter("chat-usage-mock", ChatUsageAdapter())

        c.emit("chat:send", {
            "sessionId": "session-usage-1",
            "provider": "chat-usage-mock",
            "model": "mock-model",
            "message": "hello",
        })

        deadline = time.time() + 3.0
        done = False
        while time.time() < deadline and not done:
            for evt in c.get_received():
                if evt["name"] == "chat:done":
                    done = True
                    break
            if not done:
                time.sleep(0.05)

        assert done, "chat:done not received"

        from server.tasks import list_tasks

        tasks = list_tasks(app.config["bp_dir"])
        chat_tasks = [t for t in tasks if "chat" in (t.get("tags") or [])]
        assert chat_tasks
        task = chat_tasks[0]
        assert task.get("tokens") == 18
        assert isinstance(task.get("usage"), list)
        assert len(task["usage"]) == 1
        usage = task["usage"][0]
        assert usage["source"] == "chat"
        assert usage["provider"] == "chat-usage-mock"
        assert usage["model"] == "mock-model"
        assert usage["input_tokens"] == 11
        assert usage["output_tokens"] == 7
        assert usage["cached_input_tokens"] == 3
        assert isinstance(task.get("tokens_by_provider_model"), list)
        assert len(task["tokens_by_provider_model"]) == 1
        breakdown = task["tokens_by_provider_model"][0]
        assert breakdown["provider"] == "chat-usage-mock"
        assert breakdown["model"] == "mock-model"
        assert breakdown["input_tokens"] == 11
        assert breakdown["output_tokens"] == 7
        assert breakdown["cached_input_tokens"] == 3
        assert breakdown["tokens"] == 18


class TestConfigEvents:
    def test_config_update(self, client):
        c, app = client
        c.emit("config:update", {"name": "My Team", "theme": "nord"})
        config = get_event(c, "config:updated")
        assert config is not None
        assert config["name"] == "My Team"
        assert config["theme"] == "nord"

    def test_prompt_update(self, client):
        c, app = client
        c.emit("prompt:update", {"type": "workspace", "content": "This is a Flask project."})
        result = get_event(c, "prompt:updated")
        assert result is not None
        assert result["type"] == "workspace"
        assert result["content"] == "This is a Flask project."

        # Verify file
        path = os.path.join(app.config["bp_dir"], "workspace_prompt.md")
        assert open(path).read() == "This is a Flask project."

    def test_profile_create(self, client):
        c, _ = client
        c.emit("profile:create", {
            "id": "custom",
            "name": "Custom",
            "default_agent": "claude",
            "default_model": "sonnet",
            "color_hint": "pink",
            "expertise_prompt": "Custom worker.",
        })
        profiles = get_event(c, "profiles:updated")
        assert profiles is not None
        ids = {p["id"] for p in profiles}
        assert "custom" in ids
