# Security Review — codex-1

Date: 2026-04-08
Reviewer: Codex
Scope: Full repository code review (`server/`, `static/`, entrypoint, tests), with explicit separation of single-user MVP concerns vs multi-user/multi-host blockers.

## Executive Summary
- The project has several strong baseline controls (atomic writes, path-boundary checks for task/file paths, `subprocess` argv execution with no shell, markdown rendering with HTML disabled).
- The current implementation is **not safely confined to single-machine/local-only behavior by default** because it binds to `0.0.0.0` and allows Socket.IO CORS from any origin.
- I found **7 high-impact issues that matter now**, even for a single-developer setup.
- I found **10 architectural blockers** that must be addressed before multi-user/multi-host deployment.

## Threat Model Used
- Current intended mode: single developer, single machine, local trust assumptions.
- Adversary models considered:
  1. Malicious webpage opened in the developer’s browser.
  2. Untrusted process on same LAN hitting exposed port.
  3. Accidental misuse by legitimate operator causing destructive side effects.
  4. Future multi-tenant/multi-host environment with semi-trusted users.

## A) Security Issues That Matter Even In Single-User MVP

### 1) Critical: Unauthenticated remote control surface is exposed by default
Evidence:
- `socketio.run(... host="0.0.0.0" ...)` in `bullpen.py:52`
- Socket.IO allows all origins: `cors_allowed_origins="*"` in `server/app.py:42`
- No auth checks in socket handlers (`server/events.py`) or file routes (`server/app.py:52-113`)

Impact now:
- Any client that can reach the port can trigger task/worker/project/file operations.
- A malicious web page can potentially drive local operations via cross-origin Socket.IO.

Recommendation:
- Default bind to `127.0.0.1`.
- Restrict Socket.IO origins to same-origin host/port.
- Add an explicit local auth token (at minimum) before mutating events are accepted.

### 2) High: Cross-workspace data leaks to every connected client
Evidence:
- On connect, server emits `state:init` for **all** workspaces (`server/app.py:115-124`)
- Event emitter broadcasts globally (`socketio.emit`) in `server/events.py:44` and `server/workers.py:25`

Impact now:
- Any connected client receives all project metadata and task/layout state, including absolute workspace paths.

Recommendation:
- Use per-client/per-workspace rooms; emit only to authorized room.
- Never broadcast all workspaces by default.

### 3) High: Path traversal in team/profile filesystem operations
Evidence:
- Profile path built from unsanitized `id`: `server/profiles.py:36-40`
- Team path built from unsanitized `name`: `server/teams.py:23`, `server/teams.py:30`
- These are reachable from socket events: `server/events.py:353-359`, `server/events.py:363-389`

Impact now:
- Crafted IDs/names can read/write files outside intended `.bullpen/profiles` and `.bullpen/teams` directories.

Recommendation:
- Enforce strict slug regex for profile/team IDs.
- Apply `ensure_within()` on all derived paths before I/O.

### 4) High: Arbitrary project registration expands file access/write scope
Evidence:
- `project:add` takes arbitrary path from client: `server/events.py:430-436`
- `register_project()` accepts any local directory: `server/workspace_manager.py:87-118`
- File API writes text to any path under selected workspace: `server/app.py:88-113`

Impact now:
- If attacker can emit socket events, they can register broad paths and then read/write files in those directories.

Recommendation:
- Require explicit operator confirmation for new project paths.
- Maintain allowlist of approved roots.
- Gate `project:add` behind privileged auth.

### 5) High: Mutation event validation is inconsistent and often absent
Evidence:
- Good validation exists for task create/update and worker configure (`server/validation.py`), but not for many mutating events.
- Examples without schema validation: `config:update` (`server/events.py:324-336`), `layout:update` (`server/events.py:312-323`), `worker:add`/`worker:move` raw fields (`server/events.py:102-215`), `team:save/load` names (`server/events.py:363-389`).

Impact now:
- Malformed or oversized payloads can cause unsafe state mutation or DoS (e.g., huge slot indices causing large list expansion).

Recommendation:
- Centralize schema validation for every event.
- Reject unknown keys and enforce numeric/string bounds uniformly.

### 6) Medium: File tree walker can recurse through symlinks and large trees
Evidence:
- Recursive walk uses `os.path.isdir(full)` and recurses with no symlink/visited guard: `server/app.py:154-170`

Impact now:
- Potential availability issue (deep recursion, large traversal, symlink loops).

Recommendation:
- Skip symlinked directories or enforce `realpath`-within-workspace + visited inode set.
- Add max depth / max nodes caps.

### 7) Medium: Third-party CDN scripts loaded without integrity pinning
Evidence:
- External scripts/styles loaded from unpkg/cdnjs/socket.io CDN without SRI hashes: `static/index.html:15-24`

Impact now:
- Supply-chain/browser MITM risk for frontend runtime.

Recommendation:
- Add SRI + `crossorigin` attributes, or self-host fixed assets.

### 8) Medium: Sensitive operational details are sent in raw error messages
Evidence:
- Generic exception text is emitted to client: `server/events.py:54-55`

Impact now:
- Internal paths/tooling details can leak to any connected client.

Recommendation:
- Send generic client-safe errors; log full details server-side only.

### 9) Medium: Workspace process tracking is keyed only by slot index
Evidence:
- `_processes` global map keyed by `slot_index` only: `server/workers.py:16-18`, `server/workers.py:155-157`, `server/workers.py:329-330`

Impact now:
- In multi-workspace runtime, slot collisions can cause cross-workspace stop/kill behavior.

Recommendation:
- Key active process map by `(workspace_id, slot_index)`.

