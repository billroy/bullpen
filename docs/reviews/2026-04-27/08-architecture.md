# Architecture Review
*Bullpen — 2026-04-27*

**Reviewer role:** Principal architect, potential acquirer perspective
**Prior review:** 2026-04-09 (baseline)
**Scope:** Updated assessment reflecting ~391 commits of development since the April 9 review. New architectural elements include: MCP auth token system, Stats tab with token/time accounting, worker import/export, cross-workspace worker transfer, Marker worker type, live agent chat, git worktree isolation, and Docker deployment improvements.

---

## Executive Summary

Bullpen's architecture has matured and solidified since the April baseline while remaining consistent with its stated scope: a single-user, local agent orchestrator with real-time browser UI. The layering is clean and the component boundaries are respected. Several new subsystems (MCP auth, usage accounting, worker transfer, worktree isolation) have been added with appropriate encapsulation — each as a focused module rather than expanding existing modules.

The architecture's primary constraints are unchanged: flat-file persistence, a single-process threading model, a global write lock, and no message queue between the scheduler and worker execution. These are correct design choices for the current scope. An acquirer should evaluate whether the target deployment model (single-user local tool vs. hosted multi-tenant product) requires architectural evolution or a full rewrite of the persistence and concurrency layers.

A notable positive since April: the MCP stdio server has received significant hardening. The stdout purity constraint (any stray byte kills the MCP connection) is now explicitly documented, guarded by early stdout redirection in `main()`, and backed by a token-based auth flow that survives server restarts. This was a fragile integration point in April; it is substantially more robust now.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (Vue 3 CDN, no build step)                          │
│  Kanban | Workers | Tickets | Files | Commits | Stats | Chat │
│  Socket.IO client ↔ real-time bidirectional events           │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket (Socket.IO rooms per workspace)
┌──────────────────────────▼──────────────────────────────────┐
│  Flask + Socket.IO Server  (server/app.py — app factory)     │
│                                                              │
│  REST routes:  /login /logout /api/workspace/* /api/files   │
│                /api/commits /api/export /api/import          │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ server/events.py — Socket.IO event handlers           │  │
│  │   validate (validation.py) → write_lock → business    │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  Business logic modules (single-concern):                    │
│  tasks.py │ workers.py │ scheduler.py │ profiles.py          │
│  teams.py │ transfer.py │ usage.py │ worktrees.py            │
│  prompt_hardening.py │ model_aliases.py │ service_worker.py  │
│                                                              │
│  Infrastructure:                                             │
│  persistence.py (atomic I/O) │ locks.py (write_lock)        │
│  auth.py │ mcp_auth.py │ validation.py │ workspace_manager   │
└──────────────────────────┬──────────────────────────────────┘
                           │ os.replace atomic writes
┌──────────────────────────▼──────────────────────────────────┐
│  .bullpen/ (flat-file store, per workspace)                  │
│  config.json │ layout.json │ tasks/*.md │ tasks/archive/*.md │
│  profiles/*.json │ teams/*.json │ worktrees/<task_id>/       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Agent Subprocesses (one background thread per running worker)│
│  Claude CLI (stream-json) │ Codex CLI │ Gemini CLI          │
│   stdin: prompt    stdout: streaming JSON/text               │
│                                                              │
│  MCP stdio server (mcp_tools.py) — spawned by Claude CLI    │
│   JSON-RPC 2.0 over stdin/stdout                             │
│   Authenticates via workspace mcp_token in config.json       │
│   Bridges ticket operations back to the Flask server         │
│   via Socket.IO (BullpenClient → server/events.py)           │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Analysis

### server/app.py (1,371 lines) — Flask App Factory

Creates the Flask application, configures Socket.IO, registers routes (login, static files, workspace API, file browser, commit viewer, export/import), and wires up the WorkspaceManager and per-workspace Schedulers. Route handlers are thin: they validate inputs, resolve the workspace, and delegate to business logic modules.

The `create_app` function has grown to handle workspace initialization, MCP token stamping, login throttling, archive zip security (compression bomb, path traversal, nested archive checks), and origin validation. This is correct defensive depth at the boundary layer.

**Assessment:** Acceptable concentration of concerns for a solo-developer codebase. The file is large but not deeply nested; a new contributor can navigate it. The logical next decomposition would extract route groups into blueprints (`auth_bp`, `workspace_bp`, `files_bp`).

### server/events.py (1,734 lines) — Socket.IO Event Handlers

All Socket.IO event handlers live here. The pattern is consistent: receive event, validate payload size, validate fields (via `validation.py`), acquire `write_lock`, read layout, mutate, write layout, emit updates to the workspace room. Handlers delegate complex operations to `workers.py`, `tasks.py`, and `transfer.py`.

Notable: the live agent chat handlers (`handle_chat_send`, `handle_chat_stop`) run agent subprocesses with `TRUST_MODE_UNTRUSTED` hardening applied unconditionally — this is the correct security default for a chat-originated execution path.

**Assessment:** The file has grown large as features were added (worker transfer, group paste, live agent, layout import). The structure is consistent and testable. The main risk is edit locality: a change to one event handler risks accidentally breaking adjacent handlers in the same large file.

### server/workers.py (2,872 lines) — Worker State Machine

The heaviest module. Manages the full lifecycle of a worker run: task dequeue, prompt assembly (with trust hardening), subprocess spawning, streaming output parsing, token extraction, task-time accounting, retry/backoff with exponential delay, handoff to downstream workers, and task disposition (review/done/archive). Also contains the scheduler-triggered auto-task creation path.

The MCP integration path within workers.py is notable: for Claude agent workers, `workers.py` generates a per-task MCP server config file (pointing to `mcp_tools.py`) and passes it via `--mcp-config` to the Claude CLI. The Claude CLI then spawns `mcp_tools.py` as a subprocess. This architecture means the MCP server is per-task, not persistent.

**Assessment:** Correct behavior, high complexity. This module is the most likely source of subtle bugs under new feature additions. Decomposition is the primary architectural recommendation for maintainability.

### server/persistence.py (218 lines) — Atomic I/O

Clean, focused module. `atomic_write` uses `tempfile.mkstemp` + `os.replace` for crash-safe writes. `ensure_within` guards against path traversal. The custom frontmatter parser handles the subset of YAML used by task files (scalars, arrays, inline objects) correctly and is test-covered.

**Assessment:** Well-designed for its scope. The custom parser is a maintenance liability if the task schema grows substantially more complex, but it is appropriate for the current controlled schema.

### server/locks.py (8 lines) — Global Write Lock

```python
write_lock = threading.Lock()
```

A single module-level `threading.Lock` shared across all workspaces and all event handlers. This is the correct design for preventing layout file corruption under concurrent Socket.IO events and background agent threads. The architectural constraint is that it serializes all layout mutations globally — including mutations to unrelated workspaces.

**Assessment:** Safe and correct for the current scale. See ARCH-01 finding for the workspace-scoped lock recommendation.

### server/scheduler.py (116 lines) — Background Trigger Thread

Polls every 60 seconds. Reads all workspace layouts under the write lock, identifies workers due to fire (at_time, on_interval), releases the lock, then calls `start_worker()` for each. Auto-creates ephemeral tasks for self-directed workers.

The scheduler fires `start_worker()` directly rather than queuing through the task assignment path. This means a trigger fired while the worker is busy is silently dropped (start_worker checks worker state and returns early). This is the same ARCH-02 finding from April — unresolved.

**Assessment:** Correct for manual-trigger and daily-schedule use cases. For high-reliability interval triggers (e.g., an on_interval worker that must not miss a beat), the silent-drop behavior is a reliability gap.

### server/mcp_tools.py (701 lines) — MCP stdio Server

JSON-RPC 2.0 server run as a subprocess by the Claude CLI. Exposes `create_ticket`, `list_tickets`, `list_tasks`, `list_tickets_by_title`, `update_ticket`. Bridges these operations to the Flask server via Socket.IO using `BullpenClient`.

Key hardening present:
- stdout captured to `_mcp_out` before `sys.stdout` is redirected to `sys.stderr`, preventing any library print from corrupting MCP framing
- Per-message exception handling in the read loop prevents one bad request from crashing the process
- `BullpenClient._connect_best_effort` retries up to `MAX_CONNECT_ATTEMPTS=3` times with 5-second timeouts

**Assessment:** The most architecturally fragile integration point in the system — but it is now well-guarded. The stdout purity constraint is documented in CLAUDE.md and enforced in code. The token auth flow (`mcp_token` in config.json → Socket.IO `auth=` handshake) is clean and survives server restarts.

### server/auth.py — Authentication

Session-based password authentication using Werkzeug's `generate_password_hash` / `check_password_hash`. Credentials stored in `~/.bullpen/.env` (mode 600). Supports multi-user via `BULLPEN_USERS_JSON`. CSRF token on the login form. Login throttle (5 failures in 5 minutes → 60-second block).

**Assessment:** Correct for a single-user or small-team local deployment. Not suitable for multi-tenant hosted use without replacement.

### server/agents/ — Agent Adapters

`AgentAdapter` ABC in `base.py` with implementations for Claude, Codex, and Gemini. Each adapter implements: `find_binary()`, `build_argv()`, `parse_stream_event()`, `build_mcp_config()`. The abstraction is clean and stable.

**Assessment:** Adding a new agent (e.g., a local Ollama-backed model) requires one new file implementing 4 methods. No changes to the orchestration layer. This is the correct extensibility design.

### server/worktrees.py — Git Worktree Isolation

Creates a `git worktree` per task in `.bullpen/worktrees/<task_id>`. Branch named `bullpen/<task_id>`. Supports auto-commit and auto-PR workflows. Cleans up the worktree on task completion.

**Assessment:** Well-scoped and self-contained. The `_git_ok()` check prevents worktree operations on non-git workspaces. The branch naming convention is predictable and does not collide with user branches.

### server/transfer.py — Cross-Workspace Worker Transfer

Copies or moves a worker slot (including its profile if requested) between workspaces. Uses the global write lock, validates both source and destination workspaces, and emits layout updates to both workspace rooms.

**Assessment:** Clean addition. Acquiring the global write lock for cross-workspace mutations is correct — this is one case where a per-workspace lock would need careful ordering to avoid deadlock.

---

## Data Flow

### Task Execution Flow

```
User drops task onto worker (Socket.IO: task:assign)
  → events.py: validate payload → acquire write_lock
  → tasks.py: read task frontmatter → update task status to assigned
  → workers.py: enqueue task_id in worker.task_queue → write layout
  → release write_lock → emit layout:update to workspace room
  → workers.py: start_worker() spawns background thread
    → thread: assemble prompt (trust-hardened) → subprocess.Popen(agent CLI)
    → thread: stream parse stdout → emit worker:output to room
    → thread: on completion → update task frontmatter (status, tokens, time)
    → thread: acquire write_lock → update worker state → write layout
    → thread: emit layout:update, task:updated to room
```

### MCP Tool Call Flow

```
Agent CLI executes MCP tool (e.g., update_ticket)
  → Claude CLI spawns mcp_tools.py via --mcp-config
  → mcp_tools.py reads workspace mcp_token from config.json
  → BullpenClient connects to Flask Socket.IO server
      auth={"mcp_token": <token>}
  → Flask on_connect: validates token → records mcp_sid
  → mcp_tools.py: emits Socket.IO event (e.g., task:update)
  → events.py: handles event → updates task file → emits task:updated to room
  → mcp_tools.py: receives acknowledgment → returns JSON-RPC result to agent
```

### File Write Safety

All file mutations go through `persistence.atomic_write` (temp file + `os.replace`) or `write_json` (which calls `atomic_write`). Layout mutations are further serialized by `write_lock`. The combination prevents torn writes and race conditions between concurrent event handlers and background threads.

---

## Coupling & Cohesion

**Good separations:**
- `persistence.py` has no knowledge of business domain objects — it handles bytes and dicts only
- `validation.py` has no side effects — pure validation functions returning values or raising `ValidationError`
- `locks.py` is a single object with no logic — purely a shared primitive
- `usage.py` handles token/time accounting without touching layout or task files directly
- `mcp_auth.py` handles token management as a pure config read/write operation
- `worktrees.py` has no knowledge of workers or tasks — just git subprocess calls
- Agent adapters have no knowledge of tasks or layout — just argv construction and stream parsing

**Areas of coupling:**
- `workers.py` imports from `tasks.py`, `worktrees.py`, `usage.py`, `prompt_hardening.py`, `validation.py`, `agents/`, `persistence.py`, and `locks.py`. This is unavoidable given its orchestration role, but the coupling makes decomposition more expensive.
- `events.py` imports from nearly every other module. Again, this is the nature of the event handler layer, but it means changes to any module's interface require updating events.py.
- The global `write_lock` in `locks.py` creates an implicit coupling between all modules that import it — they all contend on the same primitive.

---

## Resilience & Fault Tolerance

**What is handled well:**

- **Atomic file writes:** `os.replace` is atomic on POSIX. A crash mid-write leaves the old file intact.
- **Subprocess crash handling:** `workers.py` catches `subprocess.TimeoutExpired`, `OSError`, and general exceptions from agent runs. Failed runs update the task to an error state and emit an error event to the UI.
- **Retry/backoff:** Agent workers support configurable max_retries with exponential backoff. State is persisted in the layout so retries survive browser reload.
- **MCP connection retry:** `BullpenClient._connect_best_effort` retries up to 3 times with 5-second timeout per attempt.
- **Scheduler tick isolation:** Each scheduler tick is wrapped in a `try/except` that logs the error and continues. One bad tick does not stop the scheduler.
- **Login throttle:** 5 failures → 60-second block, preventing brute-force attacks on the login form.
- **Zip bomb protection:** Import archive validation checks file count (≤1000), size (≤200MB), compression ratio (≤100x), and nested archive presence.

**What is not handled:**

- **Process crash recovery:** If the Flask process crashes while a worker is running, the task stays in `in_progress` state with no automatic resume. On restart, the UI will show a stale state until the user manually resets the worker.
- **Multi-file transaction consistency:** Updating a task requires writing both the task `.md` file and the `layout.json`. If the process crashes between these two writes, the files are in a partially-updated state. The individual writes are atomic; the combination is not.
- **Socket.IO reconnection output gap:** Worker output emitted during a client disconnection is not replayed on reconnect. The client sees the current state but misses intermediate output lines (ARCH-03 from April, unresolved).
- **Disk full:** No explicit handling for `OSError: [Errno 28] No space left on device`. An agent run writing large output artifacts could fail mid-write with an unhandled exception.

---

## Extensibility

**Adding a new agent type:** Implement `AgentAdapter` (4 methods). Register in `server/agents/__init__.py`. Add the agent name to `VALID_AGENTS` in `validation.py`. Estimated effort: 1–2 days for a standard CLI-based agent.

**Adding a new worker type:** Add a type string to `worker_types.py`. The Marker worker type added since April demonstrates the pattern — it is a display-only node that requires no execution logic, handled by early returns in the worker execution path.

**Adding a new task field:** Add to the frontmatter schema in `persistence.py` and to the validation in `validation.py`. Existing tasks without the field will return the `.get()` default. No migration required for optional fields.

**Adding a new Socket.IO event:** Add a handler in `events.py`. The write-lock + validate + emit pattern is consistent and can be followed mechanically.

**Adding a new REST API endpoint:** Add a route in `app.py` or extract into a Flask blueprint. The `@require_auth` decorator handles auth. The workspace resolution pattern (`ws_id = request.args.get("ws_id")`, `ws = manager.get_or_activate(ws_id)`) is established.

**Assessment:** Extensibility within the current architecture is good. The agent adapter abstraction, frontmatter schema flexibility, and consistent event handler pattern make incremental feature addition low-friction. The extensibility ceiling is the single-process, single-machine constraint — not the code structure.

---

## Findings

### HIGH — No Persistent Output Log for Worker Runs

**Location:** `server/workers.py`, `server/events.py`

Worker output (stdout from agent subprocesses) is streamed to the Socket.IO room and held in a per-worker in-memory buffer (capped at ~100KB). If a client disconnects and reconnects, or if the Flask process restarts, the output from an in-progress or recently-completed run is lost. There is no append-only log on disk.

For an interactive developer tool this is a usability gap: the user loses the agent's reasoning trace on any connection interruption. For a long-running autonomous worker (e.g., an on_interval worker that runs overnight), the output is permanently unrecoverable after the run completes unless the user was watching live.

This was ARCH-03 in the April review and remains unresolved.

**Recommendation:** Write an append-only output log to `.bullpen/logs/<ws_id>/<task_id>-<slot>.log` during each worker run. On reconnect, serve this log as the initial output state. This also enables post-mortem debugging of failed runs.

---

### MEDIUM — Global Write Lock Across All Workspaces

**Location:** `server/locks.py`, `server/events.py`, `server/workers.py`

`write_lock = threading.Lock()` is a single process-level mutex. Every layout mutation — across all workspaces — contends on this one lock. In the current single-user, few-workspace case this is not a bottleneck. As workspace count grows (e.g., a developer with 10+ active projects), or as worker runs become more frequent, this lock becomes the serialization point for all state changes.

This was ARCH-01 in the April review and remains unresolved.

**Recommendation:** Move the write lock into `WorkspaceState`. Each workspace acquires only its own lock for local mutations. Cross-workspace operations (transfer.py) acquire workspace locks in a consistent order (by workspace ID) to prevent deadlock. This is a medium-complexity refactor with high parallelism benefit.

---

### MEDIUM — Scheduler Triggers Bypass the Task Queue

**Location:** `server/scheduler.py` lines 101–115

When a time-based trigger fires, the scheduler calls `start_worker()` directly. If the worker is already running (state != "idle"), `start_worker()` returns early and the trigger is silently dropped. There is no queue of pending trigger events, no retry of the missed trigger, and no user notification.

This was ARCH-02 in the April review and remains unresolved.

For daily at-time triggers this is acceptable (missing by one poll cycle is recoverable next day). For on_interval triggers with short intervals, a missed trigger during an active run means the interval effectively extends by one full run duration.

**Recommendation:** Route scheduler triggers through the same task queue mechanism as manual task assignment (`task_queue` field on the worker). The scheduler should enqueue a trigger task rather than calling `start_worker()` directly. This ensures triggers are not lost when the worker is busy.

---

### MEDIUM — workers.py Needs Decomposition

**Location:** `server/workers.py` (2,872 lines)

The worker module has grown to encompass state machine transitions, subprocess spawning, agent execution, streaming output parsing, token accounting, task-time tracking, retry/backoff, worktree setup/teardown, auto-task creation, and handoff orchestration. This breadth makes the module difficult to reason about in isolation and creates a large blast radius for any change.

**Recommendation:** Decompose into focused modules:
- `worker_state.py` — idle/running/retrying/error state transitions
- `worker_execution.py` — subprocess spawn, stream parsing, output buffering
- `worker_accounting.py` — token extraction, task-time accumulation
- `worker_retry.py` — retry policy, backoff calculation

This is a multi-day refactor. The worker module is well-tested (many tests in `test_events.py` and `test_e2e.py` cover worker behavior), which makes safe decomposition feasible.

---

### LOW — MCP Server Spawned Per-Task Rather Than as Persistent Sidecar

**Location:** `server/agents/claude_adapter.py`, `server/mcp_tools.py`

For each agent task, a new `mcp_tools.py` process is spawned by the Claude CLI. This incurs:
- MCP startup latency on every task run (Socket.IO handshake, token auth, connection verification)
- A new process with its own Socket.IO connection that must be established and torn down
- The fragility of the stdout purity constraint on every new spawn

The architecture is sound and now well-guarded, but it is less efficient than a persistent sidecar that maintains a single Socket.IO connection and handles tool calls across multiple task runs.

This was ARCH-05 in the April review and remains unresolved. It is lower priority given the improved robustness of the per-task spawn model.

**Recommendation:** For future consideration: run `mcp_tools.py` as a persistent sidecar process per workspace, reusing the Socket.IO connection across tasks. The current per-task architecture is acceptable at the current scale.

---

### LOW — No Event Replay on Socket.IO Reconnect

**Location:** `server/events.py` (`handle_connect`), `server/app.py`

On reconnect, clients receive a `state:init` event with the current layout and task list. Events emitted between disconnect and reconnect (worker output lines, task status changes, token updates) are not replayed. The `state:init` provides eventual consistency but with a gap in intermediate events.

For multi-tab usage or flaky network conditions, this means the browser may show a stale intermediate state briefly. For worker output specifically, lines emitted during disconnection are permanently lost.

This was ARCH-03 in the April review (elevated to HIGH above for the output log aspect). The event replay gap for non-output events (layout changes, task status) is LOW severity because `state:init` restores the final state correctly.

**Recommendation:** For non-output events, the current behavior is acceptable. Focus the output log recommendation (HIGH finding above) on the worker transcript loss specifically.

---

### POSITIVE FINDINGS

**MCP auth hardening (improvement since April):** The token-based auth flow (`mcp_token` in `config.json` → Socket.IO `auth=` handshake) is cleanly implemented in `mcp_auth.py`. Token collision detection across workspaces, token rotation, and the `mcp_sids` set for distinguishing agent connections from user connections are all correct.

**Zip security in import (new since April):** The archive import in `app.py` checks compression ratio (≤100x), file count (≤1000), total size (≤200MB), path traversal (via `ensure_within`), and nested archive presence. This is correct defensive depth for an import feature.

**Prompt injection hardening (improvement since April):** The `prompt_hardening.py` module and its `TRUST_MODE_UNTRUSTED` / `TRUST_MODE_TRUSTED` system correctly separates untrusted workspace content from trusted prompt instructions using marker blocks. The live agent chat path applies untrusted mode unconditionally, which is the correct default.

**Agent adapter abstraction remains stable:** The `AgentAdapter` ABC is unchanged and continues to provide the correct extensibility boundary. The addition of Gemini support without touching the orchestration layer validates the design.

**Usage accounting (new since April):** The `usage.py` module cleanly handles token field normalization across different agent response formats (Claude, Codex, Gemini all use different field names for equivalent data). The alias table approach is correct and extensible.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 1     |
| MEDIUM   | 3     |
| LOW      | 2     |

---

## Recommendations

**Address before acquisition close:**
1. Evaluate the persistent output log gap (HIGH): determine whether the target use case requires post-hoc access to worker transcripts. If yes, implement before close to assess implementation complexity.

**Address in the first 30 days:**
2. Decompose `workers.py` into focused sub-modules (MEDIUM). This is the highest-leverage maintainability improvement and reduces the risk of regressions as the team grows.
3. Per-workspace write lock (MEDIUM). Low implementation complexity, meaningful throughput improvement for multi-workspace users.

**Address in 60–90 days:**
4. Route scheduler triggers through the task queue (MEDIUM). Required for reliable on_interval workers under load.

**Defer:**
5. Persistent MCP sidecar (LOW). Current per-task spawn model is working and well-guarded. Optimize only if per-task latency becomes measurable.
6. Socket.IO event replay (LOW). The `state:init` reconnect path provides eventual consistency. Full event replay is complex and not necessary at current scale.
