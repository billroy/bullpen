# Implementation Plan — Security Review codex-2

**Created:** 2026-04-21  
**Source:** `docs/security-review-codex-2.md`

---

## Goal

Turn the current security review into an implementation sequence that reduces the highest-risk trust-boundary issues first, without breaking Bullpen's core local workflow.

This plan assumes:

- the review findings in `security-review-codex-2.md` are accepted,
- no broad additional security review is required before coding,
- a few targeted design choices can be resolved inside the implementation effort.

---

## Delivery Strategy

Order work by:

1. browser-to-app compromise paths first,
2. secret leakage reduction second,
3. credential/isolation refactors third,
4. agent-behavior hardening next,
5. UX-sensitive scoping changes after the security-critical fixes.

This keeps the highest-risk issues moving immediately while avoiding a large all-at-once refactor.

---

## Progress

- Tranche 1: Completed on 2026-04-21
- Tranche 2: Completed on 2026-04-21
- Tranche 3: Completed on 2026-04-21
- Tranche 4: Pending
- Tranche 5: Pending
- Tranche 6: Pending
- Tranche 7: Pending

---

## Tranche 1 — Close Browser-Origin Attack Paths

**Goal:** Remove the easiest browser-driven compromise routes.
**Status:** Completed on 2026-04-21

Implemented:

- Socket.IO origin checks now allow only loopback, exact same-origin, and exact origins from `BULLPEN_ALLOWED_ORIGINS`.
- HTML files no longer open in a separate same-origin window from the Files tab.
- Raw HTML downloads are served as attachments rather than inline executable pages.
- Added regression coverage for the stricter origin policy and safe HTML handling.

### T1.1 Tighten Socket.IO allowed origins

- **Files:** `server/app.py`, `tests/test_socketio_cors.py`
- Replace the unconditional trusted-suffix allowlist with:
  - exact same-origin,
  - loopback origins,
  - optional explicit allowlist from config or env (recommended: `BULLPEN_ALLOWED_ORIGINS`)
- Preserve forwarded-host behavior for reverse-proxy deployments, but only for the configured Bullpen origin.

### T1.2 Keep event-layer trust dependent on accepted origins only

- **Files:** `server/app.py`, `server/events.py`
- Do not add a second per-event CSRF system in this tranche.
- Instead, ensure the handshake origin policy is strict enough that cross-origin event streams cannot start in the first place.
- Add comments/tests documenting that the Socket.IO session is trusted only after a validated handshake.

### T1.3 Stop opening workspace HTML as live Bullpen-origin documents

- **Files:** `static/components/FilesTab.js`, `server/app.py`, optional `tests/test_frontend_*`
- Recommended implementation:
  - remove `window.open(...raw=1)` for `.html` / `.htm`,
  - keep HTML preview inside the existing sandboxed iframe path,
  - add an explicit “Download/Open Raw” behavior only if needed, but not same-origin execution.
- If a raw route remains, force `Content-Disposition: attachment` for HTML rather than inline rendering.

### T1.4 Verification

- Add/adjust tests for:
  - unrelated `*.ngrok*` / `*.sprites.app` origins rejected,
  - same-origin still accepted,
  - HTML files no longer open as active same-origin pages.

**Checkpoint:** run targeted auth/origin/file-view tests, then full test suite.

---

## Tranche 2 — Remove Runtime Secrets From Portable Workspace State

**Goal:** Stop leaking live connection metadata through export/import and workspace files.
**Status:** Completed on 2026-04-21

Implemented:

- Workspace and all-workspace exports now strip runtime-only config keys from archived `config.json`.
- Workspace import paths now restamp live runtime metadata instead of trusting imported transport settings.
- Added regression coverage for sanitized exports and runtime rewrite after import.

### T2.1 Filter runtime-only config keys on export

- **Files:** `server/app.py`, `tests/test_export_import_api.py`
- Introduce a helper that derives an export-safe config object.
- Strip at least:
  - `mcp_token`
  - `server_host`
  - `server_port`
- Review any future runtime-only keys and keep them out of exported archives by default.

### T2.2 Rewrite runtime config immediately after import

- **Files:** `server/app.py`, `server/events.py`, `tests/test_export_import_api.py`
- After `import_workspace`, `import_workers`, and `import_all`, rewrite runtime metadata from the live server state instead of trusting imported values.
- Reuse a single helper for “stamp runtime config into workspace”.

### T2.3 Verification

- Add tests confirming:
  - exported workspace zips do not contain live runtime secrets,
  - imported workspaces get the current runtime metadata, not archive-provided values.

