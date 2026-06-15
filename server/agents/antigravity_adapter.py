"""Google Antigravity CLI adapter."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

from server.agents.base import AgentAdapter
from server.agents.mcp_config import antigravity_mcp_config


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
_GEMINI_DIR_ENV = "BULLPEN_ANTIGRAVITY_GEMINI_DIR"
_MANAGED_GEMINI_DIR_ENV = "BULLPEN_ANTIGRAVITY_MANAGED_GEMINI_DIR"
_MINIMAL_GEMINI_AUTH_FILES = (
    "oauth_creds.json",
    "google_accounts.json",
    "settings.json",
    os.path.join("antigravity-cli", "settings.json"),
)
_RUNTIME_PLUGIN_RE = re.compile(
    r"\bbullpen-antigravity-runtime-(\d+)-[A-Za-z0-9]+(?:-[A-Za-z0-9_-]+)?\b"
)


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


def _configured_gemini_dir():
    configured = os.environ.get(_GEMINI_DIR_ENV)
    if configured:
        target = os.path.abspath(os.path.expanduser(configured))
        _ensure_gemini_dir(target)
        return target
    return _managed_gemini_dir()


def _managed_gemini_dir():
    configured = os.environ.get(_MANAGED_GEMINI_DIR_ENV)
    if configured:
        target = os.path.abspath(os.path.expanduser(configured))
    else:
        target = os.path.abspath(os.path.expanduser("~/.bullpen/antigravity/.gemini"))
    _ensure_gemini_dir(target)
    return target


def _ensure_gemini_dir(target):
    os.makedirs(target, mode=0o700, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass

    source = os.path.abspath(os.path.expanduser("~/.gemini"))
    if source == target or not os.path.isdir(source):
        return

    for relative_path in _MINIMAL_GEMINI_AUTH_FILES:
        source_path = os.path.join(source, relative_path)
        target_path = os.path.join(target, relative_path)
        if not os.path.isfile(source_path) or os.path.exists(target_path):
            continue
        try:
            os.makedirs(os.path.dirname(target_path), mode=0o700, exist_ok=True)
            shutil.copy2(source_path, target_path)
            if sys.platform != "win32":
                os.chmod(target_path, 0o600)
        except OSError:
            logging.debug(
                "Unable to seed Antigravity managed Gemini auth file %s",
                relative_path,
                exc_info=True,
            )


def _agy_argv():
    argv = [_find_agy() or "agy"]
    gemini_dir = _configured_gemini_dir()
    if gemini_dir:
        argv.extend(["--gemini_dir", gemini_dir])
    return argv


def _pid_is_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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


class AntigravityPluginManager:
    def __init__(self, workspace=None, bp_dir=None):
        self.workspace = workspace
        self.bp_dir = bp_dir

    def install(self, plugin_dir):
        completed = subprocess.run(
            [*_agy_argv(), "plugin", "install", plugin_dir],
            cwd=self.workspace or os.path.dirname(os.path.abspath(self.bp_dir or ".")),
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
        return completed

    def uninstall(self, plugin_name):
        if not plugin_name:
            return False
        try:
            completed = subprocess.run(
                [*_agy_argv(), "plugin", "uninstall", plugin_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            logging.exception("Failed to uninstall Antigravity MCP plugin %s", plugin_name)
            return False
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            logging.warning(
                "Failed to uninstall Antigravity MCP plugin %s%s",
                plugin_name,
                f": {detail}" if detail else ".",
            )
            return False
        return True

    def cleanup_stale_runtime_plugins(self):
        try:
            completed = subprocess.run(
                [*_agy_argv(), "plugin", "list"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            logging.debug("Unable to list Antigravity plugins for stale cleanup", exc_info=True)
            return []
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            logging.debug(
                "Unable to list Antigravity plugins for stale cleanup%s",
                f": {detail}" if detail else ".",
            )
            return []

        cleaned = []
        seen = set()
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        for match in _RUNTIME_PLUGIN_RE.finditer(output):
            plugin_name = match.group(0)
            if plugin_name in seen:
                continue
            seen.add(plugin_name)
            try:
                pid = int(match.group(1))
            except ValueError:
                continue
            if _pid_is_alive(pid):
                continue
            if self.uninstall(plugin_name):
                cleaned.append(plugin_name)
        if cleaned:
            logging.info("Cleaned up stale Antigravity MCP plugins: %s", ", ".join(cleaned))
        return cleaned


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
        argv = _agy_argv()
        argv.extend(
            [
                "--print-timeout",
                "10m",
            ]
        )
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
        plugin_manager = AntigravityPluginManager(workspace=workspace, bp_dir=bp_dir)
        try:
            plugin_manager.cleanup_stale_runtime_plugins()
            os.makedirs(plugin_dir, mode=0o700, exist_ok=True)
            self._write_plugin(plugin_dir, plugin_name, bp_dir)
            plugin_manager.install(plugin_dir)

            env = os.environ.copy()
            env[_PLUGIN_ENV] = plugin_name
            env[_PLUGIN_DIR_ENV] = plugin_dir
            return env, run_tmp
        except Exception:
            plugin_manager.uninstall(plugin_name)
            shutil.rmtree(run_tmp, ignore_errors=True)
            raise

    def finalize_env(self, env, run_tmp):
        plugin_name = (env or {}).get(_PLUGIN_ENV)
        if not plugin_name:
            return None
        AntigravityPluginManager().uninstall(plugin_name)
        return None

    def _uninstall_plugin(self, plugin_name):
        AntigravityPluginManager().uninstall(plugin_name)
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
        return antigravity_mcp_config(bp_dir)

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
