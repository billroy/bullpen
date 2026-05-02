# Bullpen Security Review 2

Date: 2026-05-02

Scope: deep source review of the Flask/Socket.IO Bullpen app, with emphasis on authentication, browser/API trust boundaries, workspace file access, import/export, MCP access, worker execution, deployment defaults, dependency posture, and existing security tests.

## Executive Summary

Bullpen has moved beyond the earlier "local prototype" security baseline. Notable improvements include optional password auth, network-bind refusal without credentials, Socket.IO origin checks, per-workspace MCP tokens stored outside `.bullpen/config.json`, HTML raw-file attachment handling, ZIP import limits, shell/service cwd containment, and tests for many of those controls.

The dominant remaining risk is not a simple path traversal or unauthenticated route. It is the product's core power: an authenticated Bullpen session can read and write workspace files, register arbitrary local projects, clone remote repos, import worker configurations, and start shell/service/AI processes. That is reasonable for a single-user local automation tool, but it is high-risk for hosted, shared, tunneled, or team use.

Overall posture:

- Local single-user on `127.0.0.1`: acceptable with documented trust assumptions.
- LAN/tunnel/sprite/small-team deployment: high risk unless CSRF/origin policy, execution policy, and project path controls are tightened.
- Multi-user or hostile-workspace environment: not ready. Needs authorization, isolation, and audit boundaries before being treated as a shared service.

## Key Strengths

- Network binds are refused unless auth is configured: `bullpen.py:460-475`.
- Passwords are hashed with Werkzeug helpers; sessions are cleared on login; login and logout use CSRF tokens: `server/auth.py`, `server/app.py:450-488`.
- Socket.IO CORS is not wildcard by default and rejects unrelated tunnel origins: `server/app.py:351-357`, `tests/test_socketio_cors.py`.
- MCP tokens are workspace-scoped and stored in `~/.bullpen/secrets.json`, not exported in `.bullpen/config.json`: `server/mcp_auth.py`, `tests/test_mcp_auth.py`.
- Workspace file reads/writes use `ensure_within()` and raw HTML is served as an attachment: `server/app.py:586-640`, `tests/test_files_api_html_security.py`.
- ZIP import rejects path traversal, absolute path forms, nested archives, high expansion, excessive size, and excessive file count: `server/app.py:752-820`, `tests/test_export_import_api.py`.
- Shell and service workers resolve cwd under the workspace and strip secret-like inherited environment variables: `server/workers.py:943-984`, `server/service_worker.py:143-162`.

## Findings

### P1: Authenticated HTTP mutating routes lack CSRF/origin protection

Evidence:

- File writes, worker transfer, imports, and service preview are normal HTTP POST/PUT routes protected only by `@auth.require_auth`: `server/app.py:623-650`, `server/app.py:651-692`, `server/app.py:953-1005`, `server/app.py:1007-1088`.
- CSRF validation is currently applied to login/logout, not to the general API surface: `server/app.py:450-488`.

Impact:

If a browser has an authenticated Bullpen session, another same-site origin, misconfigured proxy, browser extension, compromised local page, or future relaxation of `SameSite`/cookie rules can drive state-changing operations. The most sensitive target is `/api/files/<path>` because it can write workspace code; imports can replace `.bullpen` worker state; transfer can alter worker topology.

Risk is mitigated by `SameSite=Lax`, but not eliminated. Relying on cookie SameSite alone is weaker than explicit CSRF/origin checks for a tool that can write code and start processes.

Remediation:

- Require `X-CSRF-Token` on every non-GET HTTP route when auth is enabled.
- Expose a general `/api/csrf` endpoint or include the token in initial state.
- Reject mutating requests with missing/untrusted `Origin` or `Referer` when a browser origin is present.
- Add tests for PUT `/api/files`, POST `/api/import/*`, and POST `/api/worker/transfer` without/with valid CSRF.

### P1: Authenticated users can register or create arbitrary local project paths

Evidence:

- `project:add` accepts a client-supplied filesystem path and calls `manager.register_project(path)`: `server/events.py:1110-1126`.
- `project:new` creates a client-supplied absolute path when it does not exist: `server/events.py:1128-1165`.
- `project:clone` can clone a remote URL into a client-supplied absolute path: `server/events.py:1167-1215`.
- `WorkspaceManager.register_project()` only checks that the resolved path is a directory and that the textual absolute path has no `..`: `server/workspace_manager.py:120-164`.

Impact:

