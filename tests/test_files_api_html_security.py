"""HTTP regression checks for safe raw HTML handling."""

import os
import json

from server.app import create_app
from server.init import init_workspace


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
    client = app.test_client()

    resp = client.get("/api/files/data.json")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["path"] == "data.json"
    assert body["mime"].startswith("application/json")
    assert '"name": "Bullpen"' in body["content"]
