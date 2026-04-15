"""Tests for agent adapters."""

import json
import os

import pytest

from server.agents import get_adapter, register_adapter, list_adapters
from server.agents.claude_adapter import ClaudeAdapter
from server.agents.codex_adapter import CodexAdapter
from server.agents.gemini_adapter import GeminiAdapter
import server.agents.claude_adapter as claude_mod
import server.agents.codex_adapter as codex_mod
import server.agents.gemini_adapter as gemini_mod
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

    def test_find_claude_honors_configured_path(self, monkeypatch):
        configured = "/opt/bullpen/bin/claude"
        monkeypatch.setenv("BULLPEN_CLAUDE_PATH", configured)
        monkeypatch.setattr(claude_mod, "_is_executable", lambda path: path == configured)

        assert claude_mod._find_claude() == configured

    def test_unavailable_message_mentions_configured_bad_path(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_CLAUDE_PATH", "/missing/claude")
        msg = ClaudeAdapter().unavailable_message()
        assert "BULLPEN_CLAUDE_PATH" in msg
        assert "/missing/claude" in msg

    def test_mcp_config_uses_loopback_for_wildcard_host(self, tmp_workspace):
        adapter = ClaudeAdapter()
        bp_dir = os.path.join(tmp_workspace, ".bullpen")
        os.makedirs(bp_dir, exist_ok=True)
        with open(os.path.join(bp_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server_host": "0.0.0.0", "server_port": 5050}, f)

        cfg_path = adapter._mcp_config(bp_dir)
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            args = cfg["mcpServers"]["bullpen"]["args"]
            host = args[args.index("--host") + 1]
            assert host == "127.0.0.1"
        finally:
            if os.path.exists(cfg_path):
                os.unlink(cfg_path)

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

    def test_build_argv(self, monkeypatch):
        monkeypatch.delenv("BULLPEN_CODEX_SANDBOX", raising=False)
        adapter = CodexAdapter()
        argv = adapter.build_argv("test prompt", "o4-mini", "/workspace")
        assert any("codex" in arg for arg in argv)
        assert "exec" in argv
        assert "--model" in argv
        assert "o4-mini" in argv
        assert "--full-auto" in argv
        assert "--skip-git-repo-check" in argv
        assert "-" in argv
        assert "--approval-mode" not in argv
        assert "--quiet" not in argv

    def test_build_argv_can_disable_nested_sandbox(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_CODEX_SANDBOX", "none")
        adapter = CodexAdapter()
        argv = adapter.build_argv("test prompt", "gpt-5.4", "/workspace")

        assert "--dangerously-bypass-approvals-and-sandbox" in argv
        assert "--full-auto" not in argv

    def test_find_codex_checks_app_bundle_when_not_on_path(self, monkeypatch):
        app_bin = "/Applications/Codex.app/Contents/Resources/codex"
        monkeypatch.delenv("BULLPEN_CODEX_PATH", raising=False)
        monkeypatch.setattr(codex_mod.shutil, "which", lambda name: None)
        monkeypatch.setattr(codex_mod, "_CODEX_SEARCH_PATHS", [app_bin])
        monkeypatch.setattr(codex_mod, "_is_executable", lambda path: path == app_bin)

        assert codex_mod._find_codex() == app_bin

    def test_find_codex_honors_configured_path(self, monkeypatch):
        configured = "/opt/bullpen/bin/codex"
        monkeypatch.setenv("BULLPEN_CODEX_PATH", configured)
        monkeypatch.setattr(codex_mod, "_is_executable", lambda path: path == configured)

        assert codex_mod._find_codex() == configured

    def test_unavailable_message_mentions_configured_bad_path(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_CODEX_PATH", "/missing/codex")
        msg = CodexAdapter().unavailable_message()
        assert "BULLPEN_CODEX_PATH" in msg
        assert "/missing/codex" in msg

    def test_parse_success_falls_back_to_stderr_when_stdout_empty(self):
        adapter = CodexAdapter()
        result = adapter.parse_output("", "assistant reply from stderr", 0)
        assert result["success"] is True
        assert result["output"] == "assistant reply from stderr"
        assert result["error"] is None

    def test_build_argv_with_bp_dir_includes_mcp_overrides(self, tmp_workspace):
        adapter = CodexAdapter()
        bp_dir = os.path.join(tmp_workspace, ".bullpen")
        os.makedirs(bp_dir, exist_ok=True)
        with open(os.path.join(bp_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server_host": "0.0.0.0", "server_port": 5050}, f)

        argv = adapter.build_argv("test prompt", "gpt-5.3-codex", "/workspace", bp_dir=bp_dir)
        joined = " ".join(argv)
        assert "mcp_servers.bullpen.command=" in joined
        assert "mcp_servers.bullpen.args=" in joined
        assert "mcp_servers.bullpen.env.PYTHONPATH=" in joined
        assert "mcp_servers.bullpen.cwd=" in joined
        assert "mcp_servers.bullpen.tool_timeout_sec=120" in joined
        assert "--host" in joined
        assert "127.0.0.1" in joined
        assert os.path.abspath(bp_dir) in joined

    def test_format_stream_line_passthrough_non_json(self):
        adapter = CodexAdapter()
        assert adapter.format_stream_line("hello\n") == "hello"

    def test_format_stream_line_agent_message(self):
        adapter = CodexAdapter()
        line = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Done."}})
        assert adapter.format_stream_line(line) == "Done."

    def test_format_stream_line_command(self):
        adapter = CodexAdapter()
        line = json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "ls -la"}})
        assert adapter.format_stream_line(line) == "$ ls -la"

    def test_format_stream_line_skips_turn_events(self):
        adapter = CodexAdapter()
        line = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100}})
        assert adapter.format_stream_line(line) is None

    def test_parse_output_extracts_usage(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "All done."}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 500, "output_tokens": 120}}),
        ]
        result = adapter.parse_output("\n".join(lines), "", 0)
        assert result["success"] is True
        assert result["output"] == "All done."
        assert result["usage"]["input_tokens"] == 500
        assert result["usage"]["output_tokens"] == 120

    def test_parse_output_accumulates_multi_turn_usage(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 300, "output_tokens": 50}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Step 2."}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 400, "output_tokens": 80}}),
        ]
        result = adapter.parse_output("\n".join(lines), "", 0)
        assert result["usage"]["input_tokens"] == 700
        assert result["usage"]["output_tokens"] == 130

    def test_parse_output_error_preserves_usage(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 30}}),
            json.dumps({"type": "turn.failed", "error": {"message": "Rate limited"}}),
        ]
        result = adapter.parse_output("\n".join(lines), "", 1)
        assert result["success"] is False
        assert result["error"] == "Rate limited"
        assert result["usage"]["input_tokens"] == 200

    def test_parse_output_extracts_token_count_event(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps({
                "type": "token_count",
                "input_tokens": 120,
                "cached_input_tokens": 30,
                "output_tokens": 45,
                "reasoning_output_tokens": 10,
                "total_tokens": 205,
            }),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Done."}}),
        ]
        result = adapter.parse_output("\n".join(lines), "", 0)
        assert result["success"] is True
        assert result["output"] == "Done."
        assert result["usage"]["input_tokens"] == 120
        assert result["usage"]["cached_input_tokens"] == 30
        assert result["usage"]["output_tokens"] == 45
        assert result["usage"]["reasoning_output_tokens"] == 10
        assert result["usage"]["total_tokens"] == 205

    def test_parse_output_does_not_double_count_token_count_with_turn_completed(self):
        adapter = CodexAdapter()
        lines = [
            json.dumps({
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 30,
                        "output_tokens": 45,
                        "reasoning_output_tokens": 10,
                        "total_tokens": 205,
                    },
                },
            }),
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 120,
                    "cached_input_tokens": 30,
                    "output_tokens": 45,
                    "reasoning_output_tokens": 10,
                    "total_tokens": 205,
                },
            }),
        ]
        result = adapter.parse_output("\n".join(lines), "", 0)
        assert result["success"] is True
        assert result["usage"]["input_tokens"] == 120
        assert result["usage"]["cached_input_tokens"] == 30
        assert result["usage"]["output_tokens"] == 45
        assert result["usage"]["reasoning_output_tokens"] == 10
        assert result["usage"]["total_tokens"] == 205


