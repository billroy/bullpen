# Linux / Windows Portability Analysis

**Date:** 2026-04-09  
**Scope:** Full Python codebase (`server/`, `tests/`, `bullpen.py`)

---

## Summary

Bullpen runs on macOS today. Linux support is achievable with minimal changes. Windows support requires moderate work across three areas: process termination, agent binary discovery, and atomic file writes. No Unix-only Python dependencies were found.

---

## Issues by Priority

### P1 — Blocking on Windows

#### 1. `os.rename()` over an existing file fails on Windows (`persistence.py:16`)

`atomic_write()` uses `os.rename(tmp, path)`. On Windows, `os.rename` raises `FileExistsError` if the destination already exists (unlike POSIX where it is atomic). Every JSON write and ticket save goes through this path.

**Fix:** Replace `os.rename` with `os.replace`, which is atomic on POSIX and overwrites on Windows. Available since Python 3.3.

```python
# persistence.py:16
os.replace(tmp, path)   # replaces os.rename(tmp, path)
```

---

#### 2. Agent binary discovery has no Windows paths (`claude_adapter.py:12–15`, `codex_adapter.py:11–13`)

The fallback search lists only Unix paths. `shutil.which()` is tried first (good) but on Windows with non-standard installs it will also fail.

```python
_CLAUDE_SEARCH_PATHS = [
    os.path.expanduser("~/.local/bin/claude"),
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",    # macOS only
]
```

**Fix:** Add Windows-typical paths and `.cmd`/`.exe` suffixes:

```python
import sys, os

if sys.platform == "win32":
    _CLAUDE_SEARCH_PATHS = [
        os.path.expanduser(r"~\AppData\Local\Programs\claude\claude.cmd"),
        os.path.expanduser(r"~\AppData\Roaming\npm\claude.cmd"),
    ]
else:
    _CLAUDE_SEARCH_PATHS = [
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
    ]
```

Same pattern applies to `codex_adapter.py`.

---

#### 3. `os.access(path, os.X_OK)` is unreliable on Windows (`claude_adapter.py:25`, `codex_adapter.py:23`)

Windows does not have a Unix-style execute bit. `os.X_OK` always returns `True` for files on Windows, making the check useless. Actual executability depends on file extension (`.exe`, `.cmd`, `.bat`, `.com`).

**Fix:**

```python
def _is_executable(path):
    if not os.path.isfile(path):
        return False
    if sys.platform == "win32":
        return os.path.splitext(path)[1].lower() in {".exe", ".cmd", ".bat", ".com"}
    return os.access(path, os.X_OK)
```

---

### P2 — Degraded behavior on Windows

#### 4. `proc.terminate()` behavior differs on Windows (`workers.py:246`, `events.py:641`)

On POSIX, `terminate()` sends SIGTERM. On Windows it calls `TerminateProcess()`, which is immediate and cannot be caught — the agent has no chance to flush or clean up. Additionally, if the agent is a `.cmd` wrapper, only the cmd.exe shell is killed, leaving the underlying Node/Python process orphaned.

**Fix:** For `.cmd`-wrapped agents on Windows, use `taskkill /T /F /PID` to kill the process tree. The existing `terminate()` + `kill()` fallback is otherwise acceptable on Windows for `.exe` processes, but should be documented.

```python
def _terminate_proc(proc):
    if sys.platform == "win32":
        # Kill entire process tree to handle .cmd wrappers
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        proc.terminate()
```

---

#### 5. Hardcoded `/tmp` in tests (`test_persistence.py:75`, `test_events_chat_hardening.py:9`)

```python
os.symlink("/tmp", link)           # test_persistence.py:75
argv = [..., "/tmp/x.json"]        # test_events_chat_hardening.py:9
```

Tests will fail on Windows because `/tmp` does not exist.

**Fix:** Use `tempfile.gettempdir()` and `tempfile.mktemp()` / `tmp_path` pytest fixture.

---

