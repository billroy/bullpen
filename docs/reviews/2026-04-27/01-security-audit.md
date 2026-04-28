# Security Audit
*Bullpen — 2026-04-27*

---

## Executive Summary

Bullpen is a Flask + Flask-SocketIO web application that acts as an AI agent team manager, allowing users to configure AI worker agents (Claude, Codex, Gemini) and shell workers that execute arbitrary bash commands against a local workspace. The codebase demonstrates meaningful security engineering for a project of its size and maturity: path traversal protections are applied consistently, CSRF tokens guard login/logout, the Socket.IO handshake is origin-gated, password hashing delegates to Werkzeug (PBKDF2), and CDN-loaded scripts carry SRI integrity hashes. The MCP stdio server correctly redirects stdout to prevent framing corruption, and the Dockerfile enforces a non-root runtime user.

Despite those strengths, the threat model is materially widened by two architectural facts: shell workers execute arbitrary user-supplied bash commands in the same process-user context as the server, and AI agent subprocesses are spawned with no OS-level sandbox. An attacker who gains control of a task's prompt or a worker's configuration can instruct a shell or AI worker to perform actions with the same file-system and network privileges as the running server. This is not unique to Bullpen among agentic platforms, but the absence of sandboxing elevates several otherwise low-risk findings.

A secondary risk area is the supply chain: `requirements.txt` pins only six direct dependencies and includes no transitive-dependency pinning or automated vulnerability scanning. The Flask ecosystem (including eventlet, which has a history of CVEs) can introduce silent regressions at dependency-update time. A buyer should invest in `pip-audit` integration and a lock-file strategy before deploying Bullpen in a multi-user or internet-facing environment.

---

## Strengths

- **Path traversal protection** — `ensure_within()` in `server/persistence.py` uses `Path.is_relative_to()` on `os.path.realpath`-resolved paths, catching both `..` sequences and symlink escapes. It is applied consistently in `file_content`, `file_write`, and `_safe_extract_zip`.
- **Atomic writes** — `atomic_write()` uses `tempfile.mkstemp` + `os.replace`, preventing torn reads of JSON and frontmatter files.
- **PBKDF2 password hashing** — Werkzeug's `generate_password_hash` / `check_password_hash` default to PBKDF2-HMAC-SHA256 with a high iteration count and a per-hash salt. This is appropriate.
- **Credential file permissions** — `write_env_file()` in `auth.py` opens the file with `O_CREAT | 0o600` before writing, preventing the hash from ever being world-readable. `chmod 600` is also applied post-write to handle pre-existing files.
- **Flask SECRET_KEY persistence** — Generated once with `secrets.token_hex(32)` and stored in the same permission-restricted `.env` file, so sessions survive restarts without requiring a static env var.
- **Session fixation prevention** — `session.clear()` is called before setting `authenticated=True` in `login_submit()` (app.py line 451), preventing session fixation attacks.
- **CSRF on login and logout** — `secrets.compare_digest` is used for constant-time comparison; the token is seeded into the session before the login page is served.
- **Safe redirect validation** — `_is_safe_next()` rejects `//` and `://` patterns, preventing open redirects via the `next` parameter after login.
- **Socket.IO origin gating** — `_socketio_origin_allowed()` allows only loopback, same-origin, forwarded-origin, or explicitly configured `BULLPEN_ALLOWED_ORIGINS` values. Tunnel suffixes are not unconditionally trusted unless added to that env var.
- **Session cookies** — `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE=Lax`. `SESSION_COOKIE_SECURE=True` when `BULLPEN_PRODUCTION=1`.
- **Archive decompression defences** — Compression ratio capped at 100x, total uncompressed size capped at 200 MB, file count capped at 1 000, `..` components rejected, nested archives rejected, absolute paths rejected.
- **Input validation layer** — `server/validation.py` provides per-field length limits, enum allowlists, ID regex, and a 1 MB payload ceiling across all Socket.IO event handlers.
- **SRI on CDN scripts** — All `<script src>` tags in `static/index.html` carry `integrity="sha384-..."` and `crossorigin="anonymous"`, preventing CDN compromise from injecting arbitrary JS.
- **Prompt hardening / trust modes** — `server/prompt_hardening.py` provides `trusted`/`untrusted` mode distinction. Untrusted workers get `--strict-mcp-config` and `--disallowedTools` passed to the Claude CLI, and task/ticket content is wrapped in explicit `<<<< BEGIN UNTRUSTED_INPUT >>>>` blocks.
- **Secret masking in shell output** — Shell worker output filters lines containing TOKEN/PASSWORD/KEY field names before surfacing them to the UI.
- **MCP token isolation** — Each workspace receives a distinct `secrets.token_urlsafe(32)` MCP token written to `config.json`; the server performs ambiguity-detection (refuses if two workspaces share a token).
- **Non-root Docker user** — The Dockerfile creates a `bullpen` user (UID 1000) and drops privileges before the entrypoint runs.
- **Login throttling** — After five failures within a five-minute window the source IP (and username+IP pair) is blocked for 60 seconds.
- **ProxyFix in production** — When `BULLPEN_PRODUCTION=1`, Werkzeug's `ProxyFix` is applied with `x_proto=1, x_host=1`, enabling correct scheme/host reconstruction behind a reverse proxy.

