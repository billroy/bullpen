"""Closed-loop tests for Notification worker config and activation."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from server.app import create_app, socketio


ROOT = Path(__file__).resolve().parents[1]


def _node_modal_payload():
    result = subprocess.run(
        ["node", str(ROOT / "tests/js/notification_modal_closed_loop.js")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _event_payloads(client, name):
    return [
        evt["args"][0]
        for evt in client.get_received()
        if evt["name"] == name
    ]


def _wait_for_task_status(bp_dir, task_id, status, timeout=3.0):
    from server.tasks import read_task

    deadline = time.time() + timeout
    task = None
    while time.time() < deadline:
        task = read_task(bp_dir, task_id)
        if task and task.get("status") == status:
            return task
        time.sleep(0.05)
    return task


def _wait_for_synthetic_task(bp_dir, worker_name, status, timeout=3.0):
    from server.tasks import list_tasks

    prefix = f"[Auto] {worker_name} - manual - "
    deadline = time.time() + timeout
    matches = []
    while time.time() < deadline:
        matches = [
            task for task in list_tasks(bp_dir)
            if task.get("synthetic_run") is True
            and task.get("trigger_kind") == "manual"
            and str(task.get("title", "")).startswith(prefix)
        ]
        if matches and matches[-1].get("status") == status:
            return matches[-1]
        time.sleep(0.05)
    return matches[-1] if matches else None


def _make_client():
    tmp = tempfile.TemporaryDirectory(prefix="bullpen_notify_closed_loop_")
    app = create_app(tmp.name, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()
    return tmp, app, client


def test_notification_dialog_controls_round_trip_through_worker_configure():
    tmp, _app, client = _make_client()
    try:
        client.emit("worker:add", {
            "slot": 0,
            "type": "notification",
            "fields": {"name": "Notification worker"},
        })
        assert _event_payloads(client, "layout:updated")

        payload = _node_modal_payload()
        client.emit("worker:configure", payload)
        layouts = _event_payloads(client, "layout:updated")
        assert layouts
        worker = layouts[-1]["slots"][0]

        assert worker["type"] == "notification"
        assert worker["name"] == "Escalation Bell"
        assert worker["activation"] == "on_interval"
        assert worker["watch_column"] == "review"
        assert worker["trigger_time"] == "09:30"
        assert worker["trigger_every_day"] is True
        assert worker["trigger_interval_minutes"] == 15
        assert worker["disposition"] == "random:qa-router"
        assert worker["paused"] is False
        assert worker["color"] == "#123456"
        assert worker["max_retries"] == 0

        notification = worker["notification"]
        assert notification["toast"] == {
            "enabled": False,
            "template": "{ticket.title} toast {worker.name} {workspace.name}",
            "variant": "warning",
            "duration_ms": 12345,
        }
        assert notification["speech"] == {
            "enabled": True,
            "template": "Speak {ticket.priority} {ticket.title}",
            "engine": "web-speech",
            "voice": "Samantha",
            "rate": 1.4,
            "volume": 0.6,
        }
        assert notification["sound"] == {
            "enabled": True,
            "effect": "warning",
            "repeat_count": 4,
            "gap_ms": 750,
            "volume": 0.7,
        }
        assert notification["flash"] == {
            "enabled": True,
            "sequence": [{"color": "#00ff88", "duration_ms": 220}],
            "opacity": 0.45,
        }
        assert notification["policy"] == {
            "cooldown_ms": 2500,
            "dedupe_window_ms": 9000,
        }

        forbidden = {
            "agent", "model", "expertise_prompt", "trust_mode", "command",
            "env", "command_source", "procfile_process", "health_type",
        }
        assert forbidden.isdisjoint(worker.keys())
    finally:
        client.disconnect()
        tmp.cleanup()


def test_notification_worker_manual_start_fires_notification_and_routes_ticket():
    tmp, app, client = _make_client()
    try:
        notification = _node_modal_payload()["fields"]["notification"]
        client.emit("worker:add", {
            "slot": 0,
            "type": "notification",
            "fields": {
                "name": "Manual Notify",
                "activation": "manual",
                "disposition": "review",
                "notification": notification,
            },
        })
        assert _event_payloads(client, "layout:updated")

        client.emit("task:create", {"title": "Manual notification ticket", "priority": "urgent"})
        created = _event_payloads(client, "task:created")[-1]
        client.emit("task:assign", {"task_id": created["id"], "slot": 0})
        client.get_received()

        client.emit("worker:start", {"slot": 0})
        updated = _wait_for_task_status(app.config["bp_dir"], created["id"], "review")
        notification_events = _event_payloads(client, "notification:fire")

        assert updated["assigned_to"] == ""
        assert notification_events
        fired = notification_events[-1]
        assert fired["worker"]["name"] == "Manual Notify"
        assert fired["ticket"]["title"] == "Manual notification ticket"
        assert fired["channels"]["toast"]["enabled"] is False
        assert fired["channels"]["toast"]["variant"] == "warning"
        assert fired["channels"]["speech"]["enabled"] is True
        assert fired["channels"]["speech"]["text"] == "Speak urgent Manual notification ticket"
        assert fired["channels"]["sound"]["effect"] == "warning"
        assert fired["channels"]["flash"]["sequence"] == [{"color": "#00ff88", "duration_ms": 220}]
        assert fired["policy"]["cooldown_ms"] == 2500

        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == []
        assert final_layout["slots"][0]["state"] == "idle"
    finally:
        client.disconnect()
        tmp.cleanup()


def test_notification_worker_manual_start_empty_queue_creates_synthetic_ticket():
    tmp, app, client = _make_client()
    try:
        notification = _node_modal_payload()["fields"]["notification"]
        client.emit("worker:add", {
            "slot": 0,
            "type": "notification",
            "fields": {
                "name": "Empty Manual Notify",
                "activation": "manual",
                "disposition": "review",
                "notification": notification,
            },
        })
        assert _event_payloads(client, "layout:updated")
        client.get_received()

        client.emit("worker:start", {"slot": 0})
        synthetic = _wait_for_synthetic_task(app.config["bp_dir"], "Empty Manual Notify", "review")
        notification_events = []
        deadline = time.time() + 3
        while time.time() < deadline:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)

        assert synthetic is not None
        assert synthetic["assigned_to"] == ""
        assert notification_events
        fired = notification_events[-1]
        assert fired["worker"]["name"] == "Empty Manual Notify"
        assert fired["ticket"]["id"] == synthetic["id"]
        assert fired["ticket"]["title"] == synthetic["title"]
        assert fired["channels"]["speech"]["text"] == f"Speak normal {synthetic['title']}"

        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == []
        assert final_layout["slots"][0]["state"] == "idle"
    finally:
        client.disconnect()
        tmp.cleanup()


def test_notification_worker_on_drop_assignment_fires_notification_and_routes_ticket():
    tmp, app, client = _make_client()
    try:
        notification = _node_modal_payload()["fields"]["notification"]
        client.emit("worker:add", {
            "slot": 0,
            "type": "notification",
            "fields": {
                "name": "Drop Notify",
                "disposition": "review",
                "notification": notification,
            },
        })
        layout = _event_payloads(client, "layout:updated")[-1]
        assert layout["slots"][0]["activation"] == "on_drop"

        client.emit("task:create", {"title": "Dropped notification ticket", "priority": "high"})
        created = _event_payloads(client, "task:created")[-1]
        client.emit("task:assign", {"task_id": created["id"], "slot": 0})

        updated = _wait_for_task_status(app.config["bp_dir"], created["id"], "review")
        notification_events = []
        deadline = time.time() + 3
        while time.time() < deadline:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)

        assert updated["assigned_to"] == ""
        assert notification_events
        fired = notification_events[-1]
        assert fired["worker"]["name"] == "Drop Notify"
        assert fired["ticket"]["title"] == "Dropped notification ticket"
        assert fired["channels"]["speech"]["text"] == "Speak high Dropped notification ticket"

        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == []
        assert final_layout["slots"][0]["state"] == "idle"
    finally:
        client.disconnect()
        tmp.cleanup()
