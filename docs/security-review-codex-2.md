# Security Review — codex-2

Date: 2026-04-21
Reviewer: Codex
Scope: Repository security review of the current codebase, focused on browser trust boundaries, authentication, cross-workspace isolation, file handling, and worker execution surfaces.

## Executive Summary

The project has a noticeably stronger baseline than a typical local orchestration tool:

- HTTP routes are generally gated by auth.
- File-path traversal defenses are present in the file and task APIs.
- Zip import extraction defends against `..` and absolute-path escapes.
- Shell and service workers use explicit `argv` execution and strip inherited secret-like environment variables.

The highest remaining risks are not in the low-level file handling. They are in the trust model:

1. Browser-origin trust is too broad for Socket.IO.
2. Workspace HTML files can execute as Bullpen-origin code.
3. MCP authentication is shared across all workspaces and persists in workspace config.
4. Untrusted ticket/chat/workspace text is passed directly to high-privilege agents.
5. Clients are given more cross-workspace visibility than they need.

## Findings

### 1. High: Broad trusted-tunnel origin allowlist enables cross-site Socket.IO control of local Bullpen instances

Affected code:

- `server/app.py:50-51`
- `server/app.py:76-90`
- `server/app.py:775-804`

What happens:

- `_socketio_origin_allowed()` accepts any origin whose hostname ends with `.ngrok-free.app`, `.ngrok.app`, `.ngrok.io`, or `.sprites.app`, even when that origin is unrelated to the running Bullpen instance.
- When auth is disabled, `on_connect()` accepts the connection and immediately joins the client to all active workspace rooms and sends full workspace state.
- When auth is enabled, the session gate helps, but the event layer still has no independent per-message CSRF defense; once a cross-origin handshake is accepted, subsequent Socket.IO events are trusted.

Why this matters:

- A malicious page hosted on any attacker-controlled ngrok or sprites domain can attempt a cross-site Socket.IO connection into a developer’s local Bullpen instance.
- Because Bullpen commonly runs in local-dev mode with auth disabled, this creates a realistic browser-driven control path against the local app.

Impact:

- Unauthorized task creation or mutation.
- Worker start/stop actions.
- Project enumeration and state disclosure.

Recommendation:

- Remove the unconditional suffix allowlist.
- Allow only exact same-origin and loopback by default.
- If tunnel support is needed, require an explicit configured allowed origin list for that session.

### 2. High: Opening workspace HTML files executes untrusted repo content in Bullpen’s origin

Affected code:

- `static/components/FilesTab.js:260-266`
- `server/app.py:393-425`

What happens:

- Clicking an `.html` file calls `window.open('/api/files/...?...&raw=1', '_blank')`.
- The backend serves that file directly with `send_file()` and the guessed HTML MIME type.

Why this matters:

- A workspace is often untrusted input.
- If a repository contains hostile HTML/JS, Bullpen serves it from the Bullpen origin, not from an isolated origin.
- That page can run with access to Bullpen-origin cookies and same-origin requests.

Impact:

- Session theft or action forgery against the Bullpen app.
- Full compromise of the active Bullpen browser session through a malicious file in the workspace.

Recommendation:

- Do not open workspace HTML as live same-origin documents.
- Serve raw HTML as download-only, or from a separate isolated preview origin.
- For this local tool, the lowest-friction safe fix is to keep preview in a sandboxed iframe using `srcdoc`; a separate preview origin is stronger but likely unnecessary unless the app moves toward shared/hosted use.

### 3. High: One MCP token is reused across all workspaces, so compromise of one workspace’s token grants cross-workspace agent access

Affected code:

- `server/app.py:174-205`
- `server/app.py:775-804`
- `server/events.py:227-233`

What happens:

- `create_app()` reuses a single `mcp_token` across every active workspace and writes that same token into each workspace’s `.bullpen/config.json`.
- A Socket.IO client that presents that token is accepted as MCP-authenticated and then joined to all workspace rooms.
- The reuse loop also makes the token effectively persistent across restarts until it is manually replaced.

Why this matters:

- The token is effectively a bearer credential.
- Any process that can read one workspace’s `.bullpen/config.json` gets a credential valid for every active workspace handled by that Bullpen server.
- That breaks workspace isolation and turns a single-workspace compromise into a multi-workspace compromise.