---

## Findings

### HIGH — Agent subprocess execution: no OS-level sandboxing

**Description:** AI agent subprocesses (Claude, Codex, Gemini) are launched by `server/agents/*.py` via `subprocess` with no chroot, seccomp, cgroup, or container isolation. Shell workers execute user-supplied bash commands directly. Both run as the same OS user as the Flask server. A malicious or prompt-injected task can read and write arbitrary files accessible to that user, exfiltrate secrets, or make outbound network connections.

**Location:** `server/agents/base.py`, `server/agents/claude_adapter.py`, `server/workers.py` (runner), `server/service_worker.py`.

**Impact:** Full compromise of the server's filesystem and network access. In Docker the `bullpen` user's home and `/workspace` are accessible; on a bare-metal deployment the attacker gains the developer's full account access.

**Recommendation:** Run each agent subprocess inside a container or at minimum a separate OS user with a restricted filesystem view. For Docker deployments, consider `--cap-drop ALL` and read-only bind mounts for everything outside the workspace. Apply seccomp or AppArmor profiles. At a minimum, ensure the server user cannot read sensitive system files or SSH keys.

---

### HIGH — Login throttle state is in-process memory only; resets on restart

**Description:** `login_failures` is a plain dict inside the `create_app` closure (app.py line 286). After a server restart (crash, deploy, gunicorn worker recycle) all throttle state is lost, allowing an attacker to bypass the five-failure limit by triggering a restart or simply waiting for a normal redeploy.

**Location:** `server/app.py` lines 286–325.

**Impact:** Brute-force of credentials becomes feasible in any environment where the server restarts, including container orchestrators that restart unhealthy pods.

**Recommendation:** Persist throttle state to a shared backend (Redis, a small SQLite file, or the existing flat-file store with an atomic write). Alternatively implement exponential backoff with state stored in `~/.bullpen/` alongside credentials.

---

### HIGH — No Content-Security-Policy or security headers

