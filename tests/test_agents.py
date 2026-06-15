"""Tests for agent adapters."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from server.agents import get_adapter, register_adapter, list_adapters
from server.agents.claude_adapter import ClaudeAdapter
from server.agents.codex_adapter import CodexAdapter
from server.agents.antigravity_adapter import AntigravityAdapter
from server.agents.opencode_adapter import OpenCodeAdapter
import server.agents.antigravity_adapter as antigravity_mod
import server.agents.claude_adapter as claude_mod
import server.agents.codex_adapter as codex_mod
import server.agents.opencode_adapter as opencode_mod
from tests.conftest import MockAdapter


FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
        assert "--no-session-persistence" in argv
        assert "--setting-sources" in argv
        idx = argv.index("--setting-sources")
        assert argv[idx + 1] == "user"

    def test_find_claude_honors_configured_path(self, monkeypatch):
        configured = "/opt/bullpen/bin/claude"
        monkeypatch.setenv("BULLPEN_CLAUDE_PATH", configured)
        monkeypatch.setattr(claude_mod, "_is_executable", lambda path: path == configured)

        assert claude_mod._find_claude() == configured

    def test_available_requires_only_claude_executable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(claude_mod, "_find_claude", lambda: "/usr/local/bin/claude")

        assert ClaudeAdapter().available() is True

    def test_available_accepts_current_claude_oauth(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        credentials = home / ".claude" / ".credentials.json"
        credentials.parent.mkdir(parents=True)
        credentials.write_text('{"claudeAiOauth":{"accessToken":"token"}}', encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(claude_mod, "_find_claude", lambda: "/usr/local/bin/claude")

        assert ClaudeAdapter().available() is True

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

    def test_prepare_env_isolates_tmpdir_and_claude_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        home = tmp_path / "home"
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        credentials = claude_dir / ".credentials.json"
        credentials.write_text('{"claudeAiOauth":{"accessToken":"token"}}', encoding="utf-8")
        (claude_dir / "settings.json").write_text('{"hooks":{"Stop":[]}}', encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))

        env, cleanup_path = ClaudeAdapter().prepare_env("/workspace")
        try:
            assert cleanup_path.startswith(str(tmp_path))
            assert os.path.isdir(cleanup_path)
            assert env["TMPDIR"] == cleanup_path
            assert env["TMP"] == cleanup_path
            assert env["TEMP"] == cleanup_path
            assert env["CLAUDE_CODE_TMPDIR"] == cleanup_path
            assert env["CLAUDE_CONFIG_DIR"].startswith(cleanup_path)
            copied_credentials = os.path.join(env["CLAUDE_CONFIG_DIR"], ".credentials.json")
            assert os.path.isfile(copied_credentials)
            if os.path.isfile("/etc/ssl/certs/ca-certificates.crt"):
                assert env["SSL_CERT_FILE"] == "/etc/ssl/certs/ca-certificates.crt"
            if os.path.isdir("/etc/ssl/certs"):
                assert env["SSL_CERT_DIR"] == "/etc/ssl/certs"
            with open(copied_credentials, encoding="utf-8") as f:
                assert f.read() == '{"claudeAiOauth":{"accessToken":"token"}}'
            assert not os.path.exists(os.path.join(env["CLAUDE_CONFIG_DIR"], "settings.json"))
        finally:
            shutil.rmtree(cleanup_path, ignore_errors=True)

    def test_prepare_env_serializes_expired_oauth_refresh(self, monkeypatch, tmp_path):
        class FakeLock:
            def __init__(self):
                self.acquired = 0
                self.released = 0

            def acquire(self):
                self.acquired += 1

            def release(self):
                self.released += 1

        fake_lock = FakeLock()
        monkeypatch.setattr(claude_mod, "_CLAUDE_OAUTH_REFRESH_LOCK", fake_lock)
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        home = tmp_path / "home"
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        source_credentials = claude_dir / ".credentials.json"
        source_credentials.write_text(
            '{"claudeAiOauth":{"accessToken":"expired","expiresAt":1,"refreshToken":"r"}}',
            encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(home))

        env, cleanup_path = ClaudeAdapter().prepare_env("/workspace")
        try:
            assert fake_lock.acquired == 1
            assert env["BULLPEN_CLAUDE_REFRESH_LOCK_HELD"] == "1"

            config_dir = env["CLAUDE_CONFIG_DIR"]
            (Path(config_dir) / ".credentials.json").write_text(
                '{"claudeAiOauth":{"accessToken":"fresh","expiresAt":9999999999999,"refreshToken":"r"}}',
                encoding="utf-8",
            )
            ClaudeAdapter().finalize_env(env, cleanup_path)

            assert fake_lock.released == 1
            assert '"fresh"' in source_credentials.read_text(encoding="utf-8")
        finally:
            shutil.rmtree(cleanup_path, ignore_errors=True)

    def test_prepare_env_does_not_lock_current_oauth(self, monkeypatch, tmp_path):
        class FailLock:
            def acquire(self):
                raise AssertionError("current credentials should not acquire refresh lock")

        monkeypatch.setattr(claude_mod, "_CLAUDE_OAUTH_REFRESH_LOCK", FailLock())
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        home = tmp_path / "home"
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / ".credentials.json").write_text(
            '{"claudeAiOauth":{"accessToken":"current","expiresAt":9999999999999,"refreshToken":"r"}}',
            encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(home))

        env, cleanup_path = ClaudeAdapter().prepare_env("/workspace")
        try:
            assert "BULLPEN_CLAUDE_REFRESH_LOCK_HELD" not in env
        finally:
            shutil.rmtree(cleanup_path, ignore_errors=True)

    def test_prepare_env_prefers_credentials_file_over_parent_claude_token(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "stale-oauth-token")
        home = tmp_path / "home"
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / ".credentials.json").write_text(
            '{"claudeAiOauth":{"accessToken":"current","refreshToken":"r"}}',
            encoding="utf-8",
        )
        monkeypatch.setenv("HOME", str(home))

        env, cleanup_path = ClaudeAdapter().prepare_env("/workspace")
        try:
            assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
            assert os.path.isfile(os.path.join(env["CLAUDE_CONFIG_DIR"], ".credentials.json"))
        finally:
            shutil.rmtree(cleanup_path, ignore_errors=True)

    def test_prepare_env_does_not_set_claude_config_dir_without_credentials_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        env, cleanup_path = ClaudeAdapter().prepare_env("/workspace")
        try:
            assert "CLAUDE_CONFIG_DIR" not in env
        finally:
            shutil.rmtree(cleanup_path, ignore_errors=True)

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

    def test_format_stream_line_surfaces_api_retry(self):
        adapter = ClaudeAdapter()
        line = json.dumps({
            "type": "system",
            "subtype": "api_retry",
            "attempt": 3,
            "max_retries": 10,
            "error_status": 429,
            "error": "rate_limit_error",
        })
        out = adapter.format_stream_line(line)
        assert out is not None
        assert "api_retry" in out
        assert "3/10" in out
        assert "429" in out
        assert "rate_limit_error" in out

    def test_finalize_env_syncs_refreshed_credentials_back(self, tmp_path, monkeypatch):
        from server.agents import claude_adapter as ca

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_creds = source_dir / ".credentials.json"
        source_creds.write_text('{"claudeAiOauth":{"accessToken":"old","refreshToken":"r"}}', encoding="utf-8")

        run_tmp = tmp_path / "run"
        run_tmp.mkdir()
        config_dir = run_tmp / "claude-config"
        config_dir.mkdir()
        # Simulate claude having refreshed the token mid-run.
        (config_dir / ".credentials.json").write_text(
            '{"claudeAiOauth":{"accessToken":"NEW","refreshToken":"r"}}', encoding="utf-8"
        )

        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(source_dir))
        adapter = ClaudeAdapter()
        adapter.finalize_env({"CLAUDE_CONFIG_DIR": str(config_dir)}, str(run_tmp))

        assert '"NEW"' in source_creds.read_text(encoding="utf-8")

    def test_finalize_env_no_op_when_credentials_unchanged(self, tmp_path, monkeypatch):
        from server.agents import claude_adapter as ca

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_creds = source_dir / ".credentials.json"
        payload = '{"claudeAiOauth":{"accessToken":"same","refreshToken":"r"}}'
        source_creds.write_text(payload, encoding="utf-8")
        original_mtime = source_creds.stat().st_mtime

        run_tmp = tmp_path / "run"
        run_tmp.mkdir()
        config_dir = run_tmp / "claude-config"
        config_dir.mkdir()
        (config_dir / ".credentials.json").write_text(payload, encoding="utf-8")

        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(source_dir))
        adapter = ClaudeAdapter()
        adapter.finalize_env({"CLAUDE_CONFIG_DIR": str(config_dir)}, str(run_tmp))

        assert source_creds.stat().st_mtime == original_mtime

    def test_finalize_env_does_not_sync_poisoned_expired_credentials(self, tmp_path, monkeypatch):
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_creds = source_dir / ".credentials.json"
        source_payload = '{"claudeAiOauth":{"accessToken":"old","expiresAt":1,"refreshToken":"r"}}'
        source_creds.write_text(source_payload, encoding="utf-8")

        run_tmp = tmp_path / "run"
        run_tmp.mkdir()
        config_dir = run_tmp / "claude-config"
        config_dir.mkdir()
        (config_dir / ".credentials.json").write_text(
            '{"claudeAiOauth":{"accessToken":"bad","expiresAt":1,"refreshToken":""}}',
            encoding="utf-8",
        )

        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(source_dir))
        ClaudeAdapter().finalize_env({"CLAUDE_CONFIG_DIR": str(config_dir)}, str(run_tmp))

        assert source_creds.read_text(encoding="utf-8") == source_payload

    def test_finalize_env_preserves_source_refresh_when_target_only_refreshes_access(self, tmp_path, monkeypatch):
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_creds = source_dir / ".credentials.json"
        source_creds.write_text(
            '{"claudeAiOauth":{"accessToken":"old","expiresAt":1,"refreshToken":"keep"}}',
            encoding="utf-8",
        )

        run_tmp = tmp_path / "run"
        run_tmp.mkdir()
        config_dir = run_tmp / "claude-config"
        config_dir.mkdir()
        (config_dir / ".credentials.json").write_text(
            '{"claudeAiOauth":{"accessToken":"fresh","expiresAt":9999999999999,"refreshToken":""}}',
            encoding="utf-8",
        )

        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(source_dir))
        ClaudeAdapter().finalize_env({"CLAUDE_CONFIG_DIR": str(config_dir)}, str(run_tmp))

        data = json.loads(source_creds.read_text(encoding="utf-8"))
        oauth = data["claudeAiOauth"]
        assert oauth["accessToken"] == "fresh"
        assert oauth["refreshToken"] == "keep"


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
        assert "--sandbox" in argv
        assert "workspace-write" in argv
        assert "approval_policy=\"never\"" in argv
        assert "--ask-for-approval" not in argv
        assert "--full-auto" not in argv
        assert "--skip-git-repo-check" in argv
        assert "-" in argv
        assert "--approval-mode" not in argv
        assert "--quiet" not in argv

    def test_build_argv_honors_configured_sandbox_mode(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_CODEX_SANDBOX", "read-only")
        adapter = CodexAdapter()
        argv = adapter.build_argv("test prompt", "gpt-5.4", "/workspace")

        assert "--sandbox" in argv
        assert "read-only" in argv
        assert "--full-auto" not in argv
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv

    def test_build_argv_can_disable_nested_sandbox(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_CODEX_SANDBOX", "none")
        adapter = CodexAdapter()
        argv = adapter.build_argv("test prompt", "gpt-5.4", "/workspace")

        assert "--dangerously-bypass-approvals-and-sandbox" in argv
        assert "--full-auto" not in argv
        assert "--sandbox" not in argv

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
        assert "mcp_servers.bullpen.default_tools_approval_mode=\"approve\"" in joined
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


class TestAntigravityAdapter:
    def test_name(self):
        adapter = AntigravityAdapter()
        assert adapter.name == "antigravity"

    def test_find_agy_honors_configured_path(self, monkeypatch):
        configured = "/opt/bullpen/bin/agy"
        monkeypatch.setenv("BULLPEN_ANTIGRAVITY_PATH", configured)
        monkeypatch.setattr(antigravity_mod, "_is_executable", lambda path: path == configured)

        assert antigravity_mod._find_agy() == configured

    def test_unavailable_message_mentions_configured_bad_path(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_ANTIGRAVITY_PATH", "/missing/agy")
        msg = AntigravityAdapter().unavailable_message()
        assert "BULLPEN_ANTIGRAVITY_PATH" in msg
        assert "/missing/agy" in msg

    def test_build_argv_uses_print_mode_and_prompt_flag(self, monkeypatch):
        monkeypatch.setattr(antigravity_mod, "_find_agy", lambda: "/usr/local/bin/agy")

        adapter = AntigravityAdapter()
        argv = adapter.build_argv("test prompt", "Gemini 3.5 Flash (Medium)", "/workspace")

        assert argv[:3] == ["/usr/local/bin/agy", "--print-timeout", "10m"]
        assert "--model" in argv
        assert "Gemini 3.5 Flash (Medium)" in argv
        assert "--print" in argv
        assert "test prompt" in argv
        assert adapter.prompt_via_stdin() is False

    def test_mcp_config_uses_loopback_for_wildcard_host(self, tmp_workspace):
        adapter = AntigravityAdapter()
        bp_dir = os.path.join(tmp_workspace, ".bullpen")
        os.makedirs(bp_dir, exist_ok=True)
        with open(os.path.join(bp_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server_host": "0.0.0.0", "server_port": 5050}, f)

        cfg = adapter._mcp_config(bp_dir)
        server = cfg["mcpServers"]["bullpen"]
        assert server["command"] == sys.executable
        assert server["args"][0].endswith(os.path.join("server", "mcp_tools.py"))
        assert "--bp-dir" in server["args"]
        assert os.path.abspath(bp_dir) in server["args"]
        assert "--host" in server["args"]
        assert "127.0.0.1" in server["args"]
        assert "--port" in server["args"]
        assert "5050" in server["args"]
        assert "update_ticket" in server["enabledTools"]
        assert server["env"]["PYTHONPATH"] == os.getcwd()

    def test_prepare_env_installs_unique_plugin_and_finalize_uninstalls(self, tmp_workspace, monkeypatch):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((list(argv), kwargs))
            class Completed:
                returncode = 0
                stdout = "ok"
                stderr = ""
            return Completed()

        monkeypatch.setattr(antigravity_mod, "_find_agy", lambda: "/usr/local/bin/agy")
        monkeypatch.setattr(antigravity_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(antigravity_mod.secrets, "token_hex", lambda _n: "abc123ef")

        bp_dir = os.path.join(tmp_workspace, ".bullpen")
        os.makedirs(bp_dir, exist_ok=True)
        with open(os.path.join(bp_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server_host": "127.0.0.1", "server_port": 5050}, f)

        adapter = AntigravityAdapter()
        env, cleanup_path = adapter.prepare_env(tmp_workspace, bp_dir=bp_dir, task_id="ticket-1")
        try:
            plugin_name = env["BULLPEN_ANTIGRAVITY_PLUGIN_NAME"]
            assert plugin_name.startswith("bullpen-antigravity-runtime-")
            plugin_dir = env["BULLPEN_ANTIGRAVITY_PLUGIN_DIR"]
            plugin_json = json.loads(Path(plugin_dir, "plugin.json").read_text(encoding="utf-8"))
            mcp_json = json.loads(Path(plugin_dir, "mcp_config.json").read_text(encoding="utf-8"))
            assert plugin_json["name"] == plugin_name
            assert "bullpen" in mcp_json["mcpServers"]
            assert calls[0][0] == ["/usr/local/bin/agy", "plugin", "install", plugin_dir]

            adapter.finalize_env(env, cleanup_path)
            assert calls[-1][0] == ["/usr/local/bin/agy", "plugin", "uninstall", plugin_name]
        finally:
            shutil.rmtree(cleanup_path, ignore_errors=True)

    def test_parse_output_plain_text(self):
        adapter = AntigravityAdapter()
        result = adapter.parse_output("line 1\nline 2\n", "", 0)
        assert result == {"success": True, "output": "line 1\nline 2", "error": None, "usage": {}}

    def test_parse_output_failure_uses_stderr(self):
        adapter = AntigravityAdapter()
        result = adapter.parse_output("partial", "auth failed", 1)
        assert result["success"] is False
        assert result["output"] == "partial"
        assert result["error"] == "auth failed"
        assert result["usage"] == {}


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


class TestOpenCodeAdapter:
    def test_name(self):
        adapter = OpenCodeAdapter()
        assert adapter.name == "opencode"

    def test_find_opencode_honors_configured_path(self, monkeypatch):
        configured = "/opt/bullpen/bin/opencode"
        monkeypatch.setenv("BULLPEN_OPENCODE_PATH", configured)
        monkeypatch.setattr(opencode_mod, "_is_executable", lambda path: path == configured)

        assert opencode_mod._find_opencode() == configured

    def test_unavailable_message_mentions_configured_bad_path(self, monkeypatch):
        monkeypatch.setenv("BULLPEN_OPENCODE_PATH", "/missing/opencode")
        msg = OpenCodeAdapter().unavailable_message()
        assert "BULLPEN_OPENCODE_PATH" in msg
        assert "/missing/opencode" in msg

    def test_build_argv_uses_json_run_and_stdin_prompt(self, monkeypatch):
        monkeypatch.setattr(opencode_mod, "_find_opencode", lambda: "/usr/local/bin/opencode")

        adapter = OpenCodeAdapter()
        argv = adapter.build_argv("test prompt", "opencode/north-mini-code-free", "/workspace")

        assert argv[:4] == ["/usr/local/bin/opencode", "run", "--format", "json"]
        assert "--model" in argv
        assert "opencode/north-mini-code-free" in argv
        assert "test prompt" not in argv
        assert adapter.prompt_via_stdin() is True

    def test_prepare_env_writes_opencode_mcp_config(self, tmp_workspace):
        adapter = OpenCodeAdapter()
        bp_dir = os.path.join(tmp_workspace, ".bullpen")
        os.makedirs(bp_dir, exist_ok=True)
        with open(os.path.join(bp_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server_host": "0.0.0.0", "server_port": 5050}, f)

        env, cleanup_path = adapter.prepare_env(tmp_workspace, bp_dir=bp_dir)
        try:
            assert env["TMPDIR"] == cleanup_path
            config_path = env["OPENCODE_CONFIG"]
            cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
            server = cfg["mcp"]["bullpen"]
            assert server["type"] == "local"
            assert server["enabled"] is True
            assert server["command"][0] == sys.executable
            assert server["command"][1].endswith(os.path.join("server", "mcp_tools.py"))
            assert "--bp-dir" in server["command"]
            assert os.path.abspath(bp_dir) in server["command"]
            assert "--host" in server["command"]
            assert "127.0.0.1" in server["command"]
            assert "--port" in server["command"]
            assert "5050" in server["command"]
        finally:
            shutil.rmtree(cleanup_path, ignore_errors=True)

    def test_format_stream_line_text_event(self):
        adapter = OpenCodeAdapter()
        line = json.dumps({"type": "text", "part": {"text": "OK"}})
        assert adapter.format_stream_line(line) == "OK"

    def test_format_stream_line_skips_step_finish(self):
        adapter = OpenCodeAdapter()
        line = json.dumps({"type": "step_finish", "part": {"tokens": {"total": 1}}})
        assert adapter.format_stream_line(line) is None

    def test_format_stream_line_error_event(self):
        adapter = OpenCodeAdapter()
        line = json.dumps({"type": "error", "error": {"data": {"message": "No endpoints found"}}})
        assert adapter.format_stream_line(line) == "No endpoints found"

    def test_parse_output_success_fixture(self):
        adapter = OpenCodeAdapter()
        stdout = (FIXTURES_DIR / "opencode" / "run_success_text.jsonl").read_text(encoding="utf-8")

        result = adapter.parse_output(stdout, "", 0)

        assert result["success"] is True
        assert result["output"] == "OK"
        assert result["error"] is None
        assert result["usage"]["input_tokens"] == 7754
        assert result["usage"]["output_tokens"] == 1
        assert result["usage"]["reasoning_output_tokens"] == 85
        assert result["usage"]["cached_input_tokens"] == 0
        assert result["usage"]["total_tokens"] == 7840

    def test_parse_output_error_fixture(self):
        adapter = OpenCodeAdapter()
        stdout = (FIXTURES_DIR / "opencode" / "run_provider_error.jsonl").read_text(encoding="utf-8")

        result = adapter.parse_output(stdout, "", 1)

        assert result["success"] is False
        assert "No endpoints found" in result["error"]


class TestRegistry:
    def test_get_claude(self):
        adapter = get_adapter("claude")
        assert adapter is not None
        assert adapter.name == "claude"

    def test_get_codex(self):
        adapter = get_adapter("codex")
        assert adapter is not None
        assert adapter.name == "codex"

    def test_get_antigravity(self):
        adapter = get_adapter("antigravity")
        assert adapter is not None
        assert adapter.name == "antigravity"

    def test_gemini_is_not_registered(self):
        assert get_adapter("gemini") is None

    def test_get_opencode(self):
        adapter = get_adapter("opencode")
        assert adapter is not None
        assert adapter.name == "opencode"

    def test_get_nonexistent(self):
        assert get_adapter("nonexistent") is None

    def test_register_custom(self):
        mock = MockAdapter()
        register_adapter("mock", mock)
        assert get_adapter("mock") is mock
        assert "mock" in list_adapters()
