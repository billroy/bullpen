"""Tests for agent adapters."""

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

    def test_parse_success(self):
        adapter = ClaudeAdapter()
        result = adapter.parse_output("Hello world", "", 0)
        assert result["success"] is True
        assert result["output"] == "Hello world"
        assert result["error"] is None

    def test_parse_failure(self):
        adapter = ClaudeAdapter()
        result = adapter.parse_output("", "Something failed", 1)
        assert result["success"] is False
        assert result["error"] == "Something failed"


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
