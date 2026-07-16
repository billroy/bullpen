"""Tests for Bullpen worker Bento export and preview."""

import io
import json
import os
import zipfile

from server.app import create_app, socketio
from server.init import init_workspace
from server.persistence import read_json, write_json


def _read_zip_json(data, path):
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        return json.loads(zf.read(path))


def _received(client, name):
    matches = [event["args"][0] for event in client.get_received() if event["name"] == name]
    assert matches, f"missing socket event {name}"
    return matches[-1]


def _export_worker(client, **payload):
    client.emit("bento:export", payload)
    return _received(client, "bento:exported")


def _preview(client, data):
    client.emit("bento:preview", {"file": data})
    return _received(client, "bento:previewed")


def _import_bento(client, data, **payload):
    body = {"file": data}
    body.update(payload)
    client.emit("bento:import", body)
    return _received(client, "bento:imported")


def test_export_single_worker_bento_includes_manifest_worker_and_profile(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {
                    "name": "Builder",
                    "type": "shell",
                    "profile": "custom-worker",
                    "command": "make test",
                    "env": [{"key": "TOKEN", "value": "secret"}],
                    "use_worktree": True,
                    "auto_commit": True,
                    "state": "running",
                    "task_queue": ["ticket-1"],
                    "started_at": "2026-01-01T00:00:00Z",
                    "col": 2,
                    "row": 3,
                }
            ]
        },
    )
    write_json(
        os.path.join(bp_dir, "profiles", "custom-worker.json"),
        {"id": "custom-worker", "name": "Custom Worker", "workspaceId": "local"},
    )

    exported = _export_worker(client, kind="worker", slot=0, request_id="export-worker-1")

    assert exported["mimetype"] == "application/vnd.bullpen.bento+zip"
    assert exported["request_id"] == "export-worker-1"
    assert exported["filename"].startswith("bullpen-worker-Builder-")
    assert exported["filename"].endswith(".bento")
    manifest = _read_zip_json(exported["data"], "bento.json")
    assert manifest["format"] == "bento"
    assert manifest["profiles"][0]["id"] == "org.bullpen.share"
    assert manifest["bullpen"]["kind"] == "worker"
    worker_item = next(item for item in manifest["items"] if item["bullpen_type"] == "worker")
    profile_item = next(item for item in manifest["items"] if item["bullpen_type"] == "profile")
    worker = _read_zip_json(exported["data"], worker_item["path"])
    profile = _read_zip_json(exported["data"], profile_item["path"])
    assert worker["name"] == "Builder"
    assert worker["state"] == "idle"
    assert worker["task_queue"] == []
    assert "started_at" not in worker
    assert profile["id"] == "custom-worker"
    assert "workspaceId" not in profile


def test_export_worker_group_bento_preserves_relative_positions(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    ws_id = app.config["startup_workspace_id"]
    app.config["manager"].get(ws_id).name = "Project: alpha/beta?"
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {"name": "Left", "type": "ai", "col": 4, "row": 2, "disposition": "pass:right"},
                {"name": "Right", "type": "ai", "col": 5, "row": 2, "disposition": "pass:left"},
            ]
        },
    )

    exported = _export_worker(client, kind="worker-group", slots=[0, 1])

    assert exported["filename"].startswith("bullpen-worker-group-Project-alpha-beta-")
    assert exported["filename"].endswith(".bento")
    manifest = _read_zip_json(exported["data"], "bento.json")
    assert manifest["bullpen"]["kind"] == "worker-group"
    worker_items = [item for item in manifest["items"] if item["bullpen_type"] == "worker"]
    workers = [_read_zip_json(exported["data"], item["path"]) for item in worker_items]
    coords = {(worker["name"], worker["col"], worker["row"]) for worker in workers}
    assert coords == {("Left", 4, 2), ("Right", 5, 2)}


def test_bento_preview_upgrades_bullpen_worker_package(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {
                    "name": "Deploy",
                    "type": "shell",
                    "command": "deploy.sh",
                    "env": [{"key": "TOKEN", "value": "secret"}],
                    "disposition": "worker:Reviewer",
                    "col": 0,
                    "row": 0,
                },
                {"name": "Reviewer", "type": "ai", "col": 1, "row": 0},
            ]
        },
    )
    exported = _export_worker(client, kind="worker", slot=0)

    preview = _preview(client, exported["data"])

    assert preview["supported_profiles"] == ["org.bullpen.share"]
    assert preview["kind"] == "worker"
    assert preview["bullpen"]["items"][0]["name"] == "Deploy"
    assert preview["bullpen"]["items"][0]["worker_type"] == "shell"
    assert preview["bullpen"]["items"][0]["capabilities"] == ["commands", "env"]
    assert preview["bullpen"]["items"][0]["bindings"][0]["status"] == "workspace"
    assert preview["bullpen"]["placement"]["status"] == "conflict"
    assert preview["bullpen"]["placement"]["conflicts"][0]["existing_name"] == "Deploy"


