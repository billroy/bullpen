"""Codex CLI adapter."""

import json
import os
import shutil
import sys

from server.agents.base import AgentAdapter

_CODEX_SEARCH_PATHS = [
    os.path.expanduser("~/.local/bin/codex"),
    "/usr/local/bin/codex",
    "/opt/homebrew/bin/codex",
]


def _find_codex():
    """Find the codex binary on PATH or common install locations."""
    found = shutil.which("codex")
    if found:
        return found
    for path in _CODEX_SEARCH_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class CodexAdapter(AgentAdapter):

    @property
    def name(self):
        return "codex"

    def available(self):
        return _find_codex() is not None

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        codex_bin = _find_codex() or "codex"
        argv = [
            codex_bin,
            "exec",
            "--model", model,
            "--full-auto",
        ]
        if bp_dir:
            argv.extend(self._mcp_overrides(bp_dir))
        argv.append("-")  # Read prompt from stdin
        # Prompt is delivered via stdin
        return argv

    def _mcp_overrides(self, bp_dir):
        """Return -c overrides to register the bullpen MCP server for this run."""
        server_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_tools.py")
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from server.persistence import read_json

        bp_config = read_json(os.path.join(bp_dir, "config.json"))
        host = bp_config.get("server_host", "127.0.0.1")
        if host == "0.0.0.0":
            host = "127.0.0.1"
        port = str(bp_config.get("server_port", 5000))
        args = [server_script, "--bp-dir", bp_dir, "--host", host, "--port", port]

        return [
            "-c", f"mcp_servers.bullpen.command={json.dumps(sys.executable)}",
            "-c", f"mcp_servers.bullpen.args={json.dumps(args)}",
            "-c", f"mcp_servers.bullpen.env.PYTHONPATH={json.dumps(project_root)}",
        ]

    def format_stream_line(self, line):
        """Pass through non-empty lines for Live Agent chat streaming."""
        line = line.rstrip("\n")
        return line if line else None

    def parse_output(self, stdout, stderr, exit_code):
        if exit_code == 0:
            output = stdout.strip()
            if not output and stderr:
                output = stderr.strip()
            return {
                "success": True,
                "output": output,
                "error": None,
            }
        return {
            "success": False,
            "output": stdout.strip() if stdout else "",
            "error": stderr.strip() if stderr else f"Exit code {exit_code}",
        }
