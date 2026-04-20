"""Tests for Service worker manual lifecycle."""

import json
import os
import sys
import time

from server.init import init_workspace
from server.persistence import read_json, write_json
from server.tasks import create_task, read_task
from server.service_worker import (
    get_controller,
    restart_service,
    start_service,
    stop_all_services,
    stop_service,
    tail_service,
)
from server.workers import assign_task, start_worker, _load_layout


class FakeSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, payload, to=None):
        self.events.append((event, dict(payload), to))


def _write_script(path, body):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


def _install_service_worker(bp_dir, workspace, **overrides):
    script = os.path.join(workspace, "service_app.py")
    _write_script(
        script,
        "import time\n"
        "print('service-ready', flush=True)\n"
        "time.sleep(30)\n",
    )
    worker = {
        "type": "service",
        "row": 0,
        "col": 0,
        "name": "Preview Server",
        "command": f'"{sys.executable}" "{script}"',
        "activation": "on_drop",
        "disposition": "review",
        "startup_grace_seconds": 0,
        "startup_timeout_seconds": 5,
        "stop_timeout_seconds": 1,
        "task_queue": [],
        "state": "idle",
    }
    worker.update(overrides)
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    layout["slots"] = [worker]
    write_json(os.path.join(bp_dir, "layout.json"), layout)
    return worker


def _wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    return None


