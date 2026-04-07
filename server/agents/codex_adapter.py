"""Codex CLI adapter."""

import shutil

from server.agents.base import AgentAdapter


class CodexAdapter(AgentAdapter):

    @property
    def name(self):
        return "codex"

    def available(self):
        return shutil.which("codex") is not None

    def list_models(self):
        return ["o3-mini", "o4-mini"]

    def build_argv(self, prompt, model, workspace):
        argv = [
            "codex",
            "--model", model,
            "--approval-mode", "full-auto",
            "--quiet",
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
