"""Frontend contract tests for resilient terminal reconnects."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_terminal_client_identity_and_resume_are_connection_independent():
    text = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "sessionStorage.getItem(key)" in text
    assert "clientId: terminalClientId" in text
    assert "socket.emit('terminal:list'" in text
    assert "lastSequences" in text
    assert "tab.status = 'reconnecting'" in text


def test_terminal_traffic_is_suppressed_while_disconnected():
    text = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "if (!tab || tab.status !== 'running') return;" in text
    assert "!['running', 'starting'].includes(tab.status)" in text
    assert "tab.status = 'expired'" in text


def test_terminal_output_is_sequence_buffered_for_replay():
    text = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "lastOutputSeq" in text
    assert "replayFromSeq" in text
    assert "[terminal output omitted while disconnected]" in text