**Checkpoint:** run export/import tests and full test suite.

---

## Tranche 3 — Per-Workspace MCP Authentication

**Goal:** Restore workspace isolation for MCP-authenticated clients.
**Status:** Completed on 2026-04-21

Implemented:

- Added a dedicated `server/mcp_auth.py` helper so workspace runtime config stamping, token lookup, and rotation all use one code path.
- Replaced the shared MCP token bootstrap with distinct per-workspace tokens, including duplicate-token cleanup when active workspaces are stamped.
- Socket.IO MCP auth now resolves a token to exactly one workspace and sends only that workspace's `state:init` payload.
- MCP-authenticated sockets now stay scoped to their bound workspace and cannot use `project:join` or project-management events to widen access.
- Added a CLI rotation path via `bullpen mcp-token rotate --workspace <path>`.
- Preserved existing workspace tokens during import flows unless a collision forces replacement.
- Added regression coverage for workspace scoping, rotated-token invalidation, distinct project tokens, and the new CLI behavior.

### T3.1 Generate and persist distinct tokens per workspace

- **Files:** `server/app.py`, `server/events.py`, `server/mcp_tools.py`, `tests/test_mcp_tools.py`, `tests/test_events.py`
- Replace the current shared-token bootstrapping logic with per-workspace tokens stored only for that workspace.
- Keep token lookup and refresh centralized.

### T3.2 Bind MCP auth to a single workspace

- **Files:** `server/app.py`, `server/mcp_tools.py`
- Socket.IO MCP auth should resolve to exactly one workspace ID.
- MCP clients should join only that workspace room, not every workspace room.

### T3.3 Add token rotation support

- **Files:** likely `bullpen.py`, possibly `server/auth.py` or a small helper module, tests in `tests/test_cli_security.py` / `tests/test_mcp_tools.py`
- Add an admin/CLI path to rotate a workspace token on demand.
- Rotation can be manual-only for now; automatic cadence is not required in this tranche.

### T3.4 Verification

- Tests should prove:
  - a token from workspace A cannot access workspace B,
  - rotated tokens invalidate prior MCP access,
  - browser-session auth still works normally.

**Checkpoint:** run MCP/auth tests and full test suite.

---

## Tranche 4 — Harden Agent Handling of Untrusted Inputs

**Goal:** Reduce prompt-injection risk when tickets, chat, and repo-controlled text are untrusted.

### T4.1 Delimit untrusted content in prompts

- **Files:** `server/workers.py`, `server/events.py`, tests in `tests/test_workers.py` and chat-related tests
- Update `_assemble_prompt()` so user-controlled content is wrapped in an explicit untrusted-data section.
- Update live chat prompt construction similarly.
- Add explicit instructions that ticket/chat/repo text should not be treated as higher-priority instructions.

### T4.2 Introduce a worker trust mode

- **Files:** `server/validation.py`, `server/events.py`, `server/workers.py`, `static/components/WorkerConfigModal.js`, relevant frontend tests
- Add a field such as `trust_mode` with a small enum, recommended:
  - `trusted`
  - `untrusted`
- Default new AI/chat-capable workers to `untrusted` unless the team explicitly wants compatibility-first behavior.

### T4.3 Map trust mode to safer execution defaults

- **Files:** `server/agents/claude_adapter.py`, `server/agents/codex_adapter.py`, `server/agents/gemini_adapter.py`, `server/workers.py`
- In `untrusted` mode:
  - disable or reduce autonomous/destructive execution flags where provider support allows,
  - disable `auto_commit` and `auto_pr`,
  - optionally narrow MCP/tool access if the provider CLI supports it.
- In `trusted` mode:
  - preserve current behavior for tightly controlled workflows.

### T4.4 Preserve current UX where needed

- If changing the default trust mode is too disruptive, ship the capability first and keep existing workers grandfathered as `trusted`.
- New workers can still default to `untrusted`.

### T4.5 Verification

- Add tests for:
  - prompt templates containing clear untrusted-content delimiters,
  - trust mode validation and persistence,
  - `auto_commit` / `auto_pr` blocked in `untrusted` mode,
  - adapter flags switching based on trust mode where supported.

**Checkpoint:** run worker/chat/agent tests and full test suite.

---

## Tranche 5 — Reduce Cross-Workspace Data Exposure

**Goal:** Stop giving every connected client all workspace state and absolute paths by default.

### T5.1 Send one workspace on initial connect

