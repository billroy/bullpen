"""Claude CLI adapter."""

import os
import shutil

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

    def build_argv(self, prompt, model, workspace):
        claude_bin = _find_claude() or "claude"
        argv = [
            claude_bin,
            "--print",
            "--dangerously-skip-permissions",
            "--model", model,
        ]
        # Prompt is delivered via stdin in _run_agent
        return argv

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
