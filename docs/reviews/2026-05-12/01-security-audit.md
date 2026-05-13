# Security Audit — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Application security engineer evaluating for acquisition/investment

---

## Executive Summary

Bullpen demonstrates a thoughtful security posture for its threat model (developer-run, localhost-first, single-tenant). Core controls — authentication, CSRF protection, path traversal prevention, and secrets isolation — are correctly implemented and consistently applied. The main residual risks are the absence of HTTP security headers, lack of rate limiting on WebSocket events, and the inherent trust boundary weaknesses that arise from running untrusted AI agent output in a browser context without Content Security Policy. No critical vulnerabilities were identified.

---

## Findings

### HIGH — No Content Security Policy (CSP) header

**Location:** `server/app.py` (Flask response headers, no `after_request` hook observed adding CSP)

**Detail:** The application renders user-supplied markdown (ticket bodies, agent output) on the client side via `markdown-it`. Without a CSP, any XSS payload that reaches the DOM — whether from a compromised task body, a prompt-injected agent response, or a supply-chain issue in a CDN-served library — executes with full page-origin privileges. The `<iframe sandbox>` used in `FilesTab.js` for HTML preview is a correct mitigation for file preview specifically, but it does not extend protection to the main application frame. CDN libraries (Vue, Socket.IO, markdown-it, Prism) are loaded with SRI hashes (verified), which prevents hash-mismatched substitution attacks, but a CSP `script-src` directive would provide defense-in-depth.

**Recommendation:** Add a `Content-Security-Policy` response header permitting `'self'` scripts plus the explicit CDN origins, with `default-src 'self'`, blocking inline `<script>` and eval. Also add `X-Content-Type-Options: nosniff` and `X-Frame-Options: SAMEORIGIN`.

---

### HIGH — No rate limiting on Socket.IO events

**Location:** `server/events.py`, `server/validation.py`

**Detail:** All Socket.IO event handlers apply size and structural validation but impose no per-client rate limit. An authenticated or unauthenticated (if auth disabled) client can emit `task:create`, `worker:start`, or `chat:send` at arbitrary rates. `worker:start` spawns subprocesses; a burst of `worker:start` events could exhaust system resources (file descriptors, PIDs, memory from subprocess buffers). `task:create` writes files on every call; rapid fire could fill disk. `chat:send` proxies to paid AI APIs; runaway calls represent a cost risk.

**Recommendation:** Implement per-connection, per-event-type token bucket rate limiting (e.g., `worker:start` ≤ 5/second, `chat:send` ≤ 10/second) in a Socket.IO middleware or per-handler guard. Flask-Limiter can cover REST routes; a simple `time.monotonic()` check per socket SID covers Socket.IO events.

---

### MEDIUM — `BULLPEN_PRODUCTION=1` must be set manually; insecure defaults in non-localhost deploys

**Location:** `server/app.py`, `server/auth.py`; documented in `docs/login.md`

**Detail:** Session cookies are only flagged `Secure`, `HttpOnly`, and `SameSite=Lax` when `BULLPEN_PRODUCTION=1` is set. An operator who exposes Bullpen over HTTPS (e.g., via nginx reverse proxy) without setting this flag will serve auth cookies without the `Secure` attribute, allowing them to be captured over HTTP if any HTTP path is reachable. This is a deployment configuration risk, not a code bug, but it is a known and documented failure mode in similar applications. The enforcement of `auth required for non-localhost binds` is good but relies on operator discipline.

**Recommendation:** Auto-detect HTTPS when `X-Forwarded-Proto: https` is present (via `ProxyFix` or custom middleware) and set `SESSION_COOKIE_SECURE` automatically, removing the dependency on operator remembering to set the flag.

---

### MEDIUM — MCP token stored in `config.json` alongside non-secret configuration

**Location:** `server/init.py`, `.bullpen/config.json`

**Detail:** The MCP authentication token is written to `.bullpen/config.json` (a workspace-level file) alongside non-sensitive settings (theme, grid dimensions, column names). The global secrets registry (`~/.bullpen/secrets.json`, mode 600) also tracks these tokens. However, the per-workspace `config.json` does not appear to receive `chmod 600` treatment and may be readable by other users on a shared system. Any process or user with access to the workspace directory can read the MCP token and impersonate an MCP agent to the Bullpen server.