- **Files:** `server/app.py`, `server/events.py`, `static/app.js`, relevant frontend socket tests
- Change initial connect behavior so the client receives:
  - project list,
  - startup workspace state only.
- Additional workspace state should be fetched on explicit `project:join`.

### T5.2 Redact absolute filesystem paths from standard project payloads

- **Files:** `server/workspace_manager.py`, `server/app.py`, `server/events.py`, frontend tests
- Decide whether the regular UI actually needs absolute `path`.
- Recommended:
  - omit `path` from default client payloads,
  - add a separate privileged/debug payload only if truly needed later.

### T5.3 Verification

- Tests should confirm:
  - initial connect no longer emits every workspace’s `state:init`,
  - project switching still works,
  - path redaction does not break the workspace picker UI.

**Checkpoint:** run socket/multi-project frontend tests and full test suite.

---

## Tranche 6 — Login Hardening

**Goal:** Add low-cost protection around authenticated deployments.

### T6.1 Add login throttling

- **Files:** `server/app.py`, possibly `requirements.txt`, tests in `tests/test_auth*.py`
- Recommended lightweight implementation:
  - per-IP and per-username failed-login backoff,
  - in-memory store is acceptable for the local app.
- Avoid introducing a heavy dependency if a small local implementation is enough.

### T6.2 Make logout `POST`-only

- **Files:** `server/app.py`, `static/*` if logout UI needs updating, auth tests
- Remove `GET` from `/logout`.
- Keep CSRF protection consistent with the login/session model.

### T6.3 Verification

- Tests for:
  - repeated failed login attempts trigger throttling,
  - logout by GET is rejected,
  - logout by POST succeeds.

**Checkpoint:** run auth tests and full test suite.

---

## Tranche 7 — Zip Import Availability Hardening

**Goal:** Prevent archive-based resource exhaustion during import.

### T7.1 Add file-count and expansion-ratio limits

- **Files:** `server/app.py`, `tests/test_export_import_api.py`
- Extend `_safe_extract_zip()` to enforce:
  - maximum extracted file count,
  - maximum per-file and/or total compression ratio,
  - optional nested archive rejection.

### T7.2 Verification

- Add tests for:
  - over-file-count archive rejected,
  - high-expansion archive rejected,
  - normal exports/imports still accepted.

**Checkpoint:** run import/export tests and full test suite.

---

## Recommended Implementation Order

1. Tranche 1: browser-origin and HTML execution fixes
2. Tranche 2: export/import secret stripping
3. Tranche 3: per-workspace MCP tokenization
4. Tranche 4: untrusted-input agent hardening
5. Tranche 5: cross-workspace visibility reduction
6. Tranche 6: login/logout hardening
7. Tranche 7: zip-import hardening

---

## Design Decisions To Make During Implementation

These do not require a new security review, but they do need concrete choices before code lands.

### 1. Origin allowlist configuration shape

Recommended:

- `BULLPEN_ALLOWED_ORIGINS` as a comma-separated explicit allowlist
- exact-origin matching only

### 2. HTML handling behavior

Recommended:

- default to sandboxed in-app preview
- do not open workspace HTML as live same-origin tabs

### 3. Worker trust-mode rollout

Recommended:

- grandfather existing workers as `trusted`
- default newly created AI workers to `untrusted`

### 4. Project path exposure

Recommended:

- remove absolute paths from the default UI payload
- add them back only in a dedicated admin/debug path if needed

---

## Suggested Tickets

1. Tighten Socket.IO allowed origins and add explicit allowlist support
2. Remove same-origin HTML execution from Files tab
3. Strip runtime connection secrets from workspace export/import
4. Refactor MCP auth to per-workspace tokens
5. Add MCP token rotation CLI/admin support
6. Add untrusted-content delimiters to worker and chat prompts
7. Add worker trust mode and safer agent defaults
8. Reduce initial cross-workspace state disclosure
9. Redact absolute project paths from client payloads
10. Add login throttling and POST-only logout
11. Add zip import anti-bomb limits

---

## Exit Criteria

This plan is complete when:

- cross-origin tunnel pages cannot drive local Bullpen by default,
- workspace HTML cannot execute as Bullpen-origin code,
- exported workspaces do not leak live runtime secrets,
- one workspace’s MCP token cannot access another workspace,
- untrusted ticket/chat content is clearly separated from trusted agent instructions,
- initial clients no longer receive all workspace state by default,
- authenticated deployments have basic login hardening,
- import paths are protected against archive-based resource exhaustion,
- and the full test suite passes after each tranche lands.