**Description:** Neither the Flask app nor the Dockerfile/deployment configuration sets `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, or `Permissions-Policy` headers. The `lucide` icon library is loaded from `unpkg.com` without an SRI hash (only Vue, socket.io, markdown-it, and Prism carry SRI).

**Location:** `static/index.html` line 26 (`lucide` script tag); Flask response headers (no `after_request` hook setting security headers).

**Impact:** Absence of CSP means a successful XSS can exfiltrate session cookies and issue arbitrary Socket.IO commands (creating/modifying tickets, reading file content). `X-Frame-Options` absence allows clickjacking against the main app UI. Absence of `X-Content-Type-Options` enables MIME sniffing attacks in older browsers.

**Recommendation:** Add an `after_request` hook setting at minimum:
- `Content-Security-Policy: default-src 'self'; script-src 'self' <explicit CDN origins with hashes>; ...`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

Add an SRI hash to the `lucide` script tag or self-host it.

---

### HIGH — Dependency supply chain: no pinned transitive deps, no vulnerability scanning

**Description:** `requirements.txt` lists only six direct dependencies (`Flask`, `Flask-SocketIO`, `simple-websocket`, `websocket-client`, `eventlet`, `pytest`) without pinning transitive dependencies. There is no `pip-audit`, Dependabot, or Snyk integration. `eventlet` has historically carried CVEs (e.g. HTTP request smuggling). The Dockerfile installs `@anthropic-ai/claude-code`, `@openai/codex`, and `@google/gemini-cli` from npm at build time with no version pinning beyond what `npm install -g` resolves.

**Location:** `requirements.txt`, `Dockerfile` line 26.

**Impact:** A dependency with a known CVE or a supply-chain compromise of a transitive package can silently compromise all deployments. Undetected until an audit is performed manually.

**Recommendation:** Generate and commit a `pip-compile`-produced `requirements.lock` pinning all transitive dependencies. Add `pip-audit` to CI. Pin npm package versions in the Dockerfile. Enable Dependabot or Renovate for automated PR-based updates.

---

### MEDIUM — MCP token stored in world-readable `config.json`

**Description:** The MCP authentication token is written to `.bullpen/config.json` alongside non-sensitive workspace config. Unlike the credential file (which is `chmod 600`), `config.json` inherits default filesystem permissions (typically `644` on Linux). Any local user on the host can read this file and authenticate as the MCP client, gaining the ability to create and modify tickets.

**Location:** `server/mcp_auth.py` lines 54–55; `server/persistence.py` (`write_json` uses `atomic_write` which does not set restrictive permissions).

**Impact:** On a shared host, any local user can forge MCP connections and write tickets to arbitrary workspaces.

**Recommendation:** Apply `chmod 640` or `600` to `config.json` after writing (similar to how `write_env_file` handles `.env`), or store the MCP token separately in a permission-restricted file (e.g. `.bullpen/runtime.secret`).

---

### MEDIUM — No rate limiting on Socket.IO event handlers

**Description:** Socket.IO event handlers (task creation, worker configuration, file writes, archive import) have no per-connection or per-IP rate limiting. An authenticated client can flood the server with `task:create` or `worker:configure` events, exhausting disk space or CPU.

**Location:** `server/events.py`, `server/app.py` — no rate-limit middleware present.

**Impact:** Authenticated denial-of-service: a compromised session or a malicious MCP client can fill disk with task files or degrade server performance.

**Recommendation:** Apply a token-bucket or sliding-window rate limiter on high-volume Socket.IO events. Flask-Limiter or a custom `before_event` hook can accomplish this.

---

### MEDIUM — Zip import: no MIME type or magic-byte validation

**Description:** The archive import endpoints (`/api/import/workspace`, `/api/import/workers`, `/api/import/all`) rely entirely on `zipfile.BadZipFile` to detect non-ZIP uploads. There is no check of the `Content-Type` header, file extension, or magic bytes (`PK\x03\x04`) before opening the stream. While `_safe_extract_zip` validates internal paths and compression ratios, a crafted non-ZIP binary could exercise Python's ZIP parser in unexpected ways.

**Location:** `server/app.py` lines 986–1069.

**Impact:** Low severity in practice because `zipfile.ZipFile` is well-hardened, but defence-in-depth is missing and the attack surface of Python's ZIP parser is non-trivial.

**Recommendation:** Check `upload.content_type` or read the first four bytes and compare to `b'PK\x03\x04'` before passing the stream to `zipfile.ZipFile`.

---

### MEDIUM — `X-Forwarded-For` trusted without allowlisting trusted proxies

**Description:** `_client_ip()` (app.py line 289) reads `X-Forwarded-For` directly: `forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()`. When not behind a trusted reverse proxy, an attacker can spoof their IP by sending a forged `X-Forwarded-For` header, bypassing or manipulating per-IP login throttling.

**Location:** `server/app.py` lines 288–291.

**Impact:** An attacker running many login attempts from one real IP can evade the per-IP throttle by forging different `X-Forwarded-For` values on each request.

**Recommendation:** Only trust `X-Forwarded-For` when `BULLPEN_PRODUCTION=1` and `ProxyFix` is active (Werkzeug's `ProxyFix` normalizes this correctly). In development mode, fall back to `request.remote_addr` only.

---

### MEDIUM — No audit log for ticket mutations or worker actions

**Description:** There is no append-only log of who created, updated, moved, or deleted tickets, nor of when agent subprocesses were launched or what arguments were used. The in-memory `login_failures` dict is the only access-related state tracking.

**Location:** Entire `server/` backend.

**Impact:** In a multi-user deployment, it is impossible to attribute a destructive action (ticket deletion, workspace import overwrite) to a specific user session after the fact.

**Recommendation:** Emit structured log lines (JSON, append-only) to a file or syslog on all ticket mutations and subprocess launches. Include `username`, `session_id`, `action`, `workspace_id`, and a UTC timestamp.

---

### MEDIUM — Shell worker: no allowlist of permissible commands

**Description:** Shell worker `command` fields accept arbitrary bash, including `rm -rf`, network egress commands, and reading files outside the workspace. Secret masking (masking TOKEN/PASSWORD/KEY lines in output) provides display-level protection but does not prevent the bash process from exfiltrating data silently.

**Location:** `server/service_worker.py`, shell worker configuration.

**Impact:** A user with Bullpen access who configures a shell worker can exfiltrate secrets from the host environment or destroy workspace data.

**Recommendation:** Consider restricting shell workers to a configurable allowlist of commands, or at minimum run them in a restricted shell (`rbash`, Docker container, or a separate OS user without network access).

---

### LOW — Custom `.env` parser not tested against adversarial inputs

**Description:** `auth.py`'s `parse_env_file()` is a hand-rolled `KEY=VALUE` parser. It handles quoted values, blank lines, and `#` comments, but edge cases like multi-line values, Unicode edge cases, or values containing `=` after the first one (via `line.partition("=")`) are silently truncated rather than rejected. The parser is not fuzz-tested.

**Location:** `server/auth.py` lines 48–78.

