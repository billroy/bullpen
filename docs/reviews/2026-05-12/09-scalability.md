# Scalability Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Platform engineering lead evaluating scalability for acquisition / investment

---

## Executive Summary

Bullpen's scalability envelope is appropriate for its intended use case: a single-team, single-host AI agent orchestration tool. The flat-file storage model, process-level locking, and single-server deployment are deliberate design choices that minimize operational complexity. The system performs well within its design bounds (estimated: up to ~500 tasks per workspace, up to ~20 simultaneous workers on modern hardware, up to ~10 concurrent browser clients). The risks identified here are not defects in the current product — they are constraints on the product's growth trajectory that a buyer should understand before planning a SaaS expansion.

---

## Findings

### HIGH — Task directory listing scales linearly; no indexing

**Location:** `server/tasks.py` — `list_tasks()` calls `os.listdir()` over `.bullpen/tasks/`

**Detail:** All task queries require a full directory scan followed by per-file frontmatter parsing. As the task count grows:

- `os.listdir()` on a directory with 10,000 entries is measurably slow on most filesystems (ext4, HFS+, APFS) — typically 10–50ms for 10K entries.
- Each task file must be opened and its frontmatter parsed to extract status, tags, and priority for filtering — O(n) read operations on every list request.
- The Kanban board, which renders tasks grouped by column, triggers this full scan on load and on most Socket.IO task events.

At 100 tasks the overhead is imperceptible. At 1,000 tasks it becomes noticeable. At 5,000 tasks it degrades the interactive experience meaningfully.

**Recommendation:** Short-term: Add an in-memory task index (a dict keyed by slug, populated at startup, updated on mutation events) to eliminate per-request directory scans. This index already exists in spirit as tasks are loaded into memory — formalize it as the authoritative in-process cache. Longer-term: scope a SQLite migration (SQLite is file-based, no server required, and provides indexed queries with ACID semantics — documented in `docs/sqlite.md`).

---

### HIGH — Single `write_lock` is an application-wide serialization point

**Location:** `server/app.py` or `server/workers.py` — `write_lock` RLock used for all layout and task mutations

**Detail:** All state-modifying operations (task creation, worker state changes, layout updates) acquire `write_lock` before writing. This is correct for single-process concurrency safety, but it means:

1. All writes are serialized — a slow file write (e.g., export of a large workspace) blocks all other mutations for its duration.
2. Read operations that require consistent snapshots may hold the lock unnecessarily.
3. There is no per-workspace locking granularity — a write to workspace A blocks writes to workspace B.

Under normal usage (one team, infrequent concurrent writes) this is not a bottleneck. Under load (many workers completing simultaneously, many browser clients creating tasks) lock contention becomes measurable.

**Recommendation:** Introduce per-workspace locks (already partially present in `WorkspaceState.lock`) and use them instead of the global `write_lock` for workspace-scoped mutations. This parallelizes writes across workspaces without changing single-workspace serialization semantics.

---

### MEDIUM — Worker subprocess count is unbounded

**Location:** `server/workers.py` — worker start handling

**Detail:** There is no configured global limit on the number of simultaneous agent subprocesses. Each running worker spawns a subprocess (and potentially a git worktree). On a system with 20 worker slots active simultaneously, this creates 20 subprocesses, each of which may spawn child processes of their own (the agent CLIs spawn Node.js or Python interpreters). Resource limits (file descriptors, PIDs, memory) depend entirely on the host OS configuration.

The `agent_timeout_seconds` configuration provides a per-worker execution time limit, which bounds runaway individual agents. But there is no limit on total concurrent workers.

**Recommendation:** Add a `max_concurrent_workers` configuration option (default: 8, configurable in `config.json`) that queues worker starts beyond the limit rather than spawning immediately. Implement this in the worker start handler as a semaphore or counter check. This prevents resource exhaustion on small hosts and enables capacity planning.

---

### MEDIUM — Socket.IO event fan-out is unbounded per workspace

**Location:** `server/events.py` — all `emit()` calls to workspace rooms