### P3 — Works but worth addressing

#### 6. `~/.bullpen` global registry path (`workspace_manager.py:11–12`)

```python
GLOBAL_DIR = os.path.expanduser("~/.bullpen")
```

`os.path.expanduser("~")` works on Windows (resolves to `%USERPROFILE%`). The dotfile convention is fine — on Windows the directory won't be hidden, but it is functional. No code change required; however, a Windows-idiomatic location would be `%APPDATA%\bullpen`.

**Assessment:** Acceptable as-is for an initial port; log a follow-up to consider `%APPDATA%` if users expect it.

---

#### 7. Path traversal check uses string prefix comparison (`persistence.py:40`)

```python
if not real_path.startswith(real_root + os.sep) and real_path != real_root:
```

On Windows, `os.path.realpath` resolves drive letters and UNC paths, so `C:\foo` and `c:\foo` could compare unequal. Case sensitivity is not guaranteed.

**Fix:** Normalise both paths to lowercase (or use `pathlib.Path` with `is_relative_to`, available since Python 3.9):

```python
from pathlib import Path

def ensure_within(path, root):
    real_path = Path(os.path.realpath(path))
    real_root = Path(os.path.realpath(root))
    if real_path != real_root and not real_path.is_relative_to(real_root):
        raise ValueError(f"Path {path} escapes root {root}")
    return str(real_path)
```

---

#### 8. Symlink in path-traversal test requires admin or Developer Mode on Windows (`test_persistence.py:75`)

`os.symlink()` on Windows requires either elevated privileges or Developer Mode enabled. The test will fail or error without it.

**Fix:** Skip the symlink test on Windows with `@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")`, or use the pytest `tmp_path` fixture with a real subdirectory instead.

---

### Linux-only findings

Linux support looks solid. The only items that need attention:

- **`/opt/homebrew` search path** in both adapters is a no-op on Linux (path won't exist, `os.path.isfile` returns False) — harmless but noisy. Remove from the Linux path set.
- **`shutil.which("claude")`** correctly discovers npm-installed or pip-installed CLIs on Linux via `$PATH` — no changes needed.
- **`proc.terminate()` / SIGTERM** — works correctly on Linux.
- **`os.rename` atomicity** — atomic on Linux (same filesystem). No issue.

---

## Remediation Plan

| # | Priority | File(s) | Change | Effort |
|---|----------|---------|--------|--------|
| 1 | P1 | `persistence.py:16` | `os.rename` → `os.replace` | Trivial (1 line) |
| 2 | P1 | `claude_adapter.py`, `codex_adapter.py` | Add Windows binary search paths | Small |
| 3 | P1 | `claude_adapter.py:25`, `codex_adapter.py:23` | Replace `os.X_OK` with extension check on Windows | Small |
| 4 | P2 | `workers.py:246`, `events.py:641` | Platform-aware process termination via `_terminate_proc()` helper | Medium |
| 5 | P2 | `tests/test_persistence.py:75`, `tests/test_events_chat_hardening.py:9` | Replace `/tmp` with `tempfile` equivalents | Small |
| 6 | P3 | `persistence.py:40` | Use `pathlib.Path.is_relative_to` for traversal check | Small |
| 7 | P3 | `tests/test_persistence.py:75` | Skip or rewrite symlink test on Windows | Trivial |

**Recommended sequencing:** Fix items 1–3 first (they are individually small and collectively unblock a first Windows run), then 4–5 (test coverage), then 6–7 (robustness).

---

## Out of scope / not issues

- **Dependencies** (`flask`, `flask-socketio`, `eventlet`, `pytest`): all cross-platform.
- **Networking**: no Unix domain sockets; loopback defaults are correct.
- **MCP framing** (`\r\n` in `mcp_tools.py`): intentional per MCP spec.
- **`~/.bullpen` dotfile**: functional on all platforms.
- **`subprocess` argv lists** (no `shell=True`): cross-platform safe.
