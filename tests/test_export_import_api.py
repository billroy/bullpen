"""Tests for workspace archive export/import Socket.IO events."""

import io
import json
import os
import zipfile

from server.app import (
    _MAX_IMPORT_ARCHIVE_FILES,
    _MAX_IMPORT_COMPRESSION_RATIO,
    create_app,
    socketio,
)
from server.init import init_workspace
from server import mcp_auth
from server.persistence import read_json, write_json


def _zip_bytes(entries):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
    mem.seek(0)
    return mem


def _received(client, name):
    matches = [event["args"][0] for event in client.get_received() if event["name"] == name]
    assert matches, f"missing socket event {name}"
    return matches[-1]


def _export_archive(client, **payload):
    client.emit("archive:export", payload)
    return _received(client, "archive:exported")


def _import_archive(client, data, **payload):
    body = {"file": data}
    body.update(payload)
    client.emit("archive:import", body)
    return _received(client, "archive:imported")


def _archive_error(client, data, **payload):
    body = {"file": data}
    body.update(payload)
    client.emit("archive:import", body)
    return _received(client, "archive:error")


def _inspect_import(client, data, **payload):
    body = {"file": data}
    body.update(payload)
    client.emit("import:inspect", body)
    return _received(client, "import:inspected")


def _inspect_import_error(client, data, **payload):
    body = {"file": data}
    body.update(payload)
    client.emit("import:inspect", body)
    return _received(client, "import:error")