Impact:

- Cross-workspace task manipulation and state access by any local process or imported content that obtains one token.

Recommendation:

- Mint a distinct MCP token per workspace.
- Bind each token to exactly one workspace ID during Socket.IO auth.
- Do not auto-join MCP clients to all workspace rooms.
- Add an explicit rotation path, or at minimum a CLI/admin mechanism to rotate tokens on demand.

### 4. Medium: Workspace export/import preserves runtime connection secrets and trusts imported runtime config

Affected code:

- `server/app.py:498-508`
- `server/app.py:548-558`
- `server/app.py:604-614`

What happens:

- Workspace and all-workspace exports include `.bullpen/config.json`.
- That file currently carries runtime transport metadata such as `server_host`, `server_port`, and `mcp_token`.
- Workspace import replaces the destination `.bullpen` directory wholesale.

Why this matters:

- Exports unnecessarily package live runtime credentials/config.
- Imports can reintroduce stale or hostile runtime metadata until Bullpen rewrites it later.
- This is especially risky because the same token is reused across workspaces today.

Impact:

- Secret leakage through exported archives.
- Confused-deputy behavior after importing a crafted workspace archive.

Recommendation:

- Exclude runtime-only keys from export archives.
- After any import, immediately rewrite runtime connection fields from the live server state.
- Keep bearer tokens out of portable workspace state entirely.

### 5. High: Untrusted user and workspace inputs are passed directly to high-privilege agents without trust separation

Affected code:

- `server/workers.py:850-903`
- `server/events.py:1532-1565`
- `server/validation.py:107-145`
- `server/agents/claude_adapter.py:70-84`
- `server/agents/codex_adapter.py:50-89`
- `server/agents/gemini_adapter.py:69-77`

What happens:

- Worker prompts are assembled by concatenating `workspace_prompt.md`, `bullpen_prompt.md`, worker `expertise_prompt`, ticket title, tags, and raw ticket body directly into one model prompt.
- Live chat builds prompts by concatenating prior conversation turns and the latest raw user message directly into the assistant prompt.
- Validation limits size, but it does not meaningfully distinguish trusted instructions from untrusted content.
- The downstream agent CLIs are then launched in highly permissive modes:
  - Claude with `--dangerously-skip-permissions`
  - Codex with `--full-auto` or `--dangerously-bypass-approvals-and-sandbox`
  - Gemini with `--approval-mode yolo`

Why this matters:

- This is a prompt-injection risk, not a simple string-sanitization bug.
- A malicious ticket body, chat message, workspace prompt, or agent-produced content copied back into tickets can try to override higher-level instructions and steer the agent into dangerous actions.
- Because these agents are allowed to read/write files, call MCP tools, and in some cases auto-commit or auto-open PRs, successful instruction hijacking can cross the boundary from “bad model behavior” into real host and repository impact.

Impact:

- Unauthorized file reads or modifications within the workspace.
- Malicious or misleading ticket updates through MCP tools.
- Destructive git actions, bad commits, or unwanted PR automation.
- Increased risk of secret disclosure from accessible local files or repo state.

Recommendation:

- Treat ticket bodies, chat messages, workspace files, and other repo-controlled text as untrusted data by default.
- Delimit untrusted content explicitly in prompts and tell agents not to treat it as instructions.
- Add a per-worker trust mode:
  - trusted automation mode for tightly controlled inputs
  - untrusted/review mode with safer agent flags and no autonomous destructive actions
- Disable auto-commit/auto-PR and other high-impact follow-on actions when prompts include untrusted content, unless explicitly opted in.
- Prefer stronger runtime isolation over text filtering: sandboxed agents, scoped tool access, and narrower MCP permissions are more reliable than trying to “sanitize” prompt text.

### 6. Medium: Zip import size checks do not defend against high-expansion zip bombs

Affected code:

- `server/app.py:52`
- `server/app.py:568-586`

What happens:

- `_MAX_IMPORT_ARCHIVE_BYTES` caps the summed `ZipInfo.file_size` values at 200 MB during extraction.
- That is better than limiting only the compressed archive size, but there is still no decompression-ratio limit, file-count limit, or nested-archive policy.