### 10) Medium: Destructive automation defaults are very permissive
Evidence:
- Claude adapter includes `--dangerously-skip-permissions`: `server/agents/claude_adapter.py:41`
- Codex adapter includes `--approval-mode full-auto`: `server/agents/codex_adapter.py:40`

Impact now:
- Any compromised or malformed task prompt can drive broad file/system changes with minimal guardrails.

Recommendation:
- Make permissive modes opt-in per worker with explicit warning.
- Provide safer default adapter flags.

## B) MVP-ness vs Multi-User/Multi-Host Blockers

These are mostly acceptable as local MVP trade-offs, but they are structural blockers for next phase.

### Blocker 1: No authentication, identity, or authorization model
Evidence:
- No auth checks in HTTP routes (`server/app.py:52-113`) or socket handlers (`server/events.py`)

Why this is phase-blocking:
- Multi-user requires actor identity, access control, and scoped permissions per workspace/project.

### Blocker 2: No tenant isolation in transport/event routing
Evidence:
- Global emits instead of workspace/user rooms (`server/events.py:44`, `server/workers.py:25`, `server/app.py:115-124`)

Why this is phase-blocking:
- Multi-tenant confidentiality/integrity cannot be enforced.

### Blocker 3: No CSRF/origin-hardening strategy for browser clients
Evidence:
- Socket.IO CORS wildcard (`server/app.py:42`)

Why this is phase-blocking:
- Browser-based cross-origin drive-by control remains feasible without origin/token checks.

### Blocker 4: Dev server runtime posture unsuitable for hosted use
Evidence:
- Werkzeug unsafe mode enabled (`bullpen.py:52` with `allow_unsafe_werkzeug=True`)

Why this is phase-blocking:
- Production-grade hosting needs hardened server stack, TLS termination, and secure deployment defaults.

### Blocker 5: Flat-file persistence + in-process lock cannot scale across hosts
Evidence:
- Single process lock only (`server/locks.py:5-8`)
- File-based state as system of record (`server/persistence.py`, `server/app.py:208-234`)

Why this is phase-blocking:
- Multi-host requires shared datastore, transactional semantics, and distributed locking/consistency.

### Blocker 6: Agent execution trust boundary is full host user privileges
Evidence:
- Agents run as subprocess in workspace with no sandbox: `server/workers.py:320-327`

Why this is phase-blocking:
- Hosted/multi-user environments require sandboxing, policy controls, and least privilege execution.

### Blocker 7: No immutable audit trail / action attribution
Evidence:
- Event actions are not tied to authenticated users; logs capture process output but not user identity (`server/workers.py:505-531`)

Why this is phase-blocking:
- Compliance, incident response, and accountability require actor attribution.

### Blocker 8: No quota/rate limiting/abuse controls
Evidence:
- No request throttling or per-user/workspace limits in routes/events.

Why this is phase-blocking:
- Multi-user deployments need DoS and abuse controls.

### Blocker 9: Supply-chain policy is undeclared and unpinned
Evidence:
- Unpinned Python dependencies in `requirements.txt:1-4`
- Frontend runtime from CDN without SRI (`static/index.html:15-24`)

Why this is phase-blocking:
- Hosted environments need dependency pinning, scanning, and update governance.

### Blocker 10: Git automation has no policy guardrails
Evidence:
- Auto-commit stages everything (`git add -A`) in `server/workers.py:233-235`
- Auto-push/PR can run without branch protections from app layer (`server/workers.py:272-289`)

Why this is phase-blocking:
- Multi-user repos require branch protection integration, scoped change sets, and approval workflows.

## C) Security Controls Already Present (Positive Findings)
- Path traversal defense for task/file route operations via `ensure_within()` (`server/persistence.py:36-42`, used in `server/app.py:67`, `server/app.py:95`, `server/tasks.py:168`, `server/tasks.py:176`, `server/tasks.py:197`, `server/tasks.py:205`).
- Atomic writes for JSON/frontmatter/text (`server/persistence.py:8-23`, `server/persistence.py:31-34`, `server/persistence.py:192-196`).
- Command execution uses argv lists and no shell interpolation (`server/workers.py:320-327`).
- Markdown rendering disables raw HTML (`static/components/FilesTab.js:187`, `static/components/TaskDetailPanel.js:27`).
- HTML preview uses iframe sandbox (`static/components/FilesTab.js:117`).
- Basic payload bounds/type checks exist in validator module (`server/validation.py`).

## D) Priority Remediation Plan

### Immediate (before broader internal use)
1. Bind server to localhost by default and restrict Socket.IO origins.
2. Add mandatory auth token for mutating socket events and file-write route.
3. Fix profile/team path traversal with strict slug validation + `ensure_within`.
4. Stop global state broadcasts; scope events to workspace/client rooms.
5. Validate all event payloads consistently (including config/layout/worker/team/project events).

### Next (before multi-user pilot)
1. Replace global `_processes` key with workspace-scoped keys.
2. Add authorization model per workspace and role.
3. Add CSRF/origin/session hardening for browser clients.
4. Add symlink-safe + bounded file tree traversal.
5. Harden dependency supply chain (pin + integrity + scanning).

### Scale phase (multi-host)
1. Move from flat files to transactional datastore.
2. Introduce distributed coordination/locks.
3. Add sandboxed agent execution and policy-based capability controls.
4. Add immutable audit trails with user attribution.
5. Enforce repo/branch policy integration for auto-commit/PR features.

## E) Validation Notes
- Test suite currently has significant failures (`pytest -q` run in this review: 37 failed / 129 passed), so security assertions should not rely on current test pass status alone.
- The high-severity findings above are code-path findings validated by direct source inspection.