def test_bento_preview_reports_package_local_binding_for_worker_group(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {"name": "Left", "type": "ai", "col": 2, "row": 2, "disposition": "worker:Right"},
                {"name": "Right", "type": "ai", "col": 3, "row": 2},
            ]
        },
    )
    exported = _export_worker(client, kind="worker-group", slots=[0, 1])

    preview = _preview(client, exported["data"])

    items = preview["bullpen"]["items"]
    left = next(item for item in items if item["name"] == "Left")
    assert left["bindings"][0]["status"] == "package-local"


def test_bento_preview_carrier_only_for_non_bullpen_package(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "bento.json",
            json.dumps(
                {
                    "format": "bento",
                    "version": "1",
                    "profiles": [{"id": "org.example.other", "version": "1"}],
                    "items": [],
                    "attributes": [],
                }
            ),
        )
    mem.seek(0)

    preview = _preview(client, mem.getvalue())

    assert "bullpen" not in preview
    assert preview["unsupported_profiles"] == ["org.example.other"]


def test_bento_export_rejects_unknown_kind_and_slot(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    client.emit("bento:export", {"kind": "not-a-kind", "id": "one"})
    bad_kind = _received(client, "bento:error")
    client.emit("bento:export", {"kind": "worker", "slot": 99})
    bad_slot = _received(client, "bento:error")

    assert bad_kind["code"] == "invalid-kind"
    assert bad_slot["code"] == "unknown-worker-slot"


def test_bento_import_single_worker_adds_sanitized_dormant_worker(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {
                    "name": "Builder",
                    "type": "shell",
                    "profile": "custom-worker",
                    "command": "make test",
                    "env": [{"key": "TOKEN", "value": "secret"}],
                    "use_worktree": True,
                    "auto_commit": True,
                    "state": "running",
                    "task_queue": ["ticket-1"],
                    "started_at": "2026-01-01T00:00:00Z",
                    "col": 2,
                    "row": 3,
                }
            ]
        },
    )
    write_json(
        os.path.join(bp_dir, "profiles", "custom-worker.json"),
        {"id": "custom-worker", "name": "Custom Worker", "workspaceId": "local"},
    )
    exported = _export_worker(client, kind="worker", slot=0)
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": []})
    os.unlink(os.path.join(bp_dir, "profiles", "custom-worker.json"))

    imported = _import_bento(client, exported["data"])

    layout = read_json(os.path.join(bp_dir, "layout.json"))
    worker = layout["slots"][0]
    profile = read_json(os.path.join(bp_dir, "profiles", "custom-worker.json"))
    assert imported["imported"] == {"workers": 1, "profiles": 1}
    assert imported["slots"] == [0]
    assert worker["name"] == "Builder"
    assert worker["command"] == ""
    assert worker["env"] == []
    assert worker["use_worktree"] is False
    assert worker["auto_commit"] is False
    assert worker["state"] == "idle"
    assert worker["task_queue"] == []
    assert "started_at" not in worker
    assert profile["id"] == "custom-worker"
    assert "workspaceId" not in profile
    capabilities = {entry["capability"] for entry in imported["sanitized"]}
    assert {"commands", "env", "git", "runtime"} <= capabilities


def test_bento_import_preserves_approved_capability_fields(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {
                    "name": "Builder",
                    "type": "shell",
                    "command": "make test",
                    "env": [{"key": "TOKEN", "value": "secret"}],
                    "use_worktree": True,
                    "auto_pr": True,
                    "col": 1,
                    "row": 1,
                }
            ]
        },
    )
    exported = _export_worker(client, kind="worker", slot=0)
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": []})

    imported = _import_bento(
        client,
        exported["data"],
        approvals={"commands": True, "env": True, "git": True},
    )

    layout = read_json(os.path.join(bp_dir, "layout.json"))
    worker = layout["slots"][0]
    assert {entry["capability"] for entry in imported["sanitized"]} == {"runtime"}
    assert worker["command"] == "make test"
    assert worker["env"] == [{"key": "TOKEN", "value": "secret"}]
    assert worker["use_worktree"] is True
    assert worker["auto_pr"] is True


