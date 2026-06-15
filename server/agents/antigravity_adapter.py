"""Google Antigravity CLI adapter."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile

from server.agents.base import AgentAdapter


if sys.platform == "win32":
    _AGY_SEARCH_PATHS = [
        os.path.expanduser(r"~\AppData\Local\Programs\antigravity\agy.cmd"),
        os.path.expanduser(r"~\AppData\Roaming\npm\agy.cmd"),
    ]
else:
    _AGY_SEARCH_PATHS = [
        os.path.expanduser("~/.local/bin/agy"),
        "/usr/local/bin/agy",
        "/opt/homebrew/bin/agy",
    ]


_PLUGIN_ENV = "BULLPEN_ANTIGRAVITY_PLUGIN_NAME"
_PLUGIN_DIR_ENV = "BULLPEN_ANTIGRAVITY_PLUGIN_DIR"


def _is_executable(path):
    """Check if a file is executable."""
    if not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        return os.path.splitext(path)[1].lower() in {".exe", ".cmd", ".bat", ".com"}
    return os.access(path, os.X_OK)


def _find_agy():
    """Find the Antigravity CLI binary on PATH or common install locations."""
    configured = os.environ.get("BULLPEN_ANTIGRAVITY_PATH")
    if configured and _is_executable(os.path.expanduser(configured)):
        return os.path.expanduser(configured)

    found = shutil.which("agy")
    if found:
        return found
    for path in _AGY_SEARCH_PATHS:
        if _is_executable(path):
            return path
    return None


def _run_tmpdir():
    candidates = [os.environ.get("TMPDIR"), tempfile.gettempdir()]
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            os.makedirs(candidate, exist_ok=True)
            return tempfile.mkdtemp(prefix="bullpen-antigravity-", dir=candidate)
        except OSError:
            continue
    return tempfile.mkdtemp(prefix="bullpen-antigravity-")


class AntigravityAdapter(AgentAdapter):
    @property
    def name(self):
        return "antigravity"

    def available(self):
        return _find_agy() is not None

    def unavailable_message(self):
        configured = os.environ.get("BULLPEN_ANTIGRAVITY_PATH")
        if configured:
            return (
                "Antigravity CLI is not available. BULLPEN_ANTIGRAVITY_PATH is set to "
                f"{configured!r}, but that file was not found or is not executable."
            )
        return (
            "Antigravity CLI is not available. Install Google Antigravity CLI, "
            "authenticate with agy, or set BULLPEN_ANTIGRAVITY_PATH to the agy executable."
        )

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        agy_bin = _find_agy() or "agy"
        argv = [
            agy_bin,
            "--print-timeout",
            "10m",
        ]
        if model:
            argv.extend(["--model", model])
        argv.extend(["--print", prompt])
        return argv

    def prepare_env(self, workspace, bp_dir=None, task_id=None):
        if not bp_dir:
            return None

        run_tmp = _run_tmpdir()
        plugin_name = self._plugin_name(task_id)
        plugin_dir = os.path.join(run_tmp, plugin_name)
        try:
            os.makedirs(plugin_dir, mode=0o700, exist_ok=True)
            self._write_plugin(plugin_dir, plugin_name, bp_dir)
            agy_bin = _find_agy() or "agy"
            completed = subprocess.run(
                [agy_bin, "plugin", "install", plugin_dir],
                cwd=workspace or os.path.dirname(os.path.abspath(bp_dir)),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(
                    "Failed to install Antigravity MCP plugin"
                    + (f": {detail}" if detail else ".")
                )

            env = os.environ.copy()
            env[_PLUGIN_ENV] = plugin_name
            env[_PLUGIN_DIR_ENV] = plugin_dir
            return env, run_tmp
        except Exception:
            shutil.rmtree(run_tmp, ignore_errors=True)
            raise

    def finalize_env(self, env, run_tmp):
        plugin_name = (env or {}).get(_PLUGIN_ENV)
        if not plugin_name:
            return None
        agy_bin = _find_agy() or "agy"
        subprocess.run(
            [agy_bin, "plugin", "uninstall", plugin_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return None

    def _plugin_name(self, task_id=None):
        suffix = secrets.token_hex(4)
        base = f"bullpen-antigravity-runtime-{os.getpid()}-{suffix}"
        if task_id:
            safe_task = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(task_id))
            safe_task = safe_task.strip("-_")[:24]
            if safe_task:
                base = f"{base}-{safe_task}"
        return base[:80]

    def _write_plugin(self, plugin_dir, plugin_name, bp_dir):
        with open(os.path.join(plugin_dir, "plugin.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "name": plugin_name,
                    "version": "0.0.1",
                    "description": "Bullpen runtime MCP plugin for Antigravity.",
                },
                f,
                indent=2,
            )
        with open(os.path.join(plugin_dir, "mcp_config.json"), "w", encoding="utf-8") as f:
            json.dump(self._mcp_config(bp_dir), f, indent=2)

    def _mcp_config(self, bp_dir):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        server_script = os.path.join(project_root, "server", "mcp_tools.py")
        bp_dir = os.path.abspath(bp_dir)

        from server.persistence import read_json

        bp_config = read_json(os.path.join(bp_dir, "config.json"))
        host = bp_config.get("server_host", "127.0.0.1")
        if host == "0.0.0.0":
            host = "127.0.0.1"
        port = str(bp_config.get("server_port", 5000))

        return {
            "mcpServers": {
                "bullpen": {
                    "command": sys.executable,
                    "args": [
                        server_script,
                        "--bp-dir",
                        bp_dir,
                        "--host",
                        host,
                        "--port",
                        port,
                    ],
                    "cwd": project_root,
                    "env": {
                        "PYTHONPATH": project_root,
                    },
                    "enabledTools": [
                        "list_tickets",
                        "list_tasks",
                        "list_tickets_by_title",
                        "create_ticket",
                        "update_ticket",
                    ],
                },
            },
        }

    def prompt_via_stdin(self):
        return False

    def parse_output(self, stdout, stderr, exit_code):
        output = (stdout or "").strip()
        error = (stderr or "").strip()
        if exit_code == 0:
            return {"success": True, "output": output, "error": None, "usage": {}}
        return {
            "success": False,
            "output": output,
            "error": error or output or f"Antigravity exited with code {exit_code}",
            "usage": {},
        }
