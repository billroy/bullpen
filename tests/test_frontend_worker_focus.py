"""Frontend regression checks for Worker Focus streaming wiring."""

from pathlib import Path
import re


def _app_js_text():
    root = Path(__file__).resolve().parents[1]
    return (root / "static" / "app.js").read_text(encoding="utf-8")


def test_worker_focus_component_registered_in_root_components():
    text = _app_js_text()
    match = re.search(r"components:\s*{(?P<body>.*?)}\s*,\s*setup\(", text, re.S)
    assert match, "Could not locate root component registration block in static/app.js"
    body = match.group("body")
    assert "WorkerFocusView" in body, "WorkerFocusView must be registered in root components"


def test_worker_focus_template_and_stream_handlers_exist():
    text = _app_js_text()
    assert "<WorkerFocusView" in text, "WorkerFocusView should be rendered from root template"
    assert "socket.on('worker:output'" in text, "worker:output handler must exist"
    assert "socket.on('worker:output:done'" in text, "worker:output:done handler must exist"

