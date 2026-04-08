"""Tests for agent adapters."""

import json

import pytest

from server.agents import get_adapter, register_adapter, list_adapters
from server.agents.claude_adapter import ClaudeAdapter
from server.agents.codex_adapter import CodexAdapter
from tests.conftest import MockAdapter


class TestClaudeAdapter:
    def test_name(self):
        adapter = ClaudeAdapter()
        assert adapter.name == "claude"

    def test_build_argv(self):
        adapter = ClaudeAdapter()
        argv = adapter.build_argv("test prompt", "sonnet", "/workspace")
        assert any("claude" in arg for arg in argv)
        assert "--model" in argv
        assert "sonnet" in argv
        assert "--output-format" in argv
        assert "stream-json" in argv

    def test_parse_success(self):
        adapter = ClaudeAdapter()
        stdout = json.dumps({"type": "result", "subtype": "success",
                             "is_error": False, "result": "Hello world"})
        result = adapter.parse_output(stdout, "", 0)
        assert result["success"] is True
        assert result["output"] == "Hello world"
        assert result["error"] is None

    def test_parse_failure(self):
        adapter = ClaudeAdapter()
        result = adapter.parse_output("", "Something failed", 1)
        assert result["success"] is False
        assert result["error"] == "Something failed"

    def test_parse_error_result(self):
        adapter = ClaudeAdapter()
        stdout = json.dumps({"type": "result", "is_error": True,
                             "result": "Task failed"})
        result = adapter.parse_output(stdout, "", 0)
        assert result["success"] is False
        assert result["error"] == "Task failed"

    def test_parse_fallback_to_assistant_text(self):
        """If no result line, extract text from assistant messages."""
        adapter = ClaudeAdapter()
        stdout = json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": "Fallback output"}]}})
        result = adapter.parse_output(stdout, "", 0)
        assert result["success"] is True
        assert result["output"] == "Fallback output"

    def test_format_stream_line_assistant_text(self):
        adapter = ClaudeAdapter()
        line = json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": "Hello"}]}})
        assert adapter.format_stream_line(line) == "Hello"

    def test_format_stream_line_tool_use(self):
        adapter = ClaudeAdapter()
        line = json.dumps({"type": "assistant", "message": {
            "content": [{"type": "tool_use", "name": "Bash",
                         "input": {"command": "ls -la"}}]}})
        assert adapter.format_stream_line(line) == "$ ls -la"

    def test_format_stream_line_skips_system(self):
        adapter = ClaudeAdapter()
        line = json.dumps({"type": "system", "subtype": "init"})
        assert adapter.format_stream_line(line) is None

    def test_format_stream_line_skips_result(self):
        adapter = ClaudeAdapter()
        line = json.dumps({"type": "result", "result": "done"})
        assert adapter.format_stream_line(line) is None


class TestCodexAdapter:
    def test_name(self):
        adapter = CodexAdapter()
        assert adapter.name == "codex"

    def test_build_argv(self):
        adapter = CodexAdapter()
        argv = adapter.build_argv("test prompt", "o4-mini", "/workspace")
        assert any("codex" in arg for arg in argv)
        assert "exec" in argv
        assert "--model" in argv
        assert "o4-mini" in argv
        assert "--full-auto" in argv
        assert "-" in argv
        assert "--approval-mode" not in argv
        assert "--quiet" not in argv

    def test_parse_success_falls_back_to_stderr_when_stdout_empty(self):
        adapter = CodexAdapter()
        result = adapter.parse_output("", "assistant reply from stderr", 0)
        assert result["success"] is True
        assert result["output"] == "assistant reply from stderr"
        assert result["error"] is None


class TestMockAdapter:
    def test_basic(self):
        adapter = MockAdapter(output="test output")
        assert adapter.name == "mock"
        assert adapter.available() is True
        result = adapter.parse_output("test output", "", 0)
        assert result["success"] is True
        assert result["output"] == "test output"

    def test_failure(self):
        adapter = MockAdapter(exit_code=1)
        result = adapter.parse_output("", "error msg", 1)
        assert result["success"] is False


class TestRegistry:
    def test_get_claude(self):
        adapter = get_adapter("claude")
        assert adapter is not None
        assert adapter.name == "claude"

    def test_get_codex(self):
        adapter = get_adapter("codex")
        assert adapter is not None
        assert adapter.name == "codex"

    def test_get_nonexistent(self):
        assert get_adapter("nonexistent") is None

    def test_register_custom(self):
        mock = MockAdapter()
        register_adapter("mock", mock)
        assert get_adapter("mock") is mock
        assert "mock" in list_adapters()
