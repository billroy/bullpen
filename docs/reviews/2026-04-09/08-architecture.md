# Architecture Review — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Principal architect evaluating as a potential acquirer

---

## Scope

Review of system architecture, component design, data flow, concurrency model, extensibility, and architectural fitness for the product's stated goals and likely growth trajectory.

---

## Executive Summary

Bullpen's architecture is well-suited to its current scope: a single-user, local agent orchestrator with real-time UI. The layering is clean, the component boundaries are respected, and the agent adapter abstraction enables extensibility. The primary architectural constraints that will require redesign at scale are: (1) flat-file persistence, (2) in-process threading concurrency model, (3) single-user authentication, and (4) no message queue between the scheduler and worker execution. These are appropriate decisions for an MVP; the question for an acquirer is whether the architecture can be evolved incrementally or requires a full rewrite for the target scale.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Browser (Vue 3 CDN)                                     │
│  ┌─────────┐ ┌──────────┐ ┌─────────────┐ ┌──────────┐ │
│  │ Kanban  │ │ Bullpen  │ │ Files Tab   │ │ Chat Tab │ │
│  │ Tab     │ │ Tab      │ │             │ │          │ │
│  └─────────┘ └──────────┘ └─────────────┘ └──────────┘ │
│  Socket.IO Client ←──────────────────────────────────→  │
└─────────────────────┬───────────────────────────────────┘
                      │ WebSocket (Socket.IO)
┌─────────────────────▼───────────────────────────────────┐
│  Flask + Socket.IO Server (server/app.py)                │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ server/events.py — Event handlers (thin wrappers)   │ │
│  │   ↓ validate (server/validation.py)                 │ │
│  │   ↓ acquire write_lock (server/locks.py)            │ │
│  │   ↓ delegate to business logic                      │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │tasks.py  │ │workers.py│ │profiles  │ │scheduler.py│ │
│  │          │ │          │ │teams.py  │ │ (daemon    │ │
│  │          │ │          │ │          │ │  thread)   │ │
│  └────┬─────┘ └────┬─────┘ └──────────┘ └────────────┘ │
│       │             │                                     │
│  ┌────▼─────────────▼─────────────────────────────────┐ │
│  │  server/persistence.py (atomic_write, frontmatter)  │ │
│  └────────────────────────────┬───────────────────────┘ │
└───────────────────────────────┼─────────────────────────┘
                                │ File I/O