def test_export_workspace_returns_zip_with_bullpen_dir(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    exported = _export_archive(client, kind="workspace")
    assert exported["ok"] is True
    assert exported["mimetype"] == "application/zip"
    assert exported["filename"].startswith("bullpen-workspace-")
    with zipfile.ZipFile(io.BytesIO(exported["data"]), "r") as zf:
        names = set(zf.namelist())
        exported_config = json.loads(zf.read(".bullpen/config.json"))
    assert ".bullpen/config.json" in names
    assert ".bullpen/layout.json" in names
    live_config = read_json(os.path.join(bp_dir, "config.json"))
    assert "server_host" in live_config
    assert "server_port" in live_config
    assert "mcp_token" not in live_config
    assert mcp_auth.read_workspace_mcp_token(bp_dir)
    assert "server_host" not in exported_config
    assert "server_port" not in exported_config
    assert "mcp_token" not in exported_config


def test_import_inspect_detects_workspace_archive(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    payload = {
        ".bullpen/config.json": json.dumps({"name": "Imported Workspace"}),
    }

    inspected = _inspect_import(client, _zip_bytes(payload).getvalue(), request_id="inspect-workspace")

    assert inspected["ok"] is True
    assert inspected["import_type"] == "workspace"
    assert inspected["request_id"] == "inspect-workspace"


def test_import_workspace_replaces_config_from_zip(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    original = read_json(os.path.join(bp_dir, "config.json"))
    original_token = mcp_auth.read_workspace_mcp_token(bp_dir)
    assert original["name"] == "Bullpen"

    payload = {
        ".bullpen/config.json": json.dumps({**original, "name": "Imported Workspace"}),
    }
    archive = _zip_bytes(payload)

    imported = _import_archive(client, archive.getvalue(), kind="workspace")
    assert imported["ok"] is True
    assert imported["imported"] == 1
    config = read_json(os.path.join(bp_dir, "config.json"))
    assert config["name"] == "Imported Workspace"
    assert config["server_host"] == app.config["host"]
    assert config["server_port"] == app.config["port"]
    assert "mcp_token" not in config
    assert mcp_auth.read_workspace_mcp_token(bp_dir) == original_token


def test_import_inspect_detects_all_workspace_archive(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    payload = {
        "bullpen-export.json": json.dumps({"schema": "bullpen-export-all-v1", "workspaces": []}),
        "workspaces/example/.bullpen/config.json": json.dumps({"name": "Imported"}),
    }

    inspected = _inspect_import(client, _zip_bytes(payload).getvalue())

    assert inspected["ok"] is True
    assert inspected["import_type"] == "all"
    assert inspected["schema"] == "bullpen-export-all-v1"


def test_import_inspect_detects_legacy_all_workspace_archive(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    payload = {
        "workspaces/example/.bullpen/config.json": json.dumps({"name": "Imported"}),
    }

    inspected = _inspect_import(client, _zip_bytes(payload).getvalue())

    assert inspected["ok"] is True
    assert inspected["import_type"] == "all"
    assert inspected["legacy"] is True


def test_export_all_and_import_all_round_trip(tmp_workspace):
    bp1 = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    manager = app.config["manager"]

    ws2 = os.path.join(tmp_workspace, "workspace-two")
    os.makedirs(ws2, exist_ok=True)
    bp2 = init_workspace(ws2)
    ws2_id = manager.register_project(ws2, name="workspace-two")
    ws1_id = app.config["startup_workspace_id"]
    mcp_auth.ensure_workspace_runtime_config(bp2, host=app.config["host"], port=app.config["port"])

    write_json(
        os.path.join(bp1, "config.json"),
        {
            "name": "One",
            "columns": [],
            "grid": {"rows": 4, "cols": 6},
            "server_host": app.config["host"],
            "server_port": app.config["port"],
        },
    )
    write_json(
        os.path.join(bp2, "config.json"),
        {
            "name": "Two",
            "columns": [],
            "grid": {"rows": 4, "cols": 6},
            "server_host": app.config["host"],
            "server_port": app.config["port"],
        },
    )
    token_one = mcp_auth.read_workspace_mcp_token(bp1)
    token_two = mcp_auth.read_workspace_mcp_token(bp2)

    client = socketio.test_client(app)
    exported = _export_archive(client, kind="all")
    assert exported["ok"] is True
    assert exported["filename"].startswith("bullpen-all-")
    with zipfile.ZipFile(io.BytesIO(exported["data"]), "r") as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("bullpen-export.json"))
        exported_one = json.loads(zf.read(f"workspaces/{ws1_id}/.bullpen/config.json"))
        exported_two = json.loads(zf.read(f"workspaces/{ws2_id}/.bullpen/config.json"))
    assert f"workspaces/{ws1_id}/.bullpen/config.json" in names
    assert f"workspaces/{ws2_id}/.bullpen/config.json" in names
    for ws in manifest["workspaces"]:
        assert "path" not in ws
    for exported in (exported_one, exported_two):
        assert "server_host" not in exported
        assert "server_port" not in exported
        assert "mcp_token" not in exported

    import_archive = _zip_bytes({
        f"workspaces/{ws1_id}/.bullpen/config.json": json.dumps({"name": "Imported One", "columns": [], "grid": {"rows": 4, "cols": 6}}),
        f"workspaces/{ws2_id}/.bullpen/config.json": json.dumps({"name": "Imported Two", "columns": [], "grid": {"rows": 4, "cols": 6}}),
    })
    imported = _import_archive(client, import_archive.getvalue(), kind="all")
    assert imported["ok"] is True
    assert imported["imported"] == 2
    config_one = read_json(os.path.join(bp1, "config.json"))
    config_two = read_json(os.path.join(bp2, "config.json"))
    assert config_one["name"] == "Imported One"
    assert config_two["name"] == "Imported Two"
    for config in (config_one, config_two):
        assert config["server_host"] == app.config["host"]
        assert config["server_port"] == app.config["port"]
        assert "mcp_token" not in config
    assert mcp_auth.read_workspace_mcp_token(bp1) == token_one
    assert mcp_auth.read_workspace_mcp_token(bp2) == token_two


def test_legacy_worker_zip_routes_are_removed(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {"name": "Builder", "profile": "custom-worker", "state": "idle", "task_queue": []}
            ]
        },
    )

    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/export/workers" not in routes
    assert "/api/export/worker" not in routes
    assert "/api/import/workers" not in routes
    assert client.get("/api/export/workers").status_code == 404
    assert client.get("/api/export/worker?slot=0").status_code == 404
    resp = client.post(
        "/api/import/workers",
        data={"file": (_zip_bytes({".bullpen/layout.json": json.dumps({"slots": []})}), "workers.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code in {404, 405}


def test_legacy_archive_routes_are_removed(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/export/workspace" not in routes
    assert "/api/export/all" not in routes
    assert "/api/import/workspace" not in routes
    assert "/api/import/all" not in routes
    assert client.get("/api/export/workspace").status_code == 404
    assert client.get("/api/export/all").status_code == 404
    assert client.post("/api/import/workspace").status_code in {404, 405}
    assert client.post("/api/import/all").status_code in {404, 405}


def test_import_inspect_rejects_unknown_archive(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    error = _inspect_import_error(client, _zip_bytes({"notes.txt": "hello"}).getvalue())

    assert error["ok"] is False
    assert error["code"] == "unknown-import-type"
    assert error["error"] == "Archive type could not be detected"


def test_import_workspace_rejects_archive_with_too_many_files(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    payload = {
        ".bullpen/config.json": json.dumps({"name": "Imported Workspace"}),
    }
    for idx in range(_MAX_IMPORT_ARCHIVE_FILES):
        payload[f".bullpen/files/file-{idx}.txt"] = "ok"

    error = _archive_error(client, _zip_bytes(payload).getvalue(), kind="workspace")

    assert error["code"] == "invalid-archive"
    assert error["error"] == "Archive contains too many files"


def test_import_workspace_rejects_high_expansion_archive(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    bomb_payload = {
        ".bullpen/config.json": json.dumps({"name": "Imported Workspace"}),
        ".bullpen/payload.txt": "A" * (_MAX_IMPORT_COMPRESSION_RATIO * 4096),
    }

    error = _archive_error(client, _zip_bytes(bomb_payload).getvalue(), kind="workspace")

    assert error["code"] == "invalid-archive"
    assert error["error"] == "Archive contains highly compressed entries"


def test_import_workspace_rejects_nested_archive_files(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)

    error = _archive_error(
        client,
        _zip_bytes(
            {
                ".bullpen/config.json": json.dumps({"name": "Imported Workspace"}),
                ".bullpen/nested/archive.zip": "not really a zip, still blocked",
            }
        ).getvalue(),
        kind="workspace",
    )

    assert error["code"] == "invalid-archive"
    assert error["error"] == "Archive contains nested archive files"
