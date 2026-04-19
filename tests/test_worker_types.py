"""Tests for worker type normalization and storage helpers."""

import os

from server.init import init_workspace
from server.persistence import read_json, write_json
from server.teams import load_team, save_team
from server.transfer import transfer_worker
from server.validation import validate_worker_configure
from server.worker_types import (
    ViewerContext,
    copy_worker_slot,
    normalize_layout,
    normalize_worker_slot,
    serialize_worker_slot,
)
from server.workspace_manager import WorkspaceManager


def test_legacy_ai_slot_defaults_to_ai_and_saves_type(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    config = read_json(os.path.join(bp_dir, "config.json"))

    slot = normalize_worker_slot(
        {
            "row": 0,
            "col": 0,
            "name": "Legacy",
            "agent": "mock",
            "model": "mock-model",
        },
        index=0,
        config=config,
    )

    assert slot["type"] == "ai"
    assert slot["agent"] == "mock"
    assert slot["model"] == "mock-model"

    layout = normalize_layout({"slots": [slot]}, config=config)
    write_json(os.path.join(bp_dir, "layout.json"), layout)

    saved = read_json(os.path.join(bp_dir, "layout.json"))
    assert saved["slots"][0]["type"] == "ai"


def test_unknown_worker_type_preserves_unknown_fields_through_configure_and_copy(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    config = read_json(os.path.join(bp_dir, "config.json"))
    raw = {
        "type": "acme-widget",
        "row": 1,
        "col": 2,
        "name": "Mystery",
        "activation": "manual",
        "state": "working",
        "task_queue": ["ticket-1"],
        "last_trigger_time": 123,
        "paused": True,
        "custom_payload": {"keep": ["me"]},
    }

    slot = normalize_worker_slot(raw, index=3, config=config)
    assert slot["type"] == "acme-widget"
    assert slot["custom_payload"] == {"keep": ["me"]}

    _, fields = validate_worker_configure({
        "slot": 3,
        "fields": {
            "type": "acme-widget",
            "custom_payload": {"changed": True},
            "command": "should round trip even on unknown",
        },
    }, max_slots=200)
    slot.update(fields)
    slot = normalize_worker_slot(slot, index=3, config=config)

    assert slot["custom_payload"] == {"changed": True}
    assert slot["command"] == "should round trip even on unknown"

    clone = copy_worker_slot(slot, reset_runtime=True)
    assert clone["type"] == "acme-widget"
    assert clone["custom_payload"] == {"changed": True}
    assert clone["task_queue"] == []
    assert clone["state"] == "idle"
    assert clone["last_trigger_time"] is None
    assert clone["paused"] is False


def test_shell_slot_round_trips_through_team_save_load(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    shell = {
        "type": "shell",
        "row": 0,
        "col": 0,
        "name": "Shell Gate",
        "command": "python3 scripts/check.py",
        "env": [{"key": "FOO", "value": "bar"}],
        "cwd": "tools",
        "timeout_seconds": 90,
        "ticket_delivery": "env-vars",
        "task_queue": ["running-ticket"],
        "state": "working",
    }
    layout = normalize_layout({"slots": [shell]}, config=read_json(os.path.join(bp_dir, "config.json")))

    saved = save_team(bp_dir, "shellteam", layout)
    loaded = load_team(bp_dir, "shellteam")

    assert saved["slots"][0]["type"] == "shell"
    assert saved["slots"][0]["command"] == "python3 scripts/check.py"
    assert saved["slots"][0]["env"] == [{"key": "FOO", "value": "bar"}]
    assert "task_queue" not in saved["slots"][0]
    assert loaded["slots"][0]["type"] == "shell"
    assert loaded["slots"][0]["command"] == "python3 scripts/check.py"
    assert loaded["slots"][0]["task_queue"] == []
    assert loaded["slots"][0]["state"] == "idle"


def test_unknown_worker_type_transfer_preserves_fields(tmp_path):
    ws_a = str(tmp_path / "a")
    ws_b = str(tmp_path / "b")
    os.makedirs(ws_a)
    os.makedirs(ws_b)
    manager = WorkspaceManager(global_dir=str(tmp_path / "global"))
    id_a = manager.register_project(ws_a, name="A")
    id_b = manager.register_project(ws_b, name="B")

    bp_a = manager.get_bp_dir(id_a)
    layout = read_json(os.path.join(bp_a, "layout.json"))
    layout["slots"] = [{
        "type": "vendor-special",
        "row": 0,
        "col": 0,
        "name": "Special",
        "custom_field": {"nested": True},
        "state": "idle",
        "task_queue": [],
    }]
    write_json(os.path.join(bp_a, "layout.json"), layout)

    result = transfer_worker(manager, id_a, 0, id_b, None, "copy")

    bp_b = manager.get_bp_dir(id_b)
    dest = read_json(os.path.join(bp_b, "layout.json"))["slots"][result["dest_slot"]]
    assert dest["type"] == "vendor-special"
    assert dest["custom_field"] == {"nested": True}
    assert dest["state"] == "idle"
    assert dest["task_queue"] == []


def test_shell_read_only_serialization_redacts_command_and_env_values(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    config = read_json(os.path.join(bp_dir, "config.json"))
    slot = normalize_worker_slot(
        {
            "type": "shell",
            "row": 0,
            "col": 0,
            "name": "Secret Shell",
            "command": "curl -H 'Authorization: secret'",
            "env": [{"key": "TOKEN", "value": "super-secret"}],
        },
        index=0,
        config=config,
    )

    editable = serialize_worker_slot(slot, viewer=ViewerContext(can_edit=True))
    read_only = serialize_worker_slot(slot, viewer=ViewerContext(can_edit=False))

    assert editable["command"].startswith("curl")
    assert editable["env"] == [{"key": "TOKEN", "value": "super-secret"}]
    assert read_only["command"] == "<redacted>"
    assert read_only["env"] == [{"key": "TOKEN", "value": "<redacted>"}]