class TestGeminiAdapter:
    def test_name(self):
        adapter = GeminiAdapter()
        assert adapter.name == "gemini"

    def test_build_argv(self):
        adapter = GeminiAdapter()
        argv = adapter.build_argv("test prompt", "gemini-2.5-pro", "/workspace")
        assert any("gemini" in arg for arg in argv)
        assert "--model" in argv
        assert "gemini-2.5-pro" in argv
        assert "--output-format" in argv
        assert "stream-json" in argv
        assert "--approval-mode" in argv
        assert "yolo" in argv
        assert "--prompt" in argv
        assert "test prompt" in argv
        assert "" not in argv

    def test_gemini_prompt_is_not_written_to_stdin(self):
        adapter = GeminiAdapter()
        assert adapter.prompt_via_stdin() is False

    def test_find_gemini_honors_configured_path(self, monkeypatch):
        configured = "/opt/bullpen/bin/gemini"
        monkeypatch.setenv("BULLPEN_GEMINI_PATH", configured)
        monkeypatch.setattr(gemini_mod, "_is_executable", lambda path: path == configured)

        assert gemini_mod._find_gemini() == configured

    def test_unavailable_message_mentions_configured_bad_path(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_GEMINI_PATH", "/missing/gemini")
        msg = GeminiAdapter().unavailable_message()
        assert "BULLPEN_GEMINI_PATH" in msg
        assert "/missing/gemini" in msg

    def test_format_stream_line_text_json(self):
        adapter = GeminiAdapter()
        line = json.dumps({"type": "message", "text": "hello from gemini"})
        assert adapter.format_stream_line(line) == "hello from gemini"

    def test_format_stream_line_response_stats_json(self):
        adapter = GeminiAdapter()
        line = json.dumps({
            "session_id": "6746315d-4574-495a-a0ea-229bb8c43d09",
            "response": "Aloha. How can I help you today?",
            "stats": {
                "models": {
                    "gemini-2.5-flash": {
                        "tokens": {
                            "input": 9058,
                            "prompt": 9058,
                            "candidates": 10,
                            "total": 9111,
                            "cached": 0,
                            "thoughts": 43,
                            "tool": 0,
                        }
                    }
                }
            },
            "tools": {"totalCalls": 0},
            "files": {"totalLinesAdded": 0, "totalLinesRemoved": 0},
        })
        assert adapter.format_stream_line(line) == "Aloha. How can I help you today?"

    def test_format_stream_line_skips_echoed_user_message(self):
        adapter = GeminiAdapter()
        line = json.dumps({
            "type": "message",
            "role": "user",
            "content": "Human: Aloha",
        })
        assert adapter.format_stream_line(line) is None

    def test_format_stream_line_assistant_stream_content(self):
        adapter = GeminiAdapter()
        line = json.dumps({
            "type": "message",
            "role": "assistant",
            "content": "Aloha",
            "delta": True,
        })
        assert adapter.format_stream_line(line) == "Aloha"

    def test_format_stream_line_skips_tool_events(self):
        adapter = GeminiAdapter()
        tool_use = json.dumps({
            "type": "tool_use",
            "tool_name": "google_web_search",
            "parameters": {"query": "UTC offset of Perth, AU"},
        })
        tool_result = json.dumps({
            "type": "tool_result",
            "status": "success",
            "output": "Search results returned.",
        })
        assert adapter.format_stream_line(tool_use) is None
        assert adapter.format_stream_line(tool_result) is None

    def test_parse_output_json_result_with_usage(self):
        adapter = GeminiAdapter()
        stdout = "\n".join([
            json.dumps({"type": "message", "text": "partial"}),
            json.dumps({
                "type": "result",
                "is_error": False,
                "result": "done",
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            }),
        ])
        result = adapter.parse_output(stdout, "", 0)
        assert result["success"] is True
        assert result["output"] == "done"
        assert result["usage"]["input_tokens"] == 10
        assert result["usage"]["output_tokens"] == 4

    def test_parse_output_plain_text_fallback(self):
        adapter = GeminiAdapter()
        result = adapter.parse_output("line 1\nline 2\n", "", 0)
        assert result["success"] is True
        assert result["output"] == "line 1\nline 2"

    def test_parse_output_response_stats_json(self):
        adapter = GeminiAdapter()
        stdout = json.dumps({
            "session_id": "6746315d-4574-495a-a0ea-229bb8c43d09",
            "response": "Aloha. How can I help you today?",
            "stats": {
                "models": {
                    "gemini-2.5-flash": {
                        "tokens": {
                            "input": 9058,
                            "prompt": 9058,
                            "candidates": 10,
                            "total": 9111,
                            "cached": 0,
                            "thoughts": 43,
                            "tool": 0,
                        }
                    }
                }
            },
            "tools": {"totalCalls": 0},
            "files": {"totalLinesAdded": 0, "totalLinesRemoved": 0},
        })
        result = adapter.parse_output(stdout, "", 0)
        assert result["success"] is True
        assert result["output"] == "Aloha. How can I help you today?"
        assert result["usage"]["input_tokens"] == 9058
        assert result["usage"]["output_tokens"] == 53
        assert result["usage"]["reasoning_output_tokens"] == 43
        assert result["usage"]["total_tokens"] == 9111

    def test_parse_output_stream_json_skips_user_echo_and_keeps_usage(self):
        adapter = GeminiAdapter()
        stdout = "\n".join([
            json.dumps({
                "type": "init",
                "session_id": "s1",
                "model": "gemini-2.5-flash",
            }),
            json.dumps({
                "type": "message",
                "role": "user",
                "content": "Human: Aloha",
            }),
            json.dumps({
                "type": "message",
                "role": "assistant",
                "content": "Aloha",
                "delta": True,
            }),
            json.dumps({
                "type": "result",
                "status": "success",
                "stats": {
                    "total_tokens": 6812,
                    "input_tokens": 6791,
                    "output_tokens": 2,
                    "cached": 0,
                    "models": {
                        "gemini-2.5-flash": {
                            "total_tokens": 6812,
                            "input_tokens": 6791,
                            "output_tokens": 2,
                            "cached": 0,
                        }
                    },
                },
            }),
        ])
        result = adapter.parse_output(stdout, "", 0)
        assert result["success"] is True
        assert result["output"] == "Aloha"
        assert "Human: Aloha" not in result["output"]
        assert result["usage"]["input_tokens"] == 6791
        assert result["usage"]["output_tokens"] == 2
        assert result["usage"]["total_tokens"] == 6812

    def test_parse_output_stream_json_skips_tool_events(self):
        adapter = GeminiAdapter()
        stdout = "\n".join([
            json.dumps({
                "type": "tool_use",
                "tool_name": "google_web_search",
                "parameters": {"query": "UTC offset of Perth, AU"},
            }),
            json.dumps({
                "type": "tool_result",
                "status": "success",
                "output": "Search results returned.",
            }),
            json.dumps({
                "type": "message",
                "role": "assistant",
                "content": "The UTC offset of Perth is +8 hours.",
            }),
        ])
        result = adapter.parse_output(stdout, "", 0)
        assert result["success"] is True
        assert result["output"] == "The UTC offset of Perth is +8 hours."
        assert "tool_use" not in result["output"]
        assert "tool_result" not in result["output"]


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

    def test_get_gemini(self):
        adapter = get_adapter("gemini")
        assert adapter is not None
        assert adapter.name == "gemini"

    def test_get_nonexistent(self):
        assert get_adapter("nonexistent") is None

    def test_register_custom(self):
        mock = MockAdapter()
        register_adapter("mock", mock)
        assert get_adapter("mock") is mock
        assert "mock" in list_adapters()
