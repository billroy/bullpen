# Security Audit — Bullpen
**Review date:** 2026-04-10  
**Reviewer role:** Application Security Engineer  
**Perspective:** Potential acquirer / independent security assessment

---

## Executive Summary

Bullpen is a single-user, localhost-first developer tool. Its security posture is appropriate for that threat model: auth is optional-but-complete when enabled, input validation is thorough, and file operations are hardened. Two issues require attention before any network-exposed deployment: a missing SRI hash on a CDN-loaded script, and the absence of security response headers. No critical vulnerabilities were found.

---

## Severity Table

| ID | Severity | Finding |
|----|----------|---------|
| S1 | MEDIUM | Lucide CDN script loaded without SRI hash and at floating `@latest` version |
| S2 | MEDIUM | No HTTP security headers (CSP, X-Frame-Options, X-Content-Type-Options, HSTS) |
| S3 | LOW | `SESSION_COOKIE_SECURE=False` hard-coded — sessions transmitted over HTTP even on remote deployments |
| S4 | LOW | CORS set to `*` when `--host 0.0.0.0` is used, allowing any origin |
| S5 | LOW | `--dangerously-skip-permissions` passed unconditionally to Claude CLI |
| S6 | LOW | Temp MCP config files written to system temp dir and not cleaned up after agent run |
| S7 | INFO | CSRF protection covers only the login form; Socket.IO events are not CSRF-guarded (SameSite=Lax partially mitigates) |
| S8 | INFO | No rate limiting on the login endpoint |
| S9 | INFO | `status` field accepted as arbitrary string in `validate_task_create` / `validate_task_update` — not enumerated |

---

## Detailed Findings

### S1 — MEDIUM: Lucide CDN script loaded without SRI hash

**File:** `static/index.html:26`

```html
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
```

All other CDN scripts in `index.html` carry `integrity="sha384-..."` and `crossorigin="anonymous"` attributes. The Lucide script is the sole exception. Additionally, it uses the `@latest` floating tag rather than a pinned version.

**Risk:** If the unpkg CDN or Lucide's package is compromised, arbitrary JavaScript executes in the user's browser with full access to the authenticated session and all Socket.IO state. The SRI check is the only client-side safeguard against this class of supply-chain attack.

**Fix:** Pin to a specific version and add an `integrity` attribute:
```html
<script src="https://unpkg.com/lucide@0.x.y/dist/umd/lucide.min.js"
        integrity="sha384-<hash>"
        crossorigin="anonymous"></script>
```

---

### S2 — MEDIUM: No HTTP security headers

**File:** `server/app.py` (no `after_request` hook adding headers)

Flask sends no `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, or `Referrer-Policy` headers. When the server is accessed over a LAN or through a reverse proxy, the absence of these headers enables:

- Clickjacking (no X-Frame-Options / CSP frame-ancestors)
- MIME sniffing attacks (no X-Content-Type-Options: nosniff)
- Cross-site script inclusion

**Fix:** Add an `after_request` hook in `app.py`:
```python
@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp
```
A strict CSP is harder to add given inline scripts from Vue CDN but `frame-ancestors 'none'` and `nosniff` are zero-friction.

---

### S3 — LOW: `SESSION_COOKIE_SECURE=False` hard-coded

**File:** `server/app.py:60`

```python
SESSION_COOKIE_SECURE=False,
```

The comment correctly notes this is intentional for localhost. However, if a user exposes Bullpen through a TLS reverse proxy, the `Secure` flag should be set so session cookies are not sent over plain HTTP. Currently there is no mechanism for the operator to enable this without editing source.

**Fix:** Read a `--secure-cookies` flag or environment variable and set `SESSION_COOKIE_SECURE` conditionally.

---

### S4 — LOW: CORS wildcard when binding to 0.0.0.0

**File:** `server/app.py:82-86`

```python
if host == "0.0.0.0":
    cors_origin = "*"
else:
    cors_origin = f"http://{host}:{port}"
