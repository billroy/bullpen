# Security Audit — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Full static review of all server-side Python (Flask + SocketIO + agents) and client-side JavaScript for authentication, authorization, injection, session management, CORS, path traversal, secret handling, and subprocess safety.

---

## Summary

Bullpen is a locally-hosted developer tool and its security posture is calibrated accordingly. The core patterns—atomic writes, path traversal checks, constant-time comparisons, CSRF tokens, session fixation prevention—are solid. Several issues remain that matter when auth is enabled or the server is exposed beyond localhost.

---

## Findings

### HIGH — Auth disabled by default with no runtime warning to network listeners

**File:** `server/app.py:122–135`, `bullpen.py` (CLI entry point)

Auth is disabled when `~/.bullpen/.env` contains no credentials. The server prints a one-time warning to stderr but proceeds to bind and serve. If a user binds to `0.0.0.0` without setting a password, all API endpoints and Socket.IO events are world-accessible with no authentication enforced. The README documents that non-loopback binds "require" authentication, but there is no hard enforcement at startup that blocks binding if auth is disabled.

**Recommendation:** In `create_app()`, when `host != "127.0.0.1"` and `not auth.auth_enabled()`, either refuse to start or print a prominent multi-line banner. This is a defense-in-depth check rather than a hard blocker, but the current single-line stderr message is easy to miss.

---

### HIGH — `SESSION_COOKIE_SECURE=False` hard-coded

**File:** `server/app.py:120`

```python
SESSION_COOKIE_SECURE=False,
```

The code comment acknowledges this is intentional for localhost, but the value is unconditional. If Bullpen is deployed behind a TLS-terminating reverse proxy (a supported deployment documented in `docs/login.md`), cookies will still be set without the `Secure` flag, allowing session hijacking over HTTP on the same domain. The flag should be `True` when `HTTPS` or a `X-Forwarded-Proto: https` header is detected, or made configurable via an env var.

---

### MEDIUM — MCP token stored plaintext in `.bullpen/config.json`

**File:** `server/app.py:162–165`

The per-run MCP token (used to authenticate the stdio MCP server to Socket.IO) is written to `.bullpen/config.json` as cleartext. This file is created by `atomic_write` but is not created with restricted permissions (contrast with `.env` which is `chmod 0o600`). Any process that can read the workspace `.bullpen/` directory can impersonate the MCP server.

**Recommendation:** Apply `os.chmod(path, 0o600)` after writing `config.json`, or at minimum after writing fields that contain secrets.

---

### MEDIUM — CORS allows any ngrok subdomain unconditionally

**File:** `server/app.py:34–73`

```python
_TRUSTED_TUNNEL_SUFFIXES = (".ngrok-free.app", ".ngrok.app", ".ngrok.io")
```

The Socket.IO CORS handler allows any origin whose hostname ends with these suffixes. A different ngrok tunnel belonging to an attacker (or a compromised endpoint) could issue cross-origin requests to a Bullpen instance reachable via its own ngrok URL. Since the CORS allowlist is the primary network-layer gate, this is only exploitable when the server is exposed via ngrok—but the exposure is global by design.

**Recommendation:** Either accept only the specific ngrok hostname that matches the server's own public URL (which would need to be configured), or document that ngrok mode is inherently trusted-tunnel-only and requires auth.

---

### MEDIUM — `--dangerously-skip-permissions` passed to Claude CLI

**File:** `server/agents/claude_adapter.py:61`

All Claude agent invocations include `--dangerously-skip-permissions`, which bypasses Claude Code's interactive approval prompts. This is intentional for autonomous operation, but it means agents can execute arbitrary shell commands, write files anywhere in the workspace, and access external APIs without per-action confirmation. If a task prompt is injected with malicious content (e.g., a crafted ticket body that instructs the agent to exfiltrate code), the agent will comply without any safety gate.

**Recommendation:** Document this risk prominently. Consider restricting the agent's working directory or filesystem scope when worktrees are available. Add a config option to disable this flag for users who want interactive mode.

