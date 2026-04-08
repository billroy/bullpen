"""Tests for MCP tool server behaviors."""

import io
import json

from server import mcp_tools
from server.init import init_workspace
from server.tasks import create_task


class _DummySio:
    def __init__(self):
        self.handlers = {}

    def on(self, name):
        def _register(fn):
            self.handlers[name] = fn
            return fn
        return _register

    def connect(self, url):
        raise RuntimeError(f"connect failed: {url}")

    def disconnect(self):
        return None

    def emit(self, *_args, **_kwargs):
        raise AssertionError("emit should not be called when disconnected")


def test_list_tasks_alias_returns_ticket_summary(tmp_workspace, monkeypatch):
    bp_dir = init_workspace(tmp_workspace)
    created = create_task(bp_dir, "MCP alias test")

    captured = {}

    def fake_tool_result(msg_id, text, is_error=False):
        captured["id"] = msg_id
        captured["text"] = text
        captured["is_error"] = is_error

    monkeypatch.setattr(mcp_tools, "_tool_result", fake_tool_result)

    mcp_tools.handle_call(bp_dir, client=None, msg_id=7, name="list_tasks", args={})

    assert captured["id"] == 7
    assert captured["is_error"] is False
    summary = json.loads(captured["text"])
    ids = {item["id"] for item in summary}
    assert created["id"] in ids


def test_bullpen_client_degrades_when_socket_unavailable(monkeypatch):
    monkeypatch.setattr(
        mcp_tools.socketio,
        "Client",
        lambda logger=False, engineio_logger=False: _DummySio(),
    )

    client = mcp_tools.BullpenClient("127.0.0.1", 5050)
    assert client.connected is False

    task, err = client.create_ticket({"title": "x"})
    assert task is None
    assert "unavailable" in err


def test_bullpen_client_adds_loopback_candidates_for_wildcard_host(monkeypatch):
    monkeypatch.setattr(
        mcp_tools.socketio,
        "Client",
        lambda logger=False, engineio_logger=False: _DummySio(),
    )

    client = mcp_tools.BullpenClient("0.0.0.0", 5050)
    urls = client._candidate_urls()

    assert "http://0.0.0.0:5050" in urls
    assert "http://127.0.0.1:5050" in urls
    assert "http://localhost:5050" in urls


def test_read_parses_mcp_content_length_frame():
    payload = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
    framed = b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload

    msg = mcp_tools._read(io.BytesIO(framed))

    assert msg["method"] == "initialize"
    assert msg["id"] == 1


def test_write_emits_mcp_content_length_frame():
    out = io.BytesIO()
    mcp_tools._write({"jsonrpc": "2.0", "id": 9, "result": {"ok": True}}, out_stream=out)
    raw = out.getvalue()

    header, body = raw.split(b"\r\n\r\n", 1)
    assert header.startswith(b"Content-Length:")
    declared_len = int(header.split(b":", 1)[1].strip())
    assert declared_len == len(body)
    parsed = json.loads(body.decode("utf-8"))
    assert parsed["id"] == 9
    assert parsed["result"]["ok"] is True
