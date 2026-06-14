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


def _node_runtime_payload():
    result = subprocess.run(
        ["node", str(ROOT / "tests/js/notification_runtime_kokoro.js")],
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


def _complete_notification(client, payload):
    client.emit("notification:complete", {
        "workspaceId": payload.get("workspaceId"),
        "delivery_id": payload["id"],
        "slot": payload["slot"],
        "task_id": payload["ticket"]["id"],
        "status": "complete",
    })


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
            "engine": "kokoro",
            "voice": "af_bella",
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


def test_notification_runtime_uses_kokoro_for_kokoro_engine():
    payload = _node_runtime_payload()

    assert payload["imports"] == ["test-loader"]
    assert payload["generated"][0]["opts"]["voice"] == "af_bella"
    assert payload["generated"][1]["opts"]["voice"] == "af_heart"
    assert payload["webSpeech"] == []


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

        notification_events = _event_payloads(client, "notification:fire")
        client.emit("worker:start", {"slot": 0})
        deadline = time.time() + 3
        while time.time() < deadline and not notification_events:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)

        assert notification_events
        fired = notification_events[-1]
        in_progress = _wait_for_task_status(app.config["bp_dir"], created["id"], "in_progress")
        assert str(in_progress["assigned_to"]) == "0"
        assert fired["worker"]["name"] == "Manual Notify"
        assert fired["ticket"]["title"] == "Manual notification ticket"
        assert fired["channels"]["toast"]["enabled"] is False
        assert fired["channels"]["toast"]["variant"] == "warning"
        assert fired["channels"]["speech"]["enabled"] is True
        assert fired["channels"]["speech"]["text"] == "Speak urgent Manual notification ticket"
        assert fired["channels"]["speech"]["engine"] == "kokoro"
        assert fired["channels"]["speech"]["voice"] == "af_bella"
        assert fired["channels"]["sound"]["effect"] == "warning"
        assert fired["channels"]["flash"]["sequence"] == [{"color": "#00ff88", "duration_ms": 220}]
        assert fired["policy"]["cooldown_ms"] == 2500

        _complete_notification(client, fired)
        updated = _wait_for_task_status(app.config["bp_dir"], created["id"], "review")
        assert updated["assigned_to"] == ""

        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == []
        assert final_layout["slots"][0]["state"] == "idle"
    finally:
        client.disconnect()
        tmp.cleanup()


def test_notification_worker_speech_template_can_reference_value_worker():
    tmp, app, client = _make_client()
    try:
        client.emit("worker:add", {
            "slot": 1,
            "type": "value",
            "fields": {
                "name": "direction",
                "value": "west",
                "value_type": "string",
            },
        })
        assert _event_payloads(client, "layout:updated")

        notification = {
            "toast": {"enabled": False, "template": "{ticket.title}", "variant": "stage", "duration_ms": 1000},
            "speech": {"enabled": True, "template": "Direction {direction}", "engine": "kokoro", "voice": "af_heart", "rate": 1, "volume": 1},
            "sound": {"enabled": False, "effect": "done", "repeat_count": 1, "gap_ms": 250, "volume": 1},
            "flash": {"enabled": False, "sequence": [], "opacity": 0.35},
            "policy": {"cooldown_ms": 0, "dedupe_window_ms": 0},
        }
        client.emit("worker:add", {
            "slot": 0,
            "type": "notification",
            "fields": {
                "name": "Value Notify",
                "activation": "manual",
                "disposition": "review",
                "notification": notification,
            },
        })
        assert _event_payloads(client, "layout:updated")

        client.emit("task:create", {"title": "Value notification ticket", "priority": "normal"})
        created = _event_payloads(client, "task:created")[-1]
        client.emit("task:assign", {"task_id": created["id"], "slot": 0})
        client.get_received()

        notification_events = []
        client.emit("worker:start", {"slot": 0})
        deadline = time.time() + 3
        while time.time() < deadline and not notification_events:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)

        assert notification_events
        fired = notification_events[-1]
        assert fired["channels"]["speech"]["enabled"] is True
        assert fired["channels"]["speech"]["text"] == "Direction west"

        _complete_notification(client, fired)
        updated = _wait_for_task_status(app.config["bp_dir"], created["id"], "review")
        assert updated["assigned_to"] == ""
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
        assert notification_events
        fired = notification_events[-1]
        assert fired["ticket"]["id"] == synthetic["id"]
        in_progress = _wait_for_task_status(app.config["bp_dir"], synthetic["id"], "in_progress")
        assert str(in_progress["assigned_to"]) == "0"
        assert fired["worker"]["name"] == "Empty Manual Notify"
        assert fired["ticket"]["title"] == synthetic["title"]
        assert fired["channels"]["speech"]["text"] == f"Speak normal {synthetic['title']}"

        _complete_notification(client, fired)
        updated = _wait_for_task_status(app.config["bp_dir"], synthetic["id"], "review")
        assert updated["assigned_to"] == ""

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

        notification_events = []
        deadline = time.time() + 3
        while time.time() < deadline:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)

        assert notification_events
        fired = notification_events[-1]
        in_progress = _wait_for_task_status(app.config["bp_dir"], created["id"], "in_progress")
        assert str(in_progress["assigned_to"]) == "0"
        assert fired["worker"]["name"] == "Drop Notify"
        assert fired["ticket"]["title"] == "Dropped notification ticket"
        assert fired["channels"]["speech"]["text"] == "Speak high Dropped notification ticket"

        _complete_notification(client, fired)
        updated = _wait_for_task_status(app.config["bp_dir"], created["id"], "review")
        assert updated["assigned_to"] == ""

        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == []
        assert final_layout["slots"][0]["state"] == "idle"
    finally:
        client.disconnect()
        tmp.cleanup()


