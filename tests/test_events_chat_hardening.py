"""Tests for Live Agent chat hardening in events module."""

import json
import os
import tempfile

from server.events import _claude_mcp_startup_state, _classify_chat_provider_error, _harden_live_agent_argv


def test_harden_live_agent_argv_for_claude_adds_strict_and_disallowed_tools():
    argv = ["claude", "--print", "--mcp-config", os.path.join(tempfile.gettempdir(), "x.json")]
    hardened = _harden_live_agent_argv("claude", argv)

    assert "--strict-mcp-config" in hardened
    assert "--disallowedTools" in hardened
    idx = hardened.index("--disallowedTools")
    assert "Bash" in hardened[idx + 1]
    assert "Read" in hardened[idx + 1]


def test_harden_live_agent_argv_for_codex_no_change():
    argv = ["codex", "exec", "--model", "gpt-5.3-codex"]
    hardened = _harden_live_agent_argv("codex", argv)
    assert hardened == argv


def test_harden_live_agent_argv_for_gemini_no_change():
    argv = ["gemini", "--model", "gemini-2.5-pro"]
    hardened = _harden_live_agent_argv("gemini", argv)
    assert hardened == argv


def test_claude_mcp_startup_state_on_pending_status():
    line = json.dumps({
        "type": "system",
        "subtype": "init",
        "mcp_servers": [{"name": "bullpen", "status": "pending"}],
    })
    state, msg = _claude_mcp_startup_state(line)
    assert state == "pending"
    assert "pending" in msg


def test_claude_mcp_startup_state_ready_when_connected():
    line = json.dumps({
        "type": "system",
        "subtype": "init",
        "mcp_servers": [{"name": "bullpen", "status": "connected"}],
    })
    assert _claude_mcp_startup_state(line) == ("ready", None)


def test_claude_mcp_startup_state_error_when_server_missing():
    line = json.dumps({
        "type": "system",
        "subtype": "init",
        "mcp_servers": [{"name": "other", "status": "connected"}],
    })
    state, msg = _claude_mcp_startup_state(line)
    assert state == "error"
    assert "not loaded" in msg


def test_classify_chat_provider_error_for_gemini_model_not_found():
    msg = _classify_chat_provider_error("gemini", "ModelNotFoundError: Requested entity was not found.")
    assert msg is not None
    assert "model not found" in msg.lower()
