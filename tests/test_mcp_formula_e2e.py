"""Real stdio-to-Socket.IO formula integration coverage."""

import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest


ROOT = os.path.dirname(os.path.dirname(__file__))


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("local port binding is not permitted in this sandbox")
        return sock.getsockname()[1]


def _frame(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload


def _parse_frames(raw):
    stream = io.BytesIO(raw)
    messages = []
    while True:
        header = stream.readline()
        if not header:
            return messages
        if not header.strip():
            continue
        assert header.lower().startswith(b"content-length:")
        length = int(header.split(b":", 1)[1].strip())
        assert stream.readline() == b"\r\n"
        messages.append(json.loads(stream.read(length)))


def _wait_for_server(url, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError(f"server did not start: {url}")


def test_mcp_stdio_formula_round_trip_and_formula_increment_policy(tmp_path):
    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace)
    port = _free_port()
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    os.makedirs(env["HOME"])
    server = subprocess.Popen(
        [
            sys.executable,
            "bullpen.py",
            "--workspace",
            workspace,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-browser",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(f"http://127.0.0.1:{port}")
        request_bytes = b"".join([
            _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            _frame({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
            _frame({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "set_formula",
                    "arguments": {"ref": "A1", "formula": "=ROW()*100+COLUMN()", "value_type": "number"},
                },
            }),
            _frame({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_formula", "arguments": {"ref": "A1"}},
            }),
            _frame({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "increment_value", "arguments": {"ref": "A1", "amount": 1}},
            }),
        ])
        result = subprocess.run(
            [
                sys.executable,
                os.path.join("server", "mcp_tools.py"),
                "--workspace",
                workspace,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            input=request_bytes,
            capture_output=True,
            timeout=20,
        )

        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        responses = {message["id"]: message for message in _parse_frames(result.stdout)}
        set_payload = json.loads(responses[2]["result"]["content"][0]["text"])
        get_payload = json.loads(responses[3]["result"]["content"][0]["text"])
        increment_error = json.loads(responses[4]["result"]["content"][0]["text"])
        assert set_payload["value"] == 101
        assert get_payload["formula"]["source"] == "=ROW()*100+COLUMN()"
        assert get_payload["formula_state"]["status"] == "ok"
        assert responses[4]["result"]["isError"] is True
        assert "Cannot increment formula-backed Value" in increment_error["message"]
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
