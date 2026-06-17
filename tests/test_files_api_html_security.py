"""Regression checks for safe file browsing and raw HTML handling."""

import os
import json

from server.app import create_app, socketio
from server.init import init_workspace


def _received(client, name):
    for event in client.get_received():
        if event["name"] == name:
            return event["args"][0]
    return None


def test_raw_html_file_is_served_as_attachment(tmp_workspace):
    init_workspace(tmp_workspace)
    html_path = os.path.join(tmp_workspace, "preview.html")
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write("<h1>Hello</h1>")

    app = create_app(tmp_workspace, no_browser=True)
    client = app.test_client()

    resp = client.get("/api/files/preview.html?raw=1")

    assert resp.status_code == 200
    assert resp.headers.get("Content-Disposition", "").startswith("attachment;")
    assert resp.headers.get("Content-Type", "").startswith("text/html")


def test_json_file_is_returned_as_text_payload_for_viewer(tmp_workspace):
    init_workspace(tmp_workspace)
    json_path = os.path.join(tmp_workspace, "data.json")
    payload = {"name": "Bullpen", "enabled": True}
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("files:read", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "read-json",
        "path": "data.json",
    })

    body = _received(client, "files:read")
    assert body is not None
    assert body["request_id"] == "read-json"
    assert body["path"] == "data.json"
    assert body["mime"].startswith("application/json")
    assert '"name": "Bullpen"' in body["content"]
    client.disconnect()


def test_file_write_rejects_payloads_over_one_mb(tmp_workspace):
    init_workspace(tmp_workspace)
    path = os.path.join(tmp_workspace, "large.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("small")

    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("files:write", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "write-large",
        "path": "large.txt",
        "content": "x" * 1_000_001,
    })

    body = _received(client, "files:error")
    assert body is not None
    assert body["status"] == 400
    assert body["error"] == "File too large (max 1MB)"
    client.disconnect()


def test_create_only_file_write_rejects_existing_file(tmp_workspace):
    init_workspace(tmp_workspace)
    path = os.path.join(tmp_workspace, "exists.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("original")

    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("files:write", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "write-existing",
        "path": "exists.txt",
        "content": "replacement",
        "create": True,
    })

    body = _received(client, "files:error")
    assert body is not None
    assert body["status"] == 409
    assert body["error"] == "File already exists"
    with open(path, encoding="utf-8") as handle:
        assert handle.read() == "original"
    client.disconnect()


def test_create_only_file_write_creates_missing_file(tmp_workspace):
    init_workspace(tmp_workspace)

    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("files:write", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "write-new",
        "path": "new/note.txt",
        "content": "draft",
        "create": True,
    })

    body = _received(client, "files:written")
    assert body is not None
    assert body["request_id"] == "write-new"
    with open(os.path.join(tmp_workspace, "new", "note.txt"), encoding="utf-8") as handle:
        assert handle.read() == "draft"
    client.disconnect()


def test_file_tree_returns_over_socket(tmp_workspace):
    init_workspace(tmp_workspace)
    with open(os.path.join(tmp_workspace, "note.txt"), "w", encoding="utf-8") as handle:
        handle.write("hello")
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("files:list", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "tree-one",
    })

    body = _received(client, "files:listed")
    assert body is not None
    assert body["request_id"] == "tree-one"
    assert any(node["path"] == "note.txt" for node in body["tree"])
    client.disconnect()