def test_bento_import_group_can_choose_anchor_and_preserve_relative_positions(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {"name": "Left", "type": "ai", "col": 4, "row": 2},
                {"name": "Right", "type": "ai", "col": 5, "row": 2},
            ]
        },
    )
    exported = _export_worker(client, kind="worker-group", slots=[0, 1])
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": []})

    imported = _import_bento(
        client,
        exported["data"],
        placement={"strategy": "choose-anchor", "anchor": {"col": 1, "row": 3}},
    )

    layout = read_json(os.path.join(bp_dir, "layout.json"))
    coords = {(worker["name"], worker["col"], worker["row"]) for worker in layout["slots"]}
    assert imported["placement"] == {"strategy": "choose-anchor", "anchor": {"col": 1, "row": 3}}
    assert coords == {("Left", 1, 3), ("Right", 2, 3)}


def test_bento_import_renames_conflicts_and_rewrites_package_local_bindings(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {"name": "Left", "type": "ai", "col": 2, "row": 2, "disposition": "worker:Right"},
                {"name": "Right", "type": "ai", "col": 3, "row": 2},
            ]
        },
    )
    exported = _export_worker(client, kind="worker-group", slots=[0, 1])
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {"slots": [{"name": "Right", "type": "ai", "col": 0, "row": 0}]},
    )

    imported = _import_bento(
        client,
        exported["data"],
        placement={"strategy": "choose-anchor", "anchor": {"col": 1, "row": 0}},
    )

    layout = read_json(os.path.join(bp_dir, "layout.json"))
    imported_left = next(worker for worker in layout["slots"] if worker["name"] == "Left")
    imported_right = next(worker for worker in layout["slots"] if worker["name"] == "Right copy")
    assert imported["renamed"] == [{"from": "Right", "to": "Right copy"}]
    assert imported["rewritten_bindings"] == [
        {"worker": "Left", "field": "disposition", "from": "worker:Right", "to": "worker:Right copy"}
    ]
    assert imported_left["disposition"] == "worker:Right copy"
    assert imported_right["col"] == 2


def test_bento_import_translates_and_recalculates_formula_group(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {"slots": [
            {
                "type": "value", "name": "Input", "col": 2, "row": 35,
                "value": 10, "value_type": "auto", "resolved_value_type": "number",
                "save_history": True, "history": [],
            },
            {
                "type": "value", "name": "Formula", "col": 2, "row": 36,
                "value": 11, "value_type": "auto", "resolved_value_type": "number",
                "save_history": True, "history": [],
                "formula": {"source": "=C36+1", "version": 1},
                "formula_state": {"status": "ok"},
            },
        ]},
    )
    exported = _export_worker(client, kind="worker-group", slots=[0, 1])
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": []})

    _import_bento(
        client,
        exported["data"],
        placement={"strategy": "choose-anchor", "anchor": {"col": 3, "row": 35}},
    )

    layout = read_json(os.path.join(bp_dir, "layout.json"))
    by_name = {slot["name"]: slot for slot in layout["slots"] if slot}
    assert (by_name["Input"]["col"], by_name["Input"]["row"]) == (3, 35)
    assert by_name["Formula"]["formula"]["source"] == "=D36+1"
    assert by_name["Formula"]["value"] == 11
    assert [entry["value"] for entry in by_name["Formula"]["history"]] == [11]


def test_bento_import_preserve_reports_placement_conflict(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": [{"name": "One", "type": "ai", "col": 0, "row": 0}]})
    exported = _export_worker(client, kind="worker", slot=0)

    client.emit("bento:import", {"file": exported["data"]})
    error = _received(client, "bento:error")

    assert error["code"] == "placement-conflict"


def test_bento_import_with_preview_state_rejects_stale_workspace(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": [{"name": "One", "type": "ai", "col": 0, "row": 0}]})
    exported = _export_worker(client, kind="worker", slot=0)
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": []})
    preview = _preview(client, exported["data"])
    preview_state = preview["bullpen"]["placement"]["state"]
    write_json(os.path.join(bp_dir, "layout.json"), {"slots": [{"name": "Two", "type": "ai", "col": 0, "row": 0}]})

    client.emit("bento:import", {"file": exported["data"], "placement": {"strategy": "preserve", "state": preview_state}})
    error = _received(client, "bento:error")

    layout = read_json(os.path.join(bp_dir, "layout.json"))
    assert error["code"] == "stale-preview"
    assert [worker["name"] for worker in layout["slots"]] == ["Two"]