def test_notification_pass_loop_waits_for_completion_and_pause_stops_advance():
    tmp, app, client = _make_client()
    try:
        speech_only = {
            "toast": {"enabled": False, "template": "{ticket.title}", "variant": "stage", "duration_ms": 1000},
            "speech": {"enabled": True, "template": "Speak {worker.name}", "engine": "kokoro", "voice": "af_heart", "rate": 1, "volume": 1},
            "sound": {"enabled": False, "effect": "done", "repeat_count": 1, "gap_ms": 250, "volume": 1},
            "flash": {"enabled": False, "sequence": [], "opacity": 0.35},
            "policy": {"cooldown_ms": 0, "dedupe_window_ms": 0},
        }
        for slot, name, disposition in [
            (0, "Notify A", "pass:right"),
            (1, "Notify B", "pass:down"),
            (5, "Notify C", "pass:left"),
            (4, "Notify D", "pass:up"),
        ]:
            client.emit("worker:add", {
                "slot": slot,
                "type": "notification",
                "fields": {
                    "name": name,
                    "activation": "on_drop",
                    "disposition": disposition,
                    "notification": speech_only,
                },
            })
            assert _event_payloads(client, "layout:updated")

        client.emit("task:create", {"title": "Loop notification ticket", "priority": "high"})
        created = _event_payloads(client, "task:created")[-1]
        client.emit("task:assign", {"task_id": created["id"], "slot": 0})

        notification_events = []
        deadline = time.time() + 3
        while time.time() < deadline:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)

        assert len(notification_events) == 1
        first = notification_events[0]
        assert first["worker"]["name"] == "Notify A"
        in_progress = _wait_for_task_status(app.config["bp_dir"], created["id"], "in_progress")
        assert str(in_progress["assigned_to"]) == "0"

        client.emit("workers:pause_automation", {})
        client.get_received()
        _complete_notification(client, first)
        held = _wait_for_task_status(app.config["bp_dir"], created["id"], "assigned")
        assert str(held["assigned_to"]) == "0"

        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == [created["id"]]
        assert final_layout["slots"][0]["state"] == "idle"
        assert final_layout["slots"][1]["task_queue"] == []
        assert final_layout["slots"][4]["task_queue"] == []
        assert final_layout["slots"][5]["task_queue"] == []
    finally:
        client.disconnect()
        tmp.cleanup()


