"""Tests for Bullpen ticket Bento export, preview, and import."""

import io
import json
import os
import zipfile

from server.app import create_app, socketio
from server.init import init_workspace
from server.persistence import read_json, write_json
from server.tasks import create_task, list_tasks, read_task, update_task


def _read_zip_json(data, path):
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        return json.loads(zf.read(path))


def _received(client, name):
    matches = [event["args"][0] for event in client.get_received() if event["name"] == name]
    assert matches, f"missing socket event {name}"
    return matches[-1]


def _export(client, **payload):
    client.emit("bento:export", payload)
    return _received(client, "bento:exported")


def _preview(client, data):
    client.emit("bento:preview", {"file": data})
    return _received(client, "bento:previewed")


def _import(client, data, **payload):
    body = {"file": data}
    body.update(payload)
    client.emit("bento:import", body)
    return _received(client, "bento:imported")


def test_export_single_ticket_bento_includes_manifest_and_payload(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    task = create_task(bp_dir, "Fix import", description="Keep details", task_type="bug", priority="high", tags=["bento"])

    exported = _export(client, kind="ticket", id=task["id"])

    assert exported["mimetype"] == "application/vnd.bullpen.bento+zip"
    assert exported["filename"].startswith("bullpen-ticket-Fix-import-")
    manifest = _read_zip_json(exported["data"], "bento.json")
    assert manifest["profiles"][0]["id"] == "org.bullpen.share"
    assert manifest["bullpen"]["kind"] == "ticket"
    ticket_item = next(item for item in manifest["items"] if item["bullpen_type"] == "ticket")
    payload = _read_zip_json(exported["data"], ticket_item["path"])
    assert payload["id"] == task["id"]
    assert payload["title"] == "Fix import"
    assert payload["priority"] == "high"
    assert payload["type"] == "bug"
    assert payload["tags"] == ["bento"]
    assert "Keep details" in payload["body"]


def test_ticket_bento_preview_reports_safe_import_plan(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    task = create_task(bp_dir, "Assigned ticket", priority="urgent")
    update_task(bp_dir, task["id"], {"status": "assigned", "assigned_to": "Builder"})
    exported = _export(client, kind="ticket", id=task["id"])

    preview = _preview(client, exported["data"])

    assert preview["kind"] == "ticket"
    assert preview["bullpen"]["items"][0]["title"] == "Assigned ticket"
    assert preview["bullpen"]["items"][0]["source_status"] == "assigned"
    assert preview["bullpen"]["import"] == {
        "target_status": "backlog",
        "new_ids": True,
        "assignments_cleared": True,
    }
    assert preview["bullpen"]["items"][0]["warnings"] == ["ticket will import unassigned into backlog"]


def test_import_single_ticket_creates_new_backlog_ticket_without_assignment(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    write_json(
        os.path.join(bp_dir, "layout.json"),
        {
            "slots": [
                {
                    "name": "Backlog watcher",
                    "type": "ai",
                    "activation": "on_queue",
                    "watch_column": "backlog",
                    "task_queue": [],
                    "state": "idle",
                    "col": 0,
                    "row": 0,
                }
            ]
        },
    )
    task = create_task(bp_dir, "Move carefully", description="No worker should claim this.")
    update_task(bp_dir, task["id"], {"status": "assigned", "assigned_to": "Old worker"})
    exported = _export(client, kind="ticket", id=task["id"])
    before_ids = {item["id"] for item in list_tasks(bp_dir)}

    imported = _import(client, exported["data"])

    after = list_tasks(bp_dir)
    created = [item for item in after if item["id"] not in before_ids]
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    assert imported["imported"] == {"tickets": 1}
    assert len(created) == 1
    new_task = read_task(bp_dir, created[0]["id"])
    assert new_task["id"] != task["id"]
    assert new_task["title"] == "Move carefully"
    assert new_task["status"] == "backlog"
    assert new_task["assigned_to"] == ""
    assert new_task["source_task_id"] == task["id"]
    assert new_task["source_status"] == "assigned"
    assert "No worker should claim this." in new_task["body"]
    assert layout["slots"][0]["task_queue"] == []
    assert layout["slots"][0]["state"] == "idle"


def test_export_and_import_ticket_bundle(tmp_workspace):
    bp_dir = init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    first = create_task(bp_dir, "First bundle ticket", priority="low")
    second = create_task(bp_dir, "Second bundle ticket", priority="urgent")

    exported = _export(client, kind="ticket-bundle", ids=[first["id"], second["id"]])
    imported = _import(client, exported["data"], target_status="inbox")

    created = imported["tickets"]
    titles = {task["title"] for task in created}
    assert imported["kind"] == "ticket-bundle"
    assert imported["imported"] == {"tickets": 2}
    assert titles == {"First bundle ticket", "Second bundle ticket"}
    assert {task["status"] for task in created} == {"inbox"}
    assert {task["assigned_to"] for task in created} == {""}
