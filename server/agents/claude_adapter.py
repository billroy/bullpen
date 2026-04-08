"""Claude CLI adapter."""

import json
import os
import shutil
import sys
import tempfile

from server.agents.base import AgentAdapter

# Common install locations for claude CLI
_CLAUDE_SEARCH_PATHS = [
    os.path.expanduser("~/.local/bin/claude"),
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",
]


def _find_claude():
    """Find the claude binary on PATH or common install locations."""
    found = shutil.which("claude")
    if found:
        return found
    for path in _CLAUDE_SEARCH_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class ClaudeAdapter(AgentAdapter):

    @property
    def name(self):
        return "claude"

    def available(self):
        return _find_claude() is not None

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        claude_bin = _find_claude() or "claude"
        argv = [
            claude_bin,
            "--print",
            "--dangerously-skip-permissions",
            "--model", model,
        ]
        if bp_dir:
            config = self._mcp_config(bp_dir)
            argv.extend(["--mcp-config", config])
        # Prompt is delivered via stdin in _run_agent
        return argv

    def _mcp_config(self, bp_dir):
        """Generate a temporary MCP config file pointing to bullpen tools."""
        server_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_tools.py")
        # Read server host/port from config
        from server.persistence import read_json
        bp_config = read_json(os.path.join(bp_dir, "config.json"))
        host = bp_config.get("server_host", "127.0.0.1")
        port = str(bp_config.get("server_port", 5000))
        config = {
            "mcpServers": {
                "bullpen": {
                    "command": sys.executable,
                    "args": [server_script, "--bp-dir", bp_dir, "--host", host, "--port", port],
                }
            }
        }
        fd, path = tempfile.mkstemp(suffix=".json", prefix="bullpen-mcp-")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f)
        return path

    def parse_output(self, stdout, stderr, exit_code):
        if exit_code == 0:
            return {
                "success": True,
                "output": stdout.strip(),
                "error": None,
            }
        return {
            "success": False,
            "output": stdout.strip() if stdout else "",
            "error": stderr.strip() if stderr else f"Exit code {exit_code}",
        }