**Recommendation:** Move the `mcp_token` field from `config.json` to `secrets.json` (already mode 600), and store only a reference (e.g., a workspace-ID lookup key) in `config.json`. Alternatively, apply `chmod 600` to `config.json` on create/update.

---

### MEDIUM — Shell worker output redacts secrets by env-var name pattern only

**Location:** `server/workers.py` (secrets redaction logic)

**Detail:** Shell worker output is scanned for env vars whose names match patterns containing `TOKEN`, `SECRET`, `KEY`, `PASSWORD`, or `CREDENTIAL`, and matching values are redacted before display. This is correct for well-named secrets but misses secrets stored under arbitrary names (e.g., `ANTHROPIC_API_KEY` would be caught, but `MY_PROJ_SK` would not). Additionally, redaction occurs at display time — the raw output is streamed to the Socket.IO room before redaction filtering is applied, which could allow a race-condition observer to see unredacted output.

**Recommendation:** Apply redaction in the stream parser before emitting Socket.IO events (not after). Supplement name-pattern matching with a value-pattern scan (e.g., known secret formats: `sk-...`, `ghp_...`, AWS access key prefixes) as a secondary defense layer.

---

### LOW — No audit log for authentication events

**Location:** `server/auth.py`, `server/app.py`

**Detail:** Successful and failed login attempts are not logged in any persistent format. There is no mechanism to detect brute-force attempts, credential stuffing, or unauthorized access after the fact. Flask's development logger logs to stderr, which may or may not be persisted depending on deployment.

**Recommendation:** Add structured log lines for `LOGIN_SUCCESS`, `LOGIN_FAILURE` (with source IP and username), and `SESSION_START`/`SESSION_END`. In production (systemd deployment), these go to journald automatically; in Docker they go to the container log.

---

### LOW — ZIP archive import lacks explicit request-rate limit

**Location:** `server/app.py` (`/api/workspace/<id>/file-import` POST route)

**Detail:** The file import endpoint decompresses ZIP archives and validates total uncompressed size (bomb defense exists). However, there is no limit on how rapidly an authenticated client can submit import requests. Repeated large-ZIP imports could exhaust I/O or process bandwidth.

**Recommendation:** Apply Flask-Limiter or a simple session-based counter to restrict file import to a reasonable rate (e.g., 5 imports per minute per session).

---

### LOW — Trusted Socket.IO origin list includes wildcard-adjacent ngrok domains

**Location:** `server/app.py` (Socket.IO CORS origin configuration)

**Detail:** The allowed origin list includes `*.ngrok*` (or equivalent pattern). ngrok subdomains are user-controlled; any ngrok user can obtain a subdomain that matches this pattern and attempt to connect to a Bullpen instance. This is a low-severity concern because auth protects the application in production, but it broadens the effective CORS surface beyond the operator's own origin.

**Recommendation:** Document that `*.ngrok*` origin allowance should be disabled in production deployments (where a fixed HTTPS domain is known). Consider making the trusted tunnel domain list configurable rather than hardcoded.

---

## Positive Security Controls (No Action Required)

| Control | Implementation | Verdict |
|---|---|---|
| Password hashing | Werkzeug PBKDF2-SHA256, constant-time compare | Correct |
| Path traversal prevention | `ensure_within()` using `realpath` + `is_relative_to` | Correct |
| CSRF on login form | Session token, constant-time compare | Correct |
| Command injection prevention | `subprocess.run(args_list)`, no `shell=True` | Correct |
| MCP token security | `secrets.token_hex`, `chmod 600` on secrets.json | Correct |
| SRI hashes on CDN scripts | Verified on Vue, Socket.IO, markdown-it, Prism | Correct |
| Subprocess timeout + kill escalation | SIGTERM → SIGKILL with configurable timeout | Correct |
| Sandbox for HTML file preview | `<iframe sandbox>` on FilesTab | Correct |
| Auth required for non-localhost | Enforced at bind-time | Correct |
| Secrets redaction in shell output | ENV var name-pattern redaction | Partially correct (see findings) |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 3 |
| LOW | 3 |
