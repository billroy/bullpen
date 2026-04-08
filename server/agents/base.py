"""AgentAdapter interface."""

from abc import ABC, abstractmethod


class AgentAdapter(ABC):
    """Abstract base class for agent CLI adapters."""

    @property
    @abstractmethod
    def name(self):
        """Agent name (e.g. 'claude', 'codex')."""
        ...

    @abstractmethod
    def available(self):
        """Return True if the agent CLI is available on this system."""
        ...

    @abstractmethod
    def build_argv(self, prompt, model, workspace, bp_dir=None):
        """Build command argv list for subprocess execution.

        Args:
            prompt: The full prompt text to send to the agent.
            model: The model name to use.
            workspace: The workspace directory path.
            bp_dir: The .bullpen directory path (for MCP tools).

        Returns:
            List of strings for subprocess argv.
        """
        ...

    @abstractmethod
    def parse_output(self, stdout, stderr, exit_code):
        """Parse agent output.

        Returns:
            dict with keys: success (bool), output (str), error (str or None)
        """
        ...

    def format_stream_line(self, line):
        """Convert a raw stdout line into display text for the focus view.

        Returns a string to display, or None to skip the line.
        Override in adapters that use structured output (e.g. stream-json).
        """
        return line.rstrip("\n")