**Impact:** A crafted `.env` file (e.g. manually edited by an operator) could result in credentials being silently mis-parsed, causing auth to be disabled or a wrong hash to be loaded. Low exploitability because the file is `chmod 600` and only local operators can write it.

**Recommendation:** Add targeted unit tests for adversarial inputs (values with `=`, trailing whitespace in keys, Unicode). Consider replacing with `python-dotenv` for battle-tested parsing once it is vetted for the dependency policy.

---

### LOW — HTTPS enforcement relies solely on `SESSION_COOKIE_SECURE`

**Description:** When `BULLPEN_PRODUCTION=1`, `SESSION_COOKIE_SECURE=True` prevents the cookie from being sent over HTTP. However, there is no `Strict-Transport-Security` (HSTS) header and no HTTP→HTTPS redirect enforced at the application layer. The `ProxyFix` middleware is applied, but only if the operator has set `BULLPEN_PRODUCTION=1`.

**Location:** `server/app.py` lines 254–262.

**Impact:** On an internet-facing deployment without a properly configured reverse proxy, sessions can be downgraded to HTTP, exposing the session cookie.

**Recommendation:** Add `Strict-Transport-Security: max-age=63072000; includeSubDomains` to the response headers when `BULLPEN_PRODUCTION=1`. Document that the reverse proxy must enforce HTTPS.

---

### LOW — `lucide` loaded from unpkg without SRI

**Description:** `static/index.html` line 26 loads `https://unpkg.com/lucide@latest/dist/umd/lucide.min.js` with `@latest` resolution and no `integrity` attribute. CDN compromise or a future version of `lucide` could inject arbitrary JavaScript.

**Location:** `static/index.html` line 26.

**Impact:** If unpkg or the lucide package is compromised, arbitrary JavaScript runs in the user's browser session with access to the Socket.IO connection and all application state.

**Recommendation:** Pin to a specific version (e.g. `lucide@0.x.y`), compute its SHA-384, and add `integrity="sha384-..."` and `crossorigin="anonymous"`. Or self-host the asset.

---

### LOW — `health` endpoint unauthenticated

**Description:** `GET /health` returns `{"ok": true}` without authentication. While benign in isolation, it confirms the server is alive and its version to unauthenticated clients, aiding reconnaissance.

**Location:** `server/app.py` lines 401–403.

**Impact:** Minimal; primarily an information-disclosure finding in a hardened deployment.

**Recommendation:** Gate `/health` behind a simple token or IP allowlist in production, or accept the risk and document it.

---

### LOW — Git operations expose commit author and email in API response

**Description:** `/api/commits` returns the `author` field directly from `git log --format=%an` (author name). Full author email is not included, but commit subject lines and bodies can contain arbitrary text, including anything an AI agent wrote to the commit message.

**Location:** `server/app.py` lines 494–533.

**Impact:** Low; author names are typically not sensitive, and the endpoint is behind `@require_auth`.

**Recommendation:** No immediate action required. Ensure the API is not inadvertently exposed to unauthenticated users if the auth guard is ever conditionally removed.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 4     |
| MEDIUM   | 5     |
| LOW      | 5     |

---

## Recommendations

Listed in priority order for a buyer's first 90 days:

1. **[HIGH] Implement agent/shell sandbox** — Run AI subprocesses and shell workers in isolated containers or OS-user jails with minimal filesystem and network access. This is the highest-impact architectural change.
2. **[HIGH] Add security response headers** — Add CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` via a Flask `after_request` hook. Pin and add SRI to the `lucide` CDN script.
3. **[HIGH] Persist login throttle state** — Move `login_failures` to a durable backend (Redis, SQLite, or flat file) so brute-force protection survives restarts.
4. **[HIGH] Establish dependency lock and vulnerability scanning** — Commit a `requirements.lock` from `pip-compile`, add `pip-audit` to CI, and pin npm package versions in the Dockerfile.
5. **[MEDIUM] Restrict `config.json` permissions** — Apply `chmod 600` to workspace `config.json` files to protect the MCP token from local-user reads.
6. **[MEDIUM] Rate-limit Socket.IO events** — Apply per-session or per-IP rate limits on event handlers, especially archive import and task creation.
7. **[MEDIUM] Add audit logging** — Log all ticket mutations and subprocess launches with user, workspace, and timestamp to an append-only file.
8. **[MEDIUM] Fix `X-Forwarded-For` IP trust** — Only use the forwarded IP when behind a verified proxy (i.e. when `BULLPEN_PRODUCTION=1` and ProxyFix is active).
9. **[LOW] Enforce HTTPS / add HSTS** — Add `Strict-Transport-Security` when in production mode and document reverse-proxy HTTPS requirement.
10. **[LOW] Pin and add SRI to `lucide`** — Replace `@latest` with a specific pinned version and add an integrity hash.
