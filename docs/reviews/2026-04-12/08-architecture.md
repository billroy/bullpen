# Architecture Review — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Review of system architecture, component boundaries, data flow, coupling, extensibility points, and architectural decisions.

---

## System Overview

Bullpen is a single-process Python web application that:
1. Serves a Vue 3 SPA over HTTP (Flask static file serving)
2. Manages real-time bidirectional communication (Flask-SocketIO, threading mode)
3. Orchestrates AI agent subprocesses (subprocess-based workers)
4. Persists state in flat files (JSON + Markdown in `.bullpen/`)
5. Exposes a JSON-RPC MCP stdio server for Claude Code integration

---

## Architecture Diagram (logical)

```
Browser (Vue 3 SPA)
    │  HTTP (REST: /api/*, /login)
    │  WebSocket (Socket.IO events)
    ▼
Flask App (app.py)
    ├── auth.py          — Session auth, CSRF
    ├── events.py        — Socket.IO handlers
    ├── workers.py       — Worker state machine + agent execution
    │       └── agents/  — ClaudeAdapter, GeminiAdapter, CodexAdapter
    ├── tasks.py         — Task CRUD
    ├── persistence.py   — Atomic file I/O, frontmatter
    ├── scheduler.py     — Time-based triggers (background thread)
    └── workspace_manager.py — Multi-workspace registry

.bullpen/ (per workspace)
    ├── config.json      — Worker/workspace config + MCP token
    ├── layout.json      — Worker grid state
    ├── tasks/           — Task markdown files
    ├── profiles/        — Worker profile JSON files
    └── teams/           — Saved grid configurations

MCP stdio server (mcp_tools.py)
    └── BullpenClient    — Socket.IO client → main app
```

---

## Findings

### HIGH — No separation between application state and transport layer

**Files:** `server/events.py`, `server/workers.py`

The Socket.IO event handlers in `events.py` directly manipulate layout data, call persistence functions, and invoke worker state transitions — all in one place. There is no domain service layer between the transport (SocketIO) and the domain (task management, worker lifecycle). This means:
- Business logic is not reusable outside the Socket.IO context (e.g., for a future REST API or CLI).
- Unit testing requires mocking the SocketIO transport layer.
- Changes to task semantics require understanding the event handler's full call stack.

**Recommendation:** Introduce a thin service layer (`server/services/`) that contains business logic callable without Socket.IO context. Event handlers become thin wrappers that call services and emit results.

---

### HIGH — Shared module-level `write_lock` is a single serialization point

**File:** `server/locks.py`, `server/workers.py`, `server/events.py`

A single `threading.Lock` (`write_lock`) serializes all mutations to layout.json and all worker state changes. Under concurrent agent runs (e.g., 6 workers active simultaneously), all state-mutating operations queue behind this lock. This is:
- Correct for single-workspace single-process deployment.
- A hard scalability limit: all agent status updates, task completions, and config changes contend on the same lock.
- Potentially a source of latency under high worker load (a slow file write holds the lock).

**Recommendation:** Consider per-workspace locks to reduce contention when multiple workspaces are active. The current single-lock model is appropriate for <10 workers but will be a bottleneck at higher scale.

---

### MEDIUM — MCP stdio server is architecturally decoupled but connects back via Socket.IO

**Files:** `server/mcp_tools.py`, `server/agents/claude_adapter.py`

The MCP stdio server (`mcp_tools.py`) runs as a separate process (spawned by Claude CLI) but connects back to the main Bullpen server via Socket.IO to perform ticket operations. This creates a circular dependency:

```
Claude CLI → (spawns) → mcp_tools.py → (Socket.IO) → main server → tasks.py
```

The MCP token is the authentication bridge between these two processes. This is a workable design but has fragility:
- If the main server restarts while Claude is running, the MCP server loses its connection and must reconnect.
- The MCP server has no persistent state — all state is in the main server.
- Port conflicts or firewall rules could prevent the MCP server from connecting back.

**Recommendation:** Document this architecture and the failure modes in `server/mcp_tools.py`. Add connection retry/reconnect logic (currently `MAX_CONNECT_ATTEMPTS = 3` then fail).

---

### MEDIUM — `WorkspaceManager` stores per-workspace runtime state mixed with registry

**File:** `server/workspace_manager.py`

`WorkspaceManager` handles both: (a) the persistent registry of known workspaces (`~/.bullpen/projects.json`), and (b) in-memory runtime state (`WorkspaceState` objects including the scheduler). Mixing persistent registry and runtime state in one class makes it harder to reason about the lifecycle of each. For example, `register_project()` is called both at startup (to initialize runtime state) and from tests (to add to the registry without starting a scheduler).

**Recommendation:** Separate the persistent registry (`WorkspaceRegistry`) from the in-memory state manager (`WorkspaceRuntime`). This would clarify which operations are I/O and which are in-memory.

---

### MEDIUM — No event bus or pub/sub for internal communication

**Files:** `server/workers.py`, `server/events.py`, `server/scheduler.py`

Workers communicate results back to clients by calling `socketio.emit()` directly. The scheduler calls into `workers.py` functions directly. This creates tight coupling:
- `workers.py` imports `socketio` (passed as a parameter) and must know the event names.
- `scheduler.py` imports `workers.py` and calls specific functions.
- Adding a new consumer of worker completion events (e.g., a webhook notifier) requires modifying `workers.py`.

**Recommendation:** For future extensibility, introduce an internal event/callback system that decouples worker state changes from their consumers (SocketIO, scheduler, future webhooks).

---

### LOW — Scheduler runs as a single background thread per workspace

**File:** `server/scheduler.py`

Each workspace gets its own `Scheduler` thread that polls every 30 seconds. With N workspaces, there are N scheduler threads. This is fine at small N but adds overhead at scale. More importantly, if the scheduler thread raises an unhandled exception, it terminates silently and time-based triggers stop firing without any UI notification.

**Recommendation:** Add exception handling in the scheduler loop to catch and log all exceptions, and restart the thread if it dies.

---

### LOW — Frontend has no component registry or lazy loading

**File:** `static/index.html`

All 13+ Vue component files are loaded eagerly via `<script src="...">` tags in `index.html`. There is no module bundling, code splitting, or lazy loading. Initial page load fetches all component code even for features the user may not use (e.g., the Commits tab, FilesTab, Live Agent Chat). At current codebase size this is acceptable; at 2× size it will impact initial load performance.

---

## Positive Observations

- The agent adapter pattern (`base.py` + per-provider adapter) is a clean extensibility point for adding new AI providers.
- `ensure_within()` is used as a consistent path safety abstraction across all file-touching modules.
- `atomic_write` prevents partial writes across all persistence operations.
- Multi-workspace support is well-isolated with `WorkspaceState` per workspace.
- The MCP stdio server correctly redirects stdout to prevent corruption of the JSON-RPC stream.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| AR1 | HIGH | No service layer — business logic coupled to Socket.IO transport |
| AR2 | HIGH | Single global write_lock is a serialization bottleneck |
| AR3 | MEDIUM | MCP circular dependency has documented failure modes but no reconnect loop |
| AR4 | MEDIUM | WorkspaceManager mixes registry persistence with runtime state |
| AR5 | MEDIUM | No internal event bus — tight coupling between workers, events, and scheduler |
| AR6 | LOW | Scheduler threads die silently on unhandled exceptions |
| AR7 | LOW | Frontend eager-loads all components with no lazy loading |