---

### MEDIUM — Gemini prompt passed as CLI argument (visible in `ps aux`)

**File:** `server/agents/gemini_adapter.py:76`

The full task prompt is passed as a `--prompt <text>` CLI argument to the Gemini binary. On Linux/macOS, process arguments are visible to all users via `ps aux` or `/proc/<pid>/cmdline`. This exposes potentially sensitive task content (API keys in prompts, code snippets, internal notes) to any user on the system.

**Recommendation:** Pass the prompt via stdin instead, as Claude and Codex adapters do. Check whether the Gemini CLI supports stdin input; if not, use a temporary file and delete it after spawning.

---

### MEDIUM — `next` redirect parameter not URL-encoded in `require_auth`

**File:** `server/auth.py:313–316`

```python
return redirect(url_for("login") + f"?next={next_url}")
```

`next_url` is appended raw to the redirect URL. If `next_url` contains `&`, `=`, or other URL metacharacters (valid in Flask path values), the query string will be malformed or misinterpreted. The value should be `urllib.parse.quote(next_url, safe="/")` before embedding in the URL.

---

### LOW — Token comparison for MCP auth uses `==` not `secrets.compare_digest`

**File:** `server/app.py:457`

```python
if not expected or not token or token != expected:
```

The MCP token is compared with `!=` rather than `secrets.compare_digest()`. For a 32-byte random URL-safe token, timing-based attacks are not practical, but the pattern is inconsistent with the careful use of `secrets.compare_digest` for CSRF tokens elsewhere in the codebase.

---

### LOW — `read_json` raises unhandled `FileNotFoundError` on missing files

**File:** `server/persistence.py:27–29`

`read_json` does not handle missing files; callers in `load_state` and `workers.py` rely on the file existing. During a race between file creation and first read, or after filesystem corruption, uncaught exceptions will surface as 500 errors or crash worker threads.

**Recommendation:** Add a `missing_ok` parameter or explicit guards at call sites for layout.json and config.json.

---

### LOW — Worktree cleanup runs outside the write lock in `workers.py`

**File:** `server/workers.py` (worktree setup/teardown paths)

Worktree creation and removal use `subprocess.run(["git", "worktree", ...])`. These calls happen outside `_write_lock`. Concurrent worker starts targeting the same branch could create duplicate worktrees or corrupt the git worktree registry.

**Recommendation:** Gate worktree add/remove calls inside `_write_lock`, or use a separate per-workspace worktree lock.

---

## Positive Observations

- **Path traversal:** `ensure_within()` (using `os.path.realpath`) is used consistently in file API handlers and persistence layer.
- **CSRF:** Login form uses `secrets.compare_digest` with session-bound token.
- **Session fixation:** `session.clear()` called before setting `authenticated = True` in `login_submit`.
- **Password hashing:** Werkzeug `pbkdf2` hashing; no plaintext storage.
- **Secret key:** Persisted to `.env` (0o600) to survive restarts.
- **Subprocess:** All git and agent invocations use list-based argv—no shell interpolation.
- **File write:** 1MB cap on API file writes; binary content rejected.
- **Redirect safety:** `_is_safe_next()` rejects protocol-relative and absolute URLs.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| S1 | HIGH | No startup enforcement when auth disabled + non-loopback bind |
| S2 | HIGH | `SESSION_COOKIE_SECURE=False` hard-coded |
| S3 | MEDIUM | MCP token plaintext in config.json without restricted permissions |
| S4 | MEDIUM | Ngrok CORS wildcard allows any ngrok tenant |
| S5 | MEDIUM | `--dangerously-skip-permissions` on all Claude invocations |
| S6 | MEDIUM | Gemini prompt visible in process list |
| S7 | MEDIUM | `next` param not URL-encoded in auth redirect |
| S8 | LOW | MCP token compared with `!=` not `compare_digest` |
| S9 | LOW | `read_json` unhandled FileNotFoundError |
| S10 | LOW | Worktree ops outside write lock |
