"""Tests for web terminal validation and Socket.IO events."""

import os
import time

import pytest

from server.app import create_app, socketio
from server.validation import (
    ValidationError,
    validate_terminal_id,
    validate_terminal_input,
    validate_terminal_size,
)

TERMINAL_CLIENT_ID = "terminal-client-test"


def _events(client, name, timeout=2.0):
    deadline = time.time() + timeout
    found = []
    while time.time() < deadline:
        found.extend(evt for evt in client.get_received() if evt["name"] == name)
        if found:
            return found
        time.sleep(0.05)
    return found


def test_terminal_validation_accepts_uuid_and_size():
    assert validate_terminal_id({"terminalId": "123e4567-e89b-12d3-a456-426614174000"})
    assert validate_terminal_id({"clientId": TERMINAL_CLIENT_ID}, field="clientId")
    assert validate_terminal_size({"cols": 120, "rows": 32}) == (120, 32)
    assert validate_terminal_input({"data": "echo ok\n"}) == "echo ok\n"


@pytest.mark.parametrize("payload", [
    {"terminalId": "../bad"},
    {"terminalId": ""},
    {"terminalId": "x" * 101},
])
def test_terminal_validation_rejects_bad_ids(payload):
    with pytest.raises(ValidationError):
        validate_terminal_id(payload)


def test_terminal_create_runs_in_workspace(tmp_workspace):
    if not hasattr(os, "openpty"):
        pytest.skip("PTY support is required")

    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    terminal_id = "term-test-1"
    client.emit("terminal:create", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
        "cols": 80,
        "rows": 24,
    })
    created = _events(client, "terminal:created")
    assert created
    assert os.path.realpath(created[0]["args"][0]["cwd"]) == os.path.realpath(tmp_workspace)

    client.emit("terminal:input", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
        "data": "pwd\nexit\n",
    })
    output = []
    deadline = time.time() + 3.0
    while time.time() < deadline:
        for evt in client.get_received():
            if evt["name"] == "terminal:output":
                output.append(evt["args"][0]["data"])
            if evt["name"] == "terminal:exit":
                app.config["terminal_manager"].close_all()
                output_text = "".join(output)
                assert os.path.realpath(tmp_workspace) in output_text or tmp_workspace in output_text
                return
        time.sleep(0.05)

    app.config["terminal_manager"].close_all()
    assert False, "terminal did not exit"


def test_terminal_close_emits_closed(tmp_workspace):
    if not hasattr(os, "openpty"):
        pytest.skip("PTY support is required")

    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    terminal_id = "term-test-close"
    client.emit("terminal:create", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
        "cols": 80,
        "rows": 24,
    })
    assert _events(client, "terminal:created")
    client.emit("terminal:close", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
    })
    assert _events(client, "terminal:closed")


def test_terminal_survives_socket_reconnect_and_replays_output(tmp_workspace):
    if not hasattr(os, "openpty"):
        pytest.skip("PTY support is required")

    app = create_app(tmp_workspace, no_browser=True)
    first = socketio.test_client(app)
    first.get_received()
    terminal_id = "term-test-reconnect"
    first.emit("terminal:create", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
        "cols": 80,
        "rows": 24,
    })
    assert _events(first, "terminal:created")
    first.emit("terminal:input", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
        "data": "printf reconnect-buffered-output\\n\n",
    })
    assert _events(first, "terminal:output")

    first.disconnect()
    manager = app.config["terminal_manager"]
    assert len(manager._sessions) == 1
    session = next(iter(manager._sessions.values()))
    assert session.owner_sid is None
    assert session.process.poll() is None

    resumed = socketio.test_client(app)
    resumed.get_received()
    resumed.emit("terminal:list", {
        "clientId": TERMINAL_CLIENT_ID,
        "lastSequences": {terminal_id: 0},
    })
    resume_events = resumed.get_received()
    listed = [event for event in resume_events if event["name"] == "terminal:list"]
    assert listed
    assert [item["terminalId"] for item in listed[0]["args"][0]["terminals"]] == [terminal_id]
    replayed = [event for event in resume_events if event["name"] == "terminal:output"]
    assert replayed
    assert "reconnect-buffered-output" in "".join(
        event["args"][0]["data"] for event in replayed
    )

    resumed.emit("terminal:resize", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
        "cols": 81,
        "rows": 24,
    })
    assert not [event for event in resumed.get_received() if event["name"] == "terminal:error"]
    manager.close_all()


def test_terminal_cannot_be_resumed_by_another_client_id(tmp_workspace):
    if not hasattr(os, "openpty"):
        pytest.skip("PTY support is required")

    app = create_app(tmp_workspace, no_browser=True)
    owner = socketio.test_client(app)
    owner.get_received()
    terminal_id = "term-test-owner"
    owner.emit("terminal:create", {
        "terminalId": terminal_id,
        "clientId": TERMINAL_CLIENT_ID,
        "cols": 80,
        "rows": 24,
    })
    assert _events(owner, "terminal:created")
    owner.disconnect()

    other = socketio.test_client(app)
    other.get_received()
    other.emit("terminal:list", {"clientId": "different-terminal-client"})
    listed = _events(other, "terminal:list")
    assert listed[0]["args"][0]["terminals"] == []
    app.config["terminal_manager"].close_all()


def test_detached_terminal_expires_after_reconnect_grace(tmp_workspace):
    if not hasattr(os, "openpty"):
        pytest.skip("PTY support is required")

    app = create_app(tmp_workspace, no_browser=True)
    manager = app.config["terminal_manager"]
    manager.reconnect_grace = 0.05
    client = socketio.test_client(app)
    client.get_received()
    client.emit("terminal:create", {
        "terminalId": "term-test-expiry",
        "clientId": TERMINAL_CLIENT_ID,
        "cols": 80,
        "rows": 24,
    })
    assert _events(client, "terminal:created")
    client.disconnect()

    deadline = time.time() + 2.0
    while manager._sessions and time.time() < deadline:
        time.sleep(0.01)
    assert manager._sessions == {}