Any authenticated browser session can expand Bullpen's workspace scope to any directory readable/writable by the Bullpen process, then use the file API and workers against that directory. In local single-user use, this is expected. In a hosted/shared deployment, it is a privilege boundary break: a user with UI access can point Bullpen at home directories, mounted secrets, deployment directories, or other users' projects.

Remediation:

- Add an allowlisted project root, for example `BULLPEN_PROJECT_ROOTS=/workspace,/repos`, and reject project add/new/clone outside those roots.
- Consider disabling `project:add` and absolute-path `project:new` in production unless explicitly enabled.
- For Docker, default all project creation/cloning under `/workspace`.
- Add tests for rejecting `/`, `$HOME`, `/etc`, sibling directories, and symlink escapes outside configured roots.

### P1: Worker configuration is an authenticated arbitrary command execution surface

Evidence:

- Worker configure admits type-specific and unknown fields after only shallow filtering: `server/validation.py:185-265`.
- `worker:configure` writes those fields into persisted worker layout: `server/events.py:865-889`.
- Shell workers execute configured command strings via `/bin/sh -c`: `server/workers.py:996-1014`.
- Service workers execute configured command strings via `/bin/sh -c`: `server/service_worker.py:867-877`.
- Imported worker archives merge worker slots and profiles into live state: `server/app.py:1033-1057`.

Impact:

This is mostly by design, but it should be treated as a security boundary. Anyone who can configure or import a worker can create a command that executes with the Bullpen process user's filesystem and network permissions. In Docker, that includes mounted provider credentials if the user opted into those mounts.

Remediation:

- In production/shared mode, gate shell/service workers behind an explicit capability flag and UI confirmation.
- Add a worker execution policy model separate from `trust_mode`, for example `manual-command`, `restricted`, `full`.
- Require confirmation before importing workers containing `type: shell` or `type: service`, `pre_start`, `health_command`, custom `env`, or auto actions.
- Replace the permissive unknown-field pass-through with type-specific schemas for persisted runtime-affecting fields.

### P1: AI worker defaults intentionally bypass provider safety prompts and sandboxing

Evidence:

- Claude uses `--dangerously-skip-permissions`: `server/agents/claude_adapter.py:86-100`.
- Codex uses `--full-auto` by default, or `--dangerously-bypass-approvals-and-sandbox` when `BULLPEN_CODEX_SANDBOX` is disabled: `server/agents/codex_adapter.py:50-88`.
- Gemini uses `--approval-mode yolo`: `server/agents/gemini_adapter.py:69-78`.
- Docker sets `BULLPEN_CODEX_SANDBOX=none`: `Dockerfile:8-13`.

Impact:

Untrusted tickets, repository files, imported worker prompts, and model output can drive agents that have broad file and shell capabilities. Prompt hardening helps, but it cannot be the primary control for malicious workspaces or hostile tickets.

Remediation:

- Default untrusted workers to provider modes that require approval or restrict shell/filesystem operations where possible.
- Make broad bypass modes explicit per worker and visible in the card/config UI.
- Convert provider approval/sandbox failures into a first-class blocked state with a "rerun with broader permissions" action.
- Remove `BULLPEN_CODEX_SANDBOX=none` from the Docker default or document it as an unsafe development profile.

### P2: Docker exposes a service port to the host by default

Evidence:

- Dockerfile exposes both Bullpen and app ports: `Dockerfile:8-13`.
- Compose publishes `${APP_PORT}` to the host: `docker-compose.yml:15-17`.
- Optional app service runs `npm run dev -- --host 0.0.0.0`: `docker-compose.yml:32-40`.

Impact:

The app port is not Bullpen-authenticated. If a service worker or app binds to `0.0.0.0`, it may expose a development server to the host/LAN depending on Docker and firewall settings. That dev server can have its own vulnerabilities and may serve workspace content.

Remediation:

- Do not publish `APP_PORT` by default; make it an opt-in profile.
- Prefer binding preview apps to loopback or a reverse proxy that can add auth.
- Document that service workers can expose unauthenticated dev apps.

### P2: CDN dependency loading lacks a complete supply-chain policy

Evidence:

- Most CDN assets use SRI, but `lucide@latest` is loaded without a pinned version or SRI: `static/index.html:9-31`.
- Runtime images install latest global CLIs at build time: `Dockerfile:18-27`.
- Python dependencies are pinned but not hash-pinned: `requirements.txt`.

Impact:

Supply-chain compromise or unexpected upstream changes can execute code in Bullpen's authenticated origin. Because the UI can write files and start workers, frontend dependency compromise has high impact.

Remediation:

