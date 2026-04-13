"""Tests for workspace zip export/import endpoints."""

import io
import json
import os
import zipfile

from server.app import create_app
from server.init import init_workspace
from server.persistence import read_json, write_json


def _zip_bytes(entries):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
    mem.seek(0)
    return mem


def test_export_workspace_returns_zip_with_bullpen_dir(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    resp = client.get("/api/export/workspace")
    assert resp.status_code == 200
    assert resp.headers.get("Content-Type", "").startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
        names = set(zf.namelist())
    assert ".bullpen/config.json" in names
    assert ".bullpen/layout.json" in names


def test_import_workspace_replaces_config_from_zip(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    original = read_json(os.path.join(bp_dir, "config.json"))
    assert original["name"] == "Bullpen"

    payload = {
        ".bullpen/config.json": json.dumps({**original, "name": "Imported Workspace"}),
    }
    archive = _zip_bytes(payload)

    resp = client.post(
        "/api/import/workspace",
        data={"file": (archive, "workspace.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    config = read_json(os.path.join(bp_dir, "config.json"))
    assert config["name"] == "Imported Workspace"


def test_export_all_and_import_all_round_trip(tmp_workspace):
    bp1 = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    manager = app.config["manager"]

    ws2 = os.path.join(tmp_workspace, "workspace-two")
    os.makedirs(ws2, exist_ok=True)
    bp2 = init_workspace(ws2)
    ws2_id = manager.register_project(ws2, name="workspace-two")
    ws1_id = app.config["startup_workspace_id"]

    write_json(os.path.join(bp1, "config.json"), {"name": "One", "columns": [], "grid": {"rows": 4, "cols": 6}})
    write_json(os.path.join(bp2, "config.json"), {"name": "Two", "columns": [], "grid": {"rows": 4, "cols": 6}})

    client = app.test_client()
    export_resp = client.get("/api/export/all")
    assert export_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export_resp.data), "r") as zf:
        names = set(zf.namelist())
    assert f"workspaces/{ws1_id}/.bullpen/config.json" in names
    assert f"workspaces/{ws2_id}/.bullpen/config.json" in names

    import_archive = _zip_bytes({
        f"workspaces/{ws1_id}/.bullpen/config.json": json.dumps({"name": "Imported One", "columns": [], "grid": {"rows": 4, "cols": 6}}),
        f"workspaces/{ws2_id}/.bullpen/config.json": json.dumps({"name": "Imported Two", "columns": [], "grid": {"rows": 4, "cols": 6}}),
    })
    import_resp = client.post(
        "/api/import/all",
        data={"file": (import_archive, "all.zip")},
        content_type="multipart/form-data",
    )
    assert import_resp.status_code == 200
    assert import_resp.get_json()["imported"] == 2
    assert read_json(os.path.join(bp1, "config.json"))["name"] == "Imported One"
    assert read_json(os.path.join(bp2, "config.json"))["name"] == "Imported Two"


def test_export_workers_returns_workers_payload(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {
                    "name": "Builder",
                    "profile": "custom-worker",
                    "state": "idle",
                    "task_queue": [],
                }
            ]
        },
    )
    write_json(
        os.path.join(bp_dir, "profiles", "custom-worker.json"),
        {"id": "custom-worker", "name": "Custom Worker"},
    )

    resp = client.get("/api/export/workers")
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
        names = set(zf.namelist())
        exported_layout = json.loads(zf.read(".bullpen/layout.json"))
    assert ".bullpen/layout.json" in names
    assert ".bullpen/config.json" not in names
    assert ".bullpen/profiles/custom-worker.json" in names
    assert exported_layout["slots"][0]["name"] == "Builder"


def test_import_workers_replaces_layout_from_zip(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    write_json(os.path.join(bp_dir, "layout.json"), {"slots": []})
    archive = _zip_bytes(
        {
            ".bullpen/layout.json": json.dumps(
                {
                    "slots": [
                        {
                            "name": "Imported Worker",
                            "profile": "imported-profile",
                            "state": "idle",
                            "task_queue": [],
                        }
                    ]
                }
            ),
            ".bullpen/profiles/imported-profile.json": json.dumps(
                {"id": "imported-profile", "name": "Imported Profile"}
            ),
        }
    )

    resp = client.post(
        "/api/import/workers",
        data={"file": (archive, "workers.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    profile = read_json(os.path.join(bp_dir, "profiles", "imported-profile.json"))
    assert layout["slots"][0]["name"] == "Imported Worker"
    assert profile["id"] == "imported-profile"