Why this matters:

- A crafted archive can still impose heavy CPU, disk, or inode pressure during import.
- This is primarily an availability risk rather than a confidentiality or integrity break.

Impact:

- Import-driven denial of service against the local app or host workspace storage.

Recommendation:

- Enforce file-count limits and a maximum expansion ratio in addition to total extracted bytes.
- Reject nested archives unless explicitly needed.

### 7. Medium: Authenticated and MCP clients receive all workspace state and absolute project paths by default

Affected code:

- `server/app.py:793-804`
- `server/workspace_manager.py:225-236`
- `server/events.py:956-957`
- `server/events.py:1106-1109`

What happens:

- On connect, Bullpen joins the client to every active workspace room.
- It sends `state:init` for every workspace.
- `projects:updated` includes the full project registry entries, including absolute filesystem paths.

Why this matters:

- Even if you trust all current users, this is broader disclosure than necessary.
- Combined with the shared MCP token, this makes cross-workspace visibility automatic instead of explicit.
- This is less urgent than the browser-origin and HTML-execution issues because it mostly affects already-connected clients, but it still expands blast radius.

Impact:

- Unnecessary leakage of host filesystem layout.
- Larger blast radius for any compromised client.

Recommendation:

- Send only the startup or explicitly selected workspace on initial connect.
- Redact project paths from normal client payloads unless the UI truly needs them.
- Require explicit authorization and room join before sending workspace state.

### 8. Low: Login flow has no brute-force throttling, and logout remains CSRF-able via GET

Affected code:

- `server/app.py:269-304`

What happens:

- Failed login attempts are not rate-limited, delayed, or locked out.
- `/logout` accepts `GET`, which permits cross-site logout requests.

Why this matters:

- Bullpen now supports network-bound authenticated deployments, so the login endpoint is part of the attack surface.
- These are not catastrophic issues, but they are easy hardening wins.

Impact:

- Easier online password guessing.
- Forced logout nuisance attacks.

Recommendation:

- Add per-IP and per-username backoff/rate limiting on `/login`.
- Make logout `POST`-only and CSRF-protected.

## Positive Controls

- `server/persistence.py:31-37` has a solid `ensure_within()` path-boundary check.
- `server/app.py:568-586` validates imported zip paths before extraction.
- `server/workers.py:490-535` and `server/service_worker.py:49-73` minimize inherited environment variables and strip secret-like names.
- `server/auth.py` uses hashed passwords and rotates the session on successful login.

## Actionable Remediation Plan

### Immediate

1. Tighten Socket.IO origin checks to exact same-origin and loopback only.
2. Stop opening workspace HTML files as same-origin live documents.
3. Remove `mcp_token`, `server_host`, and `server_port` from workspace export payloads.
4. Rewrite runtime config immediately after any workspace import.
5. Replace the global MCP token with per-workspace tokens.

### Near-Term

1. Change initial Socket.IO connect behavior to send only one selected workspace.
2. Redact absolute project paths from standard client payloads.
3. Introduce an explicit untrusted-input agent mode with safer defaults, clear prompt delimiting, and reduced autonomous actions.
4. Add login throttling and make logout `POST`-only.
5. Add regression tests for:
   - rejecting unrelated ngrok/sprites origins
   - preventing same-origin HTML execution paths
   - per-workspace MCP token scoping
   - import/export stripping runtime secrets
   - untrusted prompt content preserving system/tool instructions
   - zip-bomb rejection and extraction limits

### Later

1. Introduce explicit per-user authorization if Bullpen is going to be shared by multiple people.
2. Consider a dedicated isolated preview origin for potentially active content.
3. Separate portable workspace state from live server runtime state everywhere, not just in export/import flows.
4. Move agent execution toward stronger isolation and narrower default tool permissions for untrusted tasks.

## Suggested Fix Order

1. Socket.IO origin tightening
2. HTML-file execution isolation
3. Export/import secret stripping and runtime rewrite
4. Per-workspace MCP tokenization
5. Untrusted-input agent hardening
6. Cross-workspace visibility reduction
7. Login/logout hardening
8. Zip-import hardening

## Review Notes

- This review was static/source-based. I did not run the full test suite as part of the review.
