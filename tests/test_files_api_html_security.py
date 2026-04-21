"""HTTP regression checks for safe raw HTML handling."""

import os

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