┌───────────────────────────────▼─────────────────────────┐
│  .bullpen/ (flat-file store)                             │
│  ├── config.json                                         │
│  ├── layout.json                                         │
│  ├── tasks/*.md (YAML frontmatter + markdown body)       │
│  ├── profiles/*.json                                     │
│  └── teams/*.json                                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Agent Subprocesses (per worker, background thread)      │
│  ┌────────────────────┐  ┌────────────────────────────┐ │
│  │ Claude CLI          │  │ Codex CLI                  │ │
│  │ --output-format     │  │ --full-auto -              │ │
│  │ stream-json         │  │                            │ │
│  └────────────────────┘  └────────────────────────────┘ │
│  ↑ stdin (prompt)  ↓ stdout (streaming JSON/text)        │
│  MCP stdio server (mcp_tools.py) ← agent tool calls      │
└─────────────────────────────────────────────────────────┘
```

---

## Findings

### MEDIUM — Write Lock Is a Single Global Mutex

**Location:** `server/locks.py`, `server/events.py`

All layout mutations across all workspaces contend on a single `threading.Lock`. This is safe and correct for the current single-user, few-workspace case. However, as the number of concurrent workspaces grows, or as the system handles long-running mutations (e.g., loading a large team layout), this lock becomes a bottleneck for all other Socket.IO event handlers.

**Recommendation:** Move the write lock into `WorkspaceState` so each workspace has its own lock. Cross-workspace operations (multi-workspace view updates) acquire workspace locks individually. This eliminates contention between independent workspaces.

---

### MEDIUM — Scheduler Is Not Integrated with the Task Queue

**Location:** `server/scheduler.py`, `server/workers.py`

The scheduler directly calls `start_worker()` when a trigger fires. This means:
1. If the worker is already busy, the trigger is silently dropped (no queuing).
2. If the worker is in an error state, the trigger still fires (may compound errors).
3. Trigger history is stored per-worker in the layout dict (not a proper job queue).

**Recommendation:** Route scheduler triggers through the same task queue mechanism as manual assignment. The scheduler should call `assign_task()` (which queues) rather than `start_worker()` (which executes). This ensures triggers are not silently dropped when the worker is busy.

---

### MEDIUM — No Event Replay or Persistence for Socket.IO Events

**Location:** `server/events.py`, `server/app.py`

Socket.IO connections are ephemeral. If a client disconnects (network hiccup, browser refresh) and reconnects:
1. The client receives a `state:init` event with the current layout/task state.
2. Any events emitted during the disconnection window (worker output lines, task status changes) are permanently lost.
3. Worker output buffers are capped at 100KB server-side — older output is dropped.

This is acceptable for the current use case (single browser session, localhost). For a multi-tab or remote access scenario, this becomes a usability problem.

**Recommendation:** For worker output, implement an append-only output log per worker execution (writing to `.bullpen/logs/<slot>-<task_id>.log`). The focus view reconnect path should tail this file rather than rely on the in-memory buffer.

---

### LOW — Workspace Registry Is Not Transactional

**Location:** `server/workspace_manager.py`

The workspace registry (`~/.bullpen/projects.json`) is updated by `register_project()` and `remove_project()`. These operations read, modify, and atomically write the registry file. However, there is no distributed lock around the registry — two concurrent `project:add` events from two browser tabs could produce a race condition on the projects.json file.

**Note:** In practice, this is unlikely to cause data loss because `os.replace()` is atomic. The race is on the read-modify-write cycle, which could cause one registration to overwrite another. The risk is low given the single-user context.

**Recommendation:** Acquire the workspace-level write lock before modifying the registry, or use a file lock (e.g., `fcntl.flock`) on `projects.json`.

---

### LOW — MCP Server Spawned Per-Task Rather Than as a Persistent Sidecar

**Location:** `server/agents/claude_adapter.py`

For each agent task, Bullpen generates a temp MCP config and passes it to the Claude CLI, which then starts a fresh MCP stdio connection to `mcp_tools.py`. This means:
1. Each task spawns a new MCP server process (or subprocess chain).
2. MCP startup latency is incurred per task.
3. The MCP server has no persistent state across tasks.

**Recommendation:** For agents that support it, run `mcp_tools.py` as a persistent sidecar and reuse the connection across tasks. This reduces per-task latency and simplifies cleanup.

---

### POSITIVE FINDINGS

- **Agent adapter abstraction is correct:** The ABC in `base.py` is minimal and stable. Adding a new agent requires implementing 4 methods, not touching the orchestration layer.
- **Workspace isolation is correct:** Each workspace has its own state, lock, scheduler, and Socket.IO room. Events do not cross workspace boundaries.
- **Vue 3 reactivity model is appropriate:** The CDN/no-build approach reduces deployment complexity for a localhost tool. The reactive state management (workspace → state → components) is clean.
- **Fractional indexing for task ordering:** Using lexicographic base-62 keys avoids the O(n) rewrite that sequential integer ordering would require on every reorder operation. This is the correct approach.

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| ARCH-01 | Global write lock is a single mutex across all workspaces | MEDIUM |
| ARCH-02 | Scheduler bypasses task queue, triggers may be silently dropped | MEDIUM |
| ARCH-03 | No event replay or persistent output logs for reconnection | MEDIUM |
| ARCH-04 | Workspace registry is not transactional under concurrent writes | LOW |
| ARCH-05 | MCP server spawned per-task rather than as persistent sidecar | LOW |
