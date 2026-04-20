"""Tests for Service worker manual lifecycle."""

import os
import sys
import time

from server.init import init_workspace
from server.persistence import read_json, write_json
from server.service_worker import (
    get_controller,
    restart_service,
    start_service,
    stop_all_services,
    stop_service,
    tail_service,
)


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


def teardown_module(_module):
    stop_all_services(wait=True)
