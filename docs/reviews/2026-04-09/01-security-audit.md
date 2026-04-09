# Security Audit — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Security engineer evaluating as a potential acquirer

---

## Scope

Full review of authentication, session management, input validation, CORS policy, path traversal protections, frontend supply chain, agent execution security, and error handling across the entire codebase.

---

## Executive Summary

Bullpen is a single-user, localhost-first tool with a thoughtful security baseline: scrypt password hashing, per-session CSRF tokens, atomic file writes with path traversal guards, a comprehensive input validation layer, and SRI hashes on all CDN dependencies. The primary risks are concentrated at the network boundary—specifically the deliberate CORS wildcard when binding to `0.0.0.0`, the absence of login rate limiting, and the use of permissive agent execution flags (`--dangerously-skip-permissions`, `--full-auto`). These are intentional MVP trade-offs, well-documented in `docs/login.md`, but they must be addressed before any production or multi-user deployment.

---

## Findings

### HIGH — No Rate Limiting on Login Endpoint

**Location:** `server/app.py:154-189` (`login_submit` route)

The `POST /login` endpoint performs password verification (`werkzeug.security.check_password_hash`) with no attempt throttling, no lockout, and no CAPTCHA. An attacker with network access can attempt passwords at the speed of the server's scrypt computation. While scrypt is intentionally slow, the absence of any throttle means parallel or sustained attacks are feasible.

**Evidence:**
- No `flask-limiter`, `slowapi`, or equivalent in `requirements.txt`
- No lockout counter in `server/auth.py`
- `login_submit()` returns a redirect to `?error=1` on failure with no delay

**Recommendation:** Add IP-based rate limiting (e.g., flask-limiter) capping login attempts at 5 per minute per IP. Log failed attempts with IP and timestamp to `.bullpen/logs/`.

---

### MEDIUM — CORS Wildcard When Binding to 0.0.0.0

**Location:** `server/app.py:81-85`

```python
if host == "0.0.0.0":
    cors_origin = "*"
else:
    cors_origin = f"http://{host}:{port}"
```

When the user starts Bullpen with `--host 0.0.0.0`, Socket.IO is initialized with `cors_allowed_origins="*"`. This allows any web page on the network to send authenticated Socket.IO commands (task creation, worker execution, file writes) if the browser has a valid session cookie. Combined with SameSite=Lax (not Strict), cross-origin GET-initiated navigation can set a session that is then reused.

**Note:** When bound to the default `127.0.0.1`, the CORS origin is correctly scoped to `http://127.0.0.1:<port>`. The risk only manifests with explicit `--host 0.0.0.0`.

**Recommendation:** Derive a specific CORS origin from a `--public-url` flag or require the operator to specify the exact origin. Do not accept `*` — emit a startup warning and require explicit opt-in (`--cors-allow-all`).

---

### MEDIUM — Session Cookie `Secure` Flag Always False

**Location:** `server/app.py:57-58` (comment), `server/auth.py`

`SESSION_COOKIE_SECURE` is hardcoded to `False` with a comment noting production should use a reverse proxy. This means if an operator deploys Bullpen behind an HTTPS reverse proxy without also setting `SESSION_COOKIE_SECURE=True`, cookies are transmitted in plaintext over HTTPS (the browser still sends them, but they are not marked Secure).

**Recommendation:** Set `SESSION_COOKIE_SECURE` based on a `--production` flag or detect the `X-Forwarded-Proto: https` header and flip it at startup. Document clearly in `docs/login.md`.

---

### MEDIUM — Agent Execution with Unrestricted Permissions

**Location:** `server/agents/claude_adapter.py`, `server/agents/codex_adapter.py`

- Claude: `--dangerously-skip-permissions` is always passed
- Codex: `--full-auto` is always passed

These flags give the agent process unrestricted filesystem and subprocess access within the workspace (and potentially beyond, depending on the agent implementation). A prompt injection attack via a malicious task description or workspace file could escalate to arbitrary code execution.

**Note:** This is explicitly documented as intentional for the single-developer MVP (`docs/login.md`). The risk is higher if the system is exposed to untrusted task input sources.

**Recommendation:** Make these flags configurable per worker profile. Add a `trust_level: restricted | trusted | unrestricted` field to worker profiles, and omit the permissive flags when `trust_level` is not `unrestricted`.

---

### LOW — Error Responses May Leak Internal Details

**Location:** `server/events.py` (ValidationError handlers)

Validation errors are emitted to the client as `{"error": str(e)}`. For `ValidationError`, this is safe — messages are programmer-controlled. However, any unhandled exception reaching the catch-all handler could expose a full traceback or internal path.

**Recommendation:** Audit all `except Exception as e` blocks in `events.py` and `app.py`. Ensure unhandled exceptions log full details server-side and return only a static error string to the client.

---

### LOW — MCP Temp Config File Written to Disk

**Location:** `server/agents/claude_adapter.py` (MCP config generation)

The MCP config pointing to `mcp_tools.py` is written to a temp file before each agent invocation. If the agent process crashes or is killed, the cleanup of the temp file may not run.

**Recommendation:** Use `tempfile.NamedTemporaryFile(delete=True)` with a context manager or register a `finally` cleanup to ensure the temp file is always removed.

---

### POSITIVE FINDINGS

- **SRI hashes present on all CDN resources** — All 10 CDN scripts/stylesheets in `static/index.html` have `integrity=sha384-...` and `crossorigin="anonymous"`. This is correctly implemented.
- **CSRF protection on login form** — Per-session CSRF token fetched from `/login/csrf`, validated on POST, regenerated after successful login. Implementation is correct.
- **Password hashing** — Werkzeug scrypt (default since Werkzeug 2.0). Constant-time comparison used.
- **Path traversal protection** — `ensure_within()` in `server/persistence.py` uses `os.path.realpath()` before comparison. ID fields validated against `^[a-zA-Z0-9_-]{1,80}$`.
- **Atomic file writes** — `atomic_write()` uses `tempfile.mkstemp()` + `os.replace()`. Prevents partial writes.
- **Session flags** — `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`.
- **Payload size limit** — 1MB cap enforced in `validate_payload_size()`.
- **Input validation layer** — `server/validation.py` covers all event types with field-level constraints and enum whitelisting.

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| SEC-01 | No rate limiting on login endpoint | HIGH |
| SEC-02 | CORS wildcard when host=0.0.0.0 | MEDIUM |
| SEC-03 | SESSION_COOKIE_SECURE hardcoded False | MEDIUM |
| SEC-04 | Unrestricted agent execution flags | MEDIUM |
| SEC-05 | Error responses may leak internal details | LOW |
| SEC-06 | MCP temp config file may not be cleaned up | LOW |