- Vendor frontend dependencies or pin every CDN URL to exact versions with SRI, including lucide.
- Pin global CLI package versions in Docker or build from a lockfile.
- Consider pip hash checking for production builds.

### P2: Imported workspace/worker state can activate dangerous behavior after user action

Evidence:

- Workspace import replaces `.bullpen` state wholesale after safe extraction: `server/app.py:1007-1031`.
- Workers import merges layout slots and profile files: `server/app.py:1033-1057`.
- Runtime tokens are preserved/replaced safely, but worker command content is trusted as configuration.

Impact:

A crafted export can plant shell/service workers, AI worker prompts, scheduled triggers, watch columns, or env settings. Some of these require later user action or scheduled activation, but the review flow is currently not security-aware.

Remediation:

- Show an import risk summary before applying: counts of shell/service/AI workers, scheduled triggers, command fields, auto-commit/auto-pr, env vars, and profiles.
- Default imported executable workers to paused/manual until explicitly enabled.
- Add schema validation and normalization for imported profile JSON and layout JSON.

### P2: No per-user authorization model

Evidence:

- Auth stores multiple users, but sessions only carry `username`; there are no roles or per-workspace access checks.
- Project lists deliberately hide filesystem paths from the UI, but all authenticated browser users can join any active workspace room and operate on it: `server/events.py:1088-1108`.

Impact:

Multiple configured users are equivalent administrators. That is fine if "multi-user" means shared password convenience, but unsafe if deployed for a team or customers.

Remediation:

- Document all users as full admins until RBAC exists.
- Before team/shared deployment, add per-user workspace membership and action permissions.
- Separate read-only project view from execution/file-write/admin capabilities.

### P3: Health endpoint is public

Evidence:

- `/health` is unauthenticated: `server/app.py:422-424`.

Impact:

Low. It leaks service presence and can be used for basic scanning, but it does not expose workspace state. Public health checks are common for deployments.

Remediation:

- Keep as-is for platform health checks, or make detailed health private if more data is added later.

## Prioritized Remediation Plan

### Immediate: 1-2 days

1. Add CSRF/origin enforcement to all mutating HTTP routes.
2. Pin or vendor `lucide`, and remove `@latest` frontend dependencies.
3. Update Docker defaults so `APP_PORT` is opt-in and `BULLPEN_CODEX_SANDBOX=none` is not the default safe path.
4. Add prominent docs that every authenticated user is a full administrator and that shell/service/AI workers execute code with Bullpen's OS permissions.

### Short Term: 1 week

1. Add project-root allowlisting and production defaults for `project:add`, `project:new`, and `project:clone`.
2. Add an import risk preview and default executable imported workers to paused/manual.
3. Replace permissive unknown worker config persistence with type-specific schemas.
4. Add tests for CSRF on HTTP APIs, project-root rejection, executable import risk handling, and Docker config expectations.

### Medium Term: 2-4 weeks

1. Introduce worker execution policy separate from prompt `trust_mode`.
2. Default untrusted AI workers to restricted/approval-preserving provider modes where feasible.
3. Add a blocked-and-rerun workflow for actions that need broader execution permissions.
4. Add audit events for project registration, import, worker command changes, service starts, shell starts, file writes, auto-commit, and auto-PR.

### Longer Term: Before Shared/Multi-User Use

1. Add per-user workspace authorization and roles.
2. Run workers in isolated OS/container sandboxes with scoped mounts and network policy.
3. Separate Bullpen control plane from preview/dev app origins.
4. Create a production security checklist and fail closed when unsafe combinations are detected.

## Suggested Security Test Additions

- HTTP CSRF tests for `/api/files/<path>` PUT, `/api/import/workspace`, `/api/import/workers`, `/api/import/all`, and `/api/worker/transfer`.
- Project path tests covering configured root allowlist, symlink escapes, absolute paths outside roots, and Docker `/workspace` expectations.
- Import tests that flag or pause shell/service workers, scheduled triggers, and command fields.
- Frontend supply-chain test that rejects unpinned CDN URLs and missing SRI.
- Worker execution policy tests confirming untrusted workers cannot enable auto-commit/auto-pr or bypass modes without explicit policy.

## Bottom Line

Bullpen is defensible as a powerful local single-user automation console. The next security step is to make that trust model explicit in code: authenticated users are admins, worker commands are code execution, and project registration is filesystem scope expansion. If Bullpen is going to be exposed beyond localhost, the top priorities are CSRF/origin protection, project-root restrictions, safer Docker exposure, and explicit execution policies.