def test_notification_stop_line_cancels_pending_completion_before_handoff():
    tmp, app, client = _make_client()
    try:
        speech_only = {
            "toast": {"enabled": False, "template": "{ticket.title}", "variant": "stage", "duration_ms": 1000},
            "speech": {"enabled": True, "template": "Speak {worker.name}", "engine": "kokoro", "voice": "af_heart", "rate": 1, "volume": 1},
            "sound": {"enabled": False, "effect": "done", "repeat_count": 1, "gap_ms": 250, "volume": 1},
            "flash": {"enabled": False, "sequence": [], "opacity": 0.35},
            "policy": {"cooldown_ms": 0, "dedupe_window_ms": 0},
        }
        client.emit("worker:add", {
            "slot": 0,
            "type": "notification",
            "fields": {
                "name": "Stop A",
                "activation": "on_drop",
                "disposition": "pass:right",
                "notification": speech_only,
            },
        })
        assert _event_payloads(client, "layout:updated")
        client.emit("worker:add", {
            "slot": 1,
            "type": "notification",
            "fields": {
                "name": "Stop B",
                "activation": "on_drop",
                "disposition": "review",
                "notification": speech_only,
            },
        })
        assert _event_payloads(client, "layout:updated")

        client.emit("task:create", {"title": "Stop pending notification", "priority": "high"})
        created = _event_payloads(client, "task:created")[-1]
        client.emit("task:assign", {"task_id": created["id"], "slot": 0})

        notification_events = []
        deadline = time.time() + 3
        while time.time() < deadline:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)
        assert len(notification_events) == 1
        fired = notification_events[0]

        client.emit("workers:stop_line", {})
        events = client.get_received()
        assert any(evt["name"] == "notification:cancel" for evt in events)

        held = _wait_for_task_status(app.config["bp_dir"], created["id"], "assigned")
        assert str(held["assigned_to"]) == "0"
        _complete_notification(client, fired)
        time.sleep(0.2)

        still_held = _wait_for_task_status(app.config["bp_dir"], created["id"], "assigned")
        assert str(still_held["assigned_to"]) == "0"
        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == [created["id"]]
        assert final_layout["slots"][0]["state"] == "idle"
        assert "pending_notification" not in final_layout["slots"][0]
        assert final_layout["slots"][1]["task_queue"] == []
    finally:
        client.disconnect()
        tmp.cleanup()


def test_notification_delivery_timeout_blocks_when_browser_does_not_ack(monkeypatch):
    from server import workers as worker_mod

    monkeypatch.setattr(worker_mod, "NOTIFICATION_DELIVERY_TIMEOUT_SECONDS", 0.1)
    tmp, app, client = _make_client()
    try:
        speech_only = {
            "toast": {"enabled": False, "template": "{ticket.title}", "variant": "stage", "duration_ms": 1000},
            "speech": {"enabled": True, "template": "Speak {worker.name}", "engine": "kokoro", "voice": "af_heart", "rate": 1, "volume": 1},
            "sound": {"enabled": False, "effect": "done", "repeat_count": 1, "gap_ms": 250, "volume": 1},
            "flash": {"enabled": False, "sequence": [], "opacity": 0.35},
            "policy": {"cooldown_ms": 0, "dedupe_window_ms": 0},
        }
        client.emit("worker:add", {
            "slot": 0,
            "type": "notification",
            "fields": {
                "name": "Timeout Notify",
                "activation": "on_drop",
                "disposition": "review",
                "notification": speech_only,
            },
        })
        assert _event_payloads(client, "layout:updated")

        client.emit("task:create", {"title": "Unacknowledged notification", "priority": "high"})
        created = _event_payloads(client, "task:created")[-1]
        client.emit("task:assign", {"task_id": created["id"], "slot": 0})

        notification_events = []
        deadline = time.time() + 3
        while time.time() < deadline:
            notification_events.extend(_event_payloads(client, "notification:fire"))
            if notification_events:
                break
            time.sleep(0.05)
        assert len(notification_events) == 1

        blocked = _wait_for_task_status(app.config["bp_dir"], created["id"], "blocked")
        assert blocked["assigned_to"] == ""

        layout_path = os.path.join(app.config["bp_dir"], "layout.json")
        final_layout = json.load(open(layout_path, encoding="utf-8"))
        assert final_layout["slots"][0]["task_queue"] == []
        assert final_layout["slots"][0]["state"] == "idle"
        assert "pending_notification" not in final_layout["slots"][0]
    finally:
        client.disconnect()
        tmp.cleanup()
