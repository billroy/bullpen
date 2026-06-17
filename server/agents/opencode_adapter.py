"""OpenCode CLI adapter."""

import json
import os
import shutil
import sys
import tempfile

from server.agents.base import AgentAdapter
from server.agents.mcp_config import opencode_mcp_config
from server.usage import extract_opencode_usage_event, merge_usage_dicts


if sys.platform == "win32":
    _OPENCODE_SEARCH_PATHS = [
        os.path.expanduser(r"~\.opencode\bin\opencode.cmd"),
        os.path.expanduser(r"~\AppData\Roaming\npm\opencode.cmd"),
        os.path.expanduser(r"~\AppData\Local\Programs\opencode\opencode.cmd"),
    ]
else:
    _OPENCODE_SEARCH_PATHS = [
        os.path.expanduser("~/.opencode/bin/opencode"),
        os.path.expanduser("~/.local/bin/opencode"),
        "/usr/local/bin/opencode",
        "/opt/homebrew/bin/opencode",
    ]


def _is_executable(path):
    """Check if a file is executable (extension-based on Windows, X_OK elsewhere)."""
    if not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        return os.path.splitext(path)[1].lower() in {".exe", ".cmd", ".bat", ".com"}
    return os.access(path, os.X_OK)


def _find_opencode():
    """Find the opencode binary on PATH or common install locations."""
    configured = os.environ.get("BULLPEN_OPENCODE_PATH")
    if configured and _is_executable(os.path.expanduser(configured)):
        return os.path.expanduser(configured)

    found = shutil.which("opencode")
    if found:
        return found
    for path in _OPENCODE_SEARCH_PATHS:
        if _is_executable(path):
            return path
    return None


def _make_isolated_tmpdir(prefix):
    """Create a private temp directory, preferring the current TMPDIR root."""
    candidates = [os.environ.get("TMPDIR"), tempfile.gettempdir()]
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            os.makedirs(candidate, exist_ok=True)
            return tempfile.mkdtemp(prefix=prefix, dir=candidate)
        except OSError:
            continue
    return tempfile.mkdtemp(prefix=prefix)


def _string_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join([p for p in parts if p])
    return ""


class OpenCodeAdapter(AgentAdapter):

    @property
    def name(self):
        return "opencode"

    def available(self):
        return _find_opencode() is not None

    def unavailable_message(self):
        configured = os.environ.get("BULLPEN_OPENCODE_PATH")
        if configured:
            return (
                "OpenCode CLI is not available. BULLPEN_OPENCODE_PATH is set to "
                f"{configured!r}, but that file was not found or is not executable."
            )
        return (
            "OpenCode CLI is not available. Install OpenCode and authenticate, "
            "or set BULLPEN_OPENCODE_PATH to the opencode executable."
        )

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        opencode_bin = _find_opencode() or "opencode"
        return [
            opencode_bin,
            "run",
            "--format", "json",
            "--model", model,
        ]

    def prepare_env(self, workspace, bp_dir=None, task_id=None):
        run_tmp = _make_isolated_tmpdir("bullpen-opencode-")
        env = os.environ.copy()
        self._remove_source_pythonpath(env)
        self._set_workspace_pwd(env, workspace)
        env["TMPDIR"] = run_tmp
        env["TMP"] = run_tmp
        env["TEMP"] = run_tmp

        if bp_dir:
            config_path = os.path.join(run_tmp, "opencode.json")
            launcher_path = self._write_mcp_launcher(run_tmp)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self._mcp_config(bp_dir, launcher_path=launcher_path), f)
            env["OPENCODE_CONFIG"] = config_path

        return env, run_tmp

    def _write_mcp_launcher(self, run_tmp):
        launcher_path = os.path.join(run_tmp, "bullpen_mcp_launcher.py")
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(
                "import os\n"
                "import sys\n\n"
                f"ROOT = {root!r}\n"
                "if ROOT not in sys.path:\n"
                "    sys.path.insert(0, ROOT)\n\n"
                "from server.mcp_tools import run_cli\n\n"
                "raise SystemExit(run_cli())\n"
            )
        return launcher_path

    def _remove_source_pythonpath(self, env):
        root = os.path.realpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        raw = env.get("PYTHONPATH")
        if not raw:
            return
        kept = []
        for part in raw.split(os.pathsep):
            if not part:
                continue
            if os.path.realpath(os.path.abspath(part)) == root:
                continue
            kept.append(part)
        if kept:
            env["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            env.pop("PYTHONPATH", None)

    def _set_workspace_pwd(self, env, workspace):
        if workspace:
            env["PWD"] = os.path.abspath(workspace)
        root = os.path.realpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        for key in ("OLDPWD", "INIT_CWD"):
            value = env.get(key)
            if value and os.path.realpath(os.path.abspath(value)) == root:
                env.pop(key, None)

    def _mcp_config(self, bp_dir, *, launcher_path=None):
        """Return an OpenCode config object for Bullpen MCP tools."""
        return opencode_mcp_config(bp_dir, launcher_path=launcher_path)

    def format_stream_line(self, line):
        """Extract readable text from OpenCode JSON events."""
        line = line.strip()
        if not line:
            return None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return line

        evt_type = obj.get("type")
        part = obj.get("part") if isinstance(obj.get("part"), dict) else {}

        if evt_type == "text":
            text = part.get("text")
            return text.strip() if isinstance(text, str) and text.strip() else None

        if evt_type == "error":
            return self._error_message(obj)

        if evt_type in {"step_start", "step_finish"}:
            return None

        # Future OpenCode versions may emit tool events. Keep them visible in a
        # compact form instead of crashing or dumping large JSON payloads.
        if evt_type and "tool" in str(evt_type).lower():
            name = part.get("tool") or part.get("name") or evt_type
            return f"[{name}]"

        return None

    def parse_output(self, stdout, stderr, exit_code):
        """Parse OpenCode JSONL output."""
        texts = []
        usage = {}
        error_msg = None
        saw_json = False
        non_json_lines = []

        for raw_line in (stdout or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                non_json_lines.append(raw_line)
                continue
            saw_json = True

            evt_type = obj.get("type")
            if evt_type == "text":
                part = obj.get("part") if isinstance(obj.get("part"), dict) else {}
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
            elif evt_type == "error":
                error_msg = self._error_message(obj)

            extracted = extract_opencode_usage_event(obj)
            if extracted:
                usage = merge_usage_dicts(usage, extracted)

        output = "\n".join([t for t in texts if t]).strip()

        if exit_code != 0:
            return {
                "success": False,
                "output": output,
                "error": error_msg or (stderr or "").strip() or output or f"Exit code {exit_code}",
                "usage": usage,
            }

        if error_msg:
            return {
                "success": False,
                "output": output,
                "error": error_msg,
                "usage": usage,
            }

        if output:
            return {"success": True, "output": output, "error": None, "usage": usage}

        if not saw_json and non_json_lines:
            return {
                "success": True,
                "output": "\n".join(non_json_lines).strip(),
                "error": None,
                "usage": usage,
            }

        return {
            "success": exit_code == 0,
            "output": output,
            "error": None if exit_code == 0 else (stderr or "").strip(),
            "usage": usage,
        }

    def _error_message(self, obj):
        error = obj.get("error")
        if isinstance(error, str):
            return error
        if not isinstance(error, dict):
            return "OpenCode error"
        data = error.get("data")
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            return data["message"]
        if isinstance(error.get("message"), str):
            return error["message"]
        content = _string_from_content(error.get("content"))
        if content:
            return content
        name = error.get("name")
        return str(name) if name else "OpenCode error"