def test_service_manual_start_stop_and_tail(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    _install_service_worker(bp_dir, tmp_workspace)
    socket = FakeSocket()
    ws_id = "ws-service"

    assert start_service(bp_dir, ws_id, 0, socket) is True
    assert start_service(bp_dir, ws_id, 0, socket) is False
    controller = get_controller(bp_dir, ws_id, 0, socket)
    running = _wait_for(lambda: controller.state_snapshot()["state"] == "running")
    assert running is True
    assert controller.state_snapshot()["pid"]

    log_seen = _wait_for(lambda: any(
        event == "service:log" and "service-ready" in "\n".join(payload.get("lines", []))
        for event, payload, _ in socket.events
    ))
    assert log_seen is True

    tail_service(bp_dir, ws_id, 0, socket, max_bytes=65536)
    catchup = [payload for event, payload, _ in socket.events if event == "service:log" and payload.get("catchup")]
    assert catchup
    assert catchup[-1]["reset"] is True
    assert "service-ready" in "\n".join(catchup[-1]["lines"])

    assert stop_service(bp_dir, ws_id, 0, socket) is True
    stopped = _wait_for(lambda: controller.state_snapshot()["state"] == "stopped")
    assert stopped is True
    assert controller.state_snapshot()["pid"] is None


def test_service_restart_replaces_process(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    _install_service_worker(bp_dir, tmp_workspace)
    socket = FakeSocket()
    ws_id = "ws-service-restart"

    start_service(bp_dir, ws_id, 0, socket)
    controller = get_controller(bp_dir, ws_id, 0, socket)
    assert _wait_for(lambda: controller.state_snapshot()["state"] == "running") is True
    first_pid = controller.state_snapshot()["pid"]

    assert restart_service(bp_dir, ws_id, 0, socket) is True
    assert _wait_for(lambda: controller.state_snapshot()["state"] == "running" and controller.state_snapshot()["pid"] != first_pid) is True
    assert controller.state_snapshot()["pid"] != first_pid

    stop_service(bp_dir, ws_id, 0, socket)


def test_service_pre_start_failure_crashes_without_main_process(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    _install_service_worker(bp_dir, tmp_workspace, pre_start=f'"{sys.executable}" -c "import sys; sys.exit(3)"')
    socket = FakeSocket()
    ws_id = "ws-service-prestart"

    start_service(bp_dir, ws_id, 0, socket)
    controller = get_controller(bp_dir, ws_id, 0, socket)
    assert _wait_for(lambda: controller.state_snapshot()["state"] == "crashed") is True
    snapshot = controller.state_snapshot()
    assert snapshot["pid"] is None
    assert "Pre-start exited" in snapshot["last_error"]


def test_service_ticket_order_routes_and_injects_ticket_env(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    output_path = os.path.join(tmp_workspace, "service-env.json")
    script = os.path.join(tmp_workspace, "ticket_service.py")
    _write_script(
        script,
        "import json, os, time\n"
        f"out = {output_path!r}\n"
        "data = {key: os.environ.get(key, '') for key in [\n"
        "    'BULLPEN_SERVICE_ORDER_ID', 'BULLPEN_SERVICE_COMMIT',\n"
        "    'BULLPEN_TICKET_ID', 'BULLPEN_TICKET_TITLE', 'BULLPEN_TICKET_STATUS',\n"
        "    'BULLPEN_TICKET_PRIORITY', 'BULLPEN_TICKET_TAGS']}\n"
        "open(out, 'w', encoding='utf-8').write(json.dumps(data))\n"
        "print('ticket-service-ready', flush=True)\n"
        "time.sleep(30)\n",
    )
    _install_service_worker(
        bp_dir,
        tmp_workspace,
        command=f'"{sys.executable}" "{script}"',
        activation="manual",
        disposition="review",
        max_retries=0,
    )
    task = create_task(bp_dir, "Restart test server", description="commit: abcdef1\n")
    assign_task(bp_dir, 0, task["id"])

    start_worker(bp_dir, 0)

    assert _wait_for(lambda: read_task(bp_dir, task["id"]).get("status") == "review") is True
    updated = read_task(bp_dir, task["id"])
    assert updated["assigned_to"] == ""
    history = [row for row in updated.get("history", []) if row.get("event") == "service_order_succeeded"]
    assert history
    assert history[-1]["log_artifact"].startswith(".bullpen/logs/services/slot-0/")
    layout = _load_layout(bp_dir)
    assert layout["slots"][0]["task_queue"] == []
    assert layout["slots"][0]["state"] == "idle"

    assert _wait_for(lambda: os.path.exists(output_path)) is True
    injected = json.loads(open(output_path, encoding="utf-8").read())
    assert injected["BULLPEN_SERVICE_ORDER_ID"] == task["id"]
    assert injected["BULLPEN_SERVICE_COMMIT"] == "abcdef1"
    assert injected["BULLPEN_TICKET_ID"] == task["id"]
    assert injected["BULLPEN_TICKET_TITLE"] == "Restart test server"
    assert injected["BULLPEN_TICKET_STATUS"] == "in_progress"
    assert injected["BULLPEN_TICKET_PRIORITY"] == "normal"

    stop_service(bp_dir, None, 0)


def test_service_ticket_order_restarts_running_service(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    _install_service_worker(bp_dir, tmp_workspace, activation="manual", ticket_action="restart", max_retries=0)
    socket = FakeSocket()
    ws_id = "ws-service-ticket-restart"

    start_service(bp_dir, ws_id, 0, socket)
    controller = get_controller(bp_dir, ws_id, 0, socket)
    assert _wait_for(lambda: controller.state_snapshot()["state"] == "running") is True
    first_pid = controller.state_snapshot()["pid"]

    task = create_task(bp_dir, "Restart running service")
    assign_task(bp_dir, 0, task["id"], socket, ws_id)
    start_worker(bp_dir, 0, socket, ws_id)
    assert _wait_for(lambda: read_task(bp_dir, task["id"]).get("status") == "review") is True

    snapshot = controller.state_snapshot()
    assert snapshot["state"] == "running"
    assert snapshot["pid"] != first_pid
    history = [row for row in read_task(bp_dir, task["id"]).get("history", []) if row.get("event") == "service_order_succeeded"]
    assert history[-1]["action"] == "restart"

    stop_service(bp_dir, ws_id, 0, socket)


def test_service_ticket_order_failure_blocks_and_records_history(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    _install_service_worker(
        bp_dir,
        tmp_workspace,
        activation="manual",
        pre_start=f'"{sys.executable}" -c "import sys; sys.exit(4)"',
        max_retries=0,
    )
    task = create_task(bp_dir, "Broken service")
    assign_task(bp_dir, 0, task["id"])

    start_worker(bp_dir, 0)

    assert _wait_for(lambda: read_task(bp_dir, task["id"]).get("status") == "blocked") is True
    updated = read_task(bp_dir, task["id"])
    history = updated.get("history", [])
    assert any(row.get("event") == "service_order_started" for row in history)
    failed = [row for row in history if row.get("event") == "service_order_failed"]
    assert failed
    assert "Pre-start exited" in failed[-1]["reason"]
    assert "Pre-start exited" in updated["body"]


def teardown_module(_module):
    stop_all_services(wait=True)
