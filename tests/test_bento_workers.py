"""Tests for Bullpen worker Bento export and preview."""

import io
import json
import os
import zipfile

from server.app import create_app
from server.init import init_workspace
from server.persistence import read_json, write_json


def _read_zip_json(data, path):
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        return json.loads(zf.read(path))


def _post_preview(client, data):
    return client.post(
        "/api/bento/preview",
        data={"file": (io.BytesIO(data), "workers.bento")},
        content_type="multipart/form-data",
    )


def test_export_single_worker_bento_includes_manifest_worker_and_profile(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {
                    "name": "Builder",
                    "type": "shell",
                    "profile": "custom-worker",
                    "command": "make test",
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

    resp = client.get("/api/bento/export?kind=worker&slot=0")

    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/vnd.bullpen.bento+zip")
    assert "bullpen-worker-Builder-" in resp.headers.get("Content-Disposition", "")
    assert ".bento" in resp.headers.get("Content-Disposition", "")
    manifest = _read_zip_json(resp.data, "bento.json")
    assert manifest["format"] == "bento"
    assert manifest["profiles"][0]["id"] == "org.bullpen.share"
    assert manifest["bullpen"]["kind"] == "worker"
    worker_item = next(item for item in manifest["items"] if item["bullpen_type"] == "worker")
    profile_item = next(item for item in manifest["items"] if item["bullpen_type"] == "profile")
    worker = _read_zip_json(resp.data, worker_item["path"])
    profile = _read_zip_json(resp.data, profile_item["path"])
    assert worker["name"] == "Builder"
    assert worker["state"] == "idle"
    assert worker["task_queue"] == []
    assert "started_at" not in worker
    assert profile["id"] == "custom-worker"
    assert "workspaceId" not in profile


def test_export_worker_group_bento_preserves_relative_positions(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {"name": "Left", "type": "ai", "col": 4, "row": 2, "disposition": "pass:right"},
                {"name": "Right", "type": "ai", "col": 5, "row": 2, "disposition": "pass:left"},
            ]
        },
    )

    resp = client.get("/api/bento/export?kind=worker-group&slots=0,1")

    assert resp.status_code == 200
    manifest = _read_zip_json(resp.data, "bento.json")
    assert manifest["bullpen"]["kind"] == "worker-group"
    worker_items = [item for item in manifest["items"] if item["bullpen_type"] == "worker"]
    workers = [_read_zip_json(resp.data, item["path"]) for item in worker_items]
    coords = {(worker["name"], worker["col"], worker["row"]) for worker in workers}
    assert coords == {("Left", 4, 2), ("Right", 5, 2)}


def test_bento_preview_upgrades_bullpen_worker_package(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()
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
    export_resp = client.get("/api/bento/export?kind=worker&slot=0")

    preview_resp = _post_preview(client, export_resp.data)

    assert preview_resp.status_code == 200
    preview = preview_resp.get_json()
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
    client = app.test_client()
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {"name": "Left", "type": "ai", "col": 2, "row": 2, "disposition": "worker:Right"},
                {"name": "Right", "type": "ai", "col": 3, "row": 2},
            ]
        },
    )
    export_resp = client.get("/api/bento/export?kind=worker-group&slots=0,1")

    preview_resp = _post_preview(client, export_resp.data)

    assert preview_resp.status_code == 200
    items = preview_resp.get_json()["bullpen"]["items"]
    left = next(item for item in items if item["name"] == "Left")
    assert left["bindings"][0]["status"] == "package-local"


def test_bento_preview_carrier_only_for_non_bullpen_package(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()
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

    resp = _post_preview(client, mem.getvalue())

    assert resp.status_code == 200
    preview = resp.get_json()
    assert "bullpen" not in preview
    assert preview["unsupported_profiles"] == ["org.example.other"]


def test_bento_export_rejects_unknown_kind_and_slot(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    bad_kind = client.get("/api/bento/export?kind=ticket&id=one")
    bad_slot = client.get("/api/bento/export?kind=worker&slot=99")

    assert bad_kind.status_code == 400
    assert bad_slot.status_code == 404
