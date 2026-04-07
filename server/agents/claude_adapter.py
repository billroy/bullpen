"""Claude CLI adapter."""

import shutil

from server.agents.base import AgentAdapter


class ClaudeAdapter(AgentAdapter):

    @property
    def name(self):
        return "claude"

    def available(self):
        return shutil.which("claude") is not None

    def list_models(self):
        return ["haiku", "sonnet", "opus"]

    def build_argv(self, prompt, model, workspace):
        argv = [
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--model", model,
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