**Detail:** Every task update, worker state change, and output chunk is emitted to all connected clients in the workspace room. With 2 clients, this doubles write work. With 50 clients (unlikely in a small-team product, but possible for a hosted SaaS offering), it multiplies network write load by 50x. Agent output streaming — which can emit hundreds of events per second per active worker — is particularly heavy under multi-client load.

**Recommendation:** For the current single-team use case, no action is needed. For a future hosted offering: implement client-side selective subscription (clients subscribe to specific worker output streams rather than receiving all output events) and server-side output batching (buffer output chunks for 100ms and emit one batch event rather than one event per chunk).

---

### MEDIUM — Worktree creation scales with active workers; no cleanup limit

**Location:** `server/workers.py` — git worktree creation logic

**Detail:** When a worker operates in worktree mode, it creates a git worktree (a separate working directory linked to the same git repository). Worktrees are created at task start and cleaned up at task completion or on explicit cleanup. If cleanup fails (e.g., a worker is killed mid-task), worktrees accumulate. There is a cleanup mechanism documented in the codebase, but no audit of how many worktrees exist or automatic reaping of stale ones.

On a repository with many task executions over time, stale worktrees consume disk space and can confuse `git status` and `git branch` output.

**Recommendation:** Add a startup check that lists all `git worktree list` entries and reaps any that correspond to task IDs not in the current task list. Log the reap events for operator awareness. Add a health-check endpoint that reports worktree count.

---

### MEDIUM — Flat-file persistence cannot support multi-host deployment

**Detail:** (Cross-references `08-architecture.md`) The persistence model — local filesystem, process-level locking — is incompatible with horizontal scaling:

1. A second server process on the same host would race on file writes (the RLock is not inter-process).
2. A second server process on a different host has no access to the `.bullpen/` directory on the first host.
3. There is no replication, no shared storage abstraction, and no conflict resolution mechanism.

This is a boundary condition, not a defect. But a buyer planning a hosted multi-tenant offering must understand that the persistence layer requires a full replacement (SQLite or PostgreSQL) before the product can scale beyond a single host.

**Recommendation:** Document the single-host constraint formally. Maintain `docs/sqlite.md` (already exists) as the forward path for persistence layer migration.

---

### LOW — In-memory scheduler state is lost on restart

**Location:** `server/scheduler.py`

**Detail:** The background scheduler manages time-based worker activation (`at_time`, `on_interval` triggers). Scheduler state is derived from the worker configuration at startup. If the server restarts mid-interval, the next execution time is recalculated from startup time, not from the last execution time. This means:

- An `on_interval: 60m` worker that ran 50 minutes ago will not run for another 60 minutes after restart, instead of 10 minutes.
- Workers with `at_time` triggers will miss their window if the server is down at that time and does not catch up.

**Recommendation:** Persist the last-execution timestamp for each scheduled worker to `.bullpen/` (e.g., in `layout.json` alongside worker config). On startup, compute the next-due time from the persisted last-execution timestamp rather than from now.

---

### LOW — `os.listdir()` on large log directories may slow health check

**Location:** `.bullpen/logs/` — per-task execution logs

**Detail:** Logs accumulate indefinitely in `.bullpen/logs/`. There is no documented log rotation or maximum log retention policy. Over time, with many agent runs across many tasks, the log directory may grow to contain thousands of subdirectories. Operations that scan this directory (e.g., during workspace export or admin inspection) will slow proportionally.

**Recommendation:** Implement log retention: automatically delete log directories for tasks that are archived and whose logs are older than N days (configurable, default: 30). Add a log-retention configuration option to `config.json`.

---

## Scalability Boundaries (Reference)

| Dimension | Estimated Comfortable Range | Estimated Degradation Threshold |
|---|---|---|
| Tasks per workspace | 0–500 | ~1,000 (listdir + parse overhead) |
| Simultaneous active workers | 0–10 | ~20 (subprocess resource pressure) |
| Concurrent browser clients | 0–5 | ~15 (Socket.IO fan-out overhead) |
| Workspaces (multi-project) | 0–10 | ~50 (global lock contention) |
| Agent output events/sec | 0–200 | ~500 (Socket.IO backpressure) |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 4 |
| LOW | 2 |
