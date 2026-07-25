import os
from pathlib import Path

import pytest

import server.file_browser as file_browser_mod
from server.file_browser import FileBrowserError, open_file_in_browser
from server.init import init_workspace


def test_open_file_in_browser_launches_html_file_uri(tmp_workspace, monkeypatch):
    init_workspace(tmp_workspace)
    html_path = os.path.join(tmp_workspace, "preview.html")
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write("<h1>Hello</h1>")
    opened = []
    monkeypatch.setattr(file_browser_mod.webbrowser, "open", lambda url, new=0: opened.append((url, new)) or True)

    result = open_file_in_browser(tmp_workspace, "preview.html")

    assert result["ok"] is True
    assert result["path"] == "preview.html"
    assert result["mime"].startswith("text/html")
    assert opened == [(Path(html_path).resolve().as_uri(), 2)]


def test_open_file_in_browser_rejects_unsupported_file_type(tmp_workspace, monkeypatch):
    init_workspace(tmp_workspace)
    with open(os.path.join(tmp_workspace, "payload.bin"), "wb") as handle:
        handle.write(b"\x00\x01")
    opened = []
    monkeypatch.setattr(file_browser_mod.webbrowser, "open", lambda url, new=0: opened.append((url, new)) or True)

    with pytest.raises(FileBrowserError) as exc:
        open_file_in_browser(tmp_workspace, "payload.bin")

    assert exc.value.status == 415
    assert exc.value.message == "File type cannot be opened in browser"
    assert opened == []


def test_open_file_in_browser_rejects_traversal(tmp_workspace, monkeypatch):
    init_workspace(tmp_workspace)
    outside = os.path.join(os.path.dirname(tmp_workspace), "outside.html")
    with open(outside, "w", encoding="utf-8") as handle:
        handle.write("<h1>Outside</h1>")
    opened = []
    monkeypatch.setattr(file_browser_mod.webbrowser, "open", lambda url, new=0: opened.append((url, new)) or True)

    with pytest.raises(FileBrowserError) as exc:
        open_file_in_browser(tmp_workspace, "../outside.html")

    assert exc.value.status == 403
    assert opened == []