```

When the server is exposed on the LAN, any origin can make authenticated Socket.IO requests if a session cookie is present. SameSite=Lax provides partial mitigation (cross-site navigations carry cookies but cross-origin fetches do not), but the wildcard still allows cross-origin WebSocket upgrades from any page open in the same browser.

**Fix:** Require the caller to supply `--cors-origin <url>` explicitly instead of defaulting to `*`.

---

### S5 — LOW: `--dangerously-skip-permissions` passed unconditionally

**File:** `server/agents/claude_adapter.py:61`

The Claude CLI is invoked with `--dangerously-skip-permissions` on every run, granting the spawned agent unrestricted filesystem and shell access. This is a necessary concession for an automation tool but means a malicious or confused prompt can perform destructive operations on the workspace.

**Mitigation in place:** Claude is separately constrained with `--disallowedTools Bash,Read,Glob,Grep,Edit,Write,NotebookEdit` via the MCP config. However, these two flags interact in non-obvious ways and may not fully contain a misbehaving agent.

**Recommendation:** Document this explicitly in the README threat model and consider a prompt-injection warning when user-controlled content flows into the agent prompt.

---

### S6 — LOW: Temp MCP config files not cleaned up

**File:** `server/agents/claude_adapter.py:93-96`

```python
fd, path = tempfile.mkstemp(suffix=".json", prefix="bullpen-mcp-")
with os.fdopen(fd, "w") as f:
    json.dump(config, f)
return path
```

The path is returned and passed to `--mcp-config` but there is no `finally:` block or cleanup after the subprocess exits. The MCP token written into these files accumulates in the system temp directory.

**Fix:** Track the temp path in `build_argv` return value or a caller-managed context, and `os.unlink()` it after the subprocess completes.

---

### S7 — INFO: CSRF applies only to login form

**File:** `server/auth.py:245-259`

Socket.IO event handlers do not validate a CSRF token. This is acceptable because:
1. `SameSite=Lax` prevents the session cookie from being sent by cross-site requests (except top-level navigations).
2. Socket.IO's WebSocket upgrade requires an existing session, which the same-origin policy protects.

No action needed for the current threat model. If `SameSite=None` is ever needed, revisit.

---

### S8 — INFO: No rate limiting on `/login`

**File:** `server/app.py` (login route)

No brute-force protection exists on the login endpoint. For a single-user localhost tool this is acceptable. For network-exposed deployments, an operator-managed rate limiter (nginx `limit_req`, Cloudflare, etc.) should be recommended in the documentation.

---

### S9 — INFO: `status` field not enumerated in task validation

**File:** `server/validation.py:109-111, 133`

```python
if "status" in data:
    result["status"] = str(data["status"])
```

The `status` field is accepted as an arbitrary string rather than validated against a known set of column names. This is intentional (custom columns are user-defined), but it means a client can set arbitrary status strings including ones that are not displayed in the UI. Not a vulnerability for a single-user tool.

---

## Positive Controls Worth Noting

- All other CDN scripts use SRI hashes (`integrity=`) and `crossorigin="anonymous"`.
- `SESSION_COOKIE_HTTPONLY=True` prevents JavaScript from reading session tokens.
- Password hashing uses Werkzeug's `generate_password_hash` / `check_password_hash` (scrypt/PBKDF2).
- Secret key auto-generated with `secrets.token_hex(32)` and stored at `~/.bullpen/.env` (mode 0o600).
- CSRF token uses `secrets.compare_digest` (constant-time comparison).
- Session regenerated on login to prevent session fixation.
- `next` redirect validated via `_is_safe_next()` to prevent open-redirect.
- Path traversal prevented by `ensure_within(path, root)` in file API.
- Agent CLI arguments built programmatically (no `shell=True`).
- Subprocess stdout/stdin/stderr fully separated; no shell injection surface.
- Write lock serializes all state mutations; no TOCTOU on layout/task files.
- Auth env file created with `O_CREAT | mode=0o600` — never world-readable.
