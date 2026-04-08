"""Codex CLI adapter."""

import os
import shutil

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
            "-",  # Read prompt from stdin
        ]
        # Prompt is delivered via stdin
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
