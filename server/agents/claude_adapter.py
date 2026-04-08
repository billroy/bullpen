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
            "--output-format", "stream-json",
            "--verbose",
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
        # Project root is parent of server/ — needed on PYTHONPATH so
        # mcp_tools.py can do `from server import tasks`
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # Read server host/port from config
        from server.persistence import read_json
        bp_config = read_json(os.path.join(bp_dir, "config.json"))
        host = bp_config.get("server_host", "127.0.0.1")
        if host == "0.0.0.0":
            # MCP helper is a local client and should connect via loopback.
            host = "127.0.0.1"
        port = str(bp_config.get("server_port", 5000))
        config = {
            "mcpServers": {
                "bullpen": {
                    "command": sys.executable,
                    "args": [server_script, "--bp-dir", bp_dir, "--host", host, "--port", port],
                    "env": {"PYTHONPATH": project_root},
                }
            }
        }
        fd, path = tempfile.mkstemp(suffix=".json", prefix="bullpen-mcp-")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f)
        return path

    def format_stream_line(self, line):
        """Extract display text from a stream-json line."""
        line = line.strip()
        if not line:
            return None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return line  # Pass through non-JSON lines as-is

        msg_type = obj.get("type")

        if msg_type == "assistant":
            parts = []
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input", {})
                    # Show a compact summary of the tool call
                    if name == "Bash":
                        parts.append(f"$ {inp.get('command', '')}")
                    elif name == "Edit":
                        parts.append(f"[Edit] {inp.get('file_path', '')}")
                    elif name == "Write":
                        parts.append(f"[Write] {inp.get('file_path', '')}")
                    elif name == "Read":
                        parts.append(f"[Read] {inp.get('file_path', '')}")
                    elif name in ("Glob", "Grep"):
                        parts.append(f"[{name}] {inp.get('pattern', '')}")
                    else:
                        parts.append(f"[{name}]")
            return "\n".join(parts) if parts else None

        if msg_type == "tool":
            # Tool output — show content
            content = obj.get("content", "")
            if isinstance(content, list):
                texts = [item.get("text", "") for item in content if isinstance(item, dict)]
                text = "\n".join(texts)
            else:
                text = str(content)
            # Truncate very long tool output for display
            if len(text) > 2000:
                text = text[:2000] + "\n[output truncated]"
            return text if text else None

        if msg_type == "result":
            return None  # Final result is handled by parse_output

        # Skip system, rate_limit_event, user echo, etc.
        return None

    def parse_output(self, stdout, stderr, exit_code):
        # In stream-json mode, stdout is multiple JSON lines.
        # The last meaningful line is type=result.
        result_text = ""
        is_error = False
        error_msg = None

        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") == "result":
                result_text = obj.get("result", "")
                is_error = obj.get("is_error", False)
                if is_error:
                    error_msg = result_text
                break

        # Fallback: if no result line found (e.g. crash), use raw stdout
        if not result_text and not is_error:
            # Try to extract assistant text from the stream
            for line in stdout.strip().splitlines():
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "assistant":
                        for block in obj.get("message", {}).get("content", []):
                            if block.get("type") == "text":
                                result_text += block["text"]
                except (json.JSONDecodeError, KeyError):
                    continue

        if exit_code != 0 and not is_error:
            return {
                "success": False,
                "output": result_text,
                "error": error_msg or stderr.strip() or f"Exit code {exit_code}",
            }

        if is_error:
            return {
                "success": False,
                "output": "",
                "error": error_msg or "Unknown error",
            }

        return {
            "success": True,
            "output": result_text.strip(),
            "error": None,
        }
