# Scalability Review — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Infrastructure/platform engineer evaluating as a potential acquirer

---

## Scope

Analysis of the system's capacity limits, bottlenecks, and scaling constraints across dimensions: users, workspaces, tasks, workers, concurrency, and data volume.

---

## Executive Summary

Bullpen is architected as a single-machine, single-user tool and scales well within those bounds. The flat-file persistence, in-process threading model, and write-serialized event handlers all impose hard limits on throughput that are appropriate for the intended use case (one developer, a handful of workspaces, dozens of workers). The system has no horizontal scaling path in its current form. An acquirer planning a hosted multi-user product will need to replace the persistence layer, the concurrency model, and the authentication system. These are substantial but predictable engineering investments, not fundamental architectural flaws.

---

## Current Capacity Estimates

| Dimension | Current Limit | Basis |
|-----------|-------------|-------|
| Concurrent users | 1 | Single-user auth |
| Workspaces per instance | ~10 | Registry not pruned; scheduler thread per workspace |
| Workers per workspace | ~20 | Write lock contention; output buffer memory |
| Tasks per workspace | ~10,000 | File tree walk cap (10K nodes) |
| Concurrent agent subprocesses | ~10 | OS thread limit; output buffer memory |
| Output buffer per worker | 100KB | Hard cap in `workers.py` |
| Prompt size | 100KB | Hard cap in `workers.py` |
| Payload size | 1MB | Hard cap in `validation.py` |
| File tree depth | 20 levels | Hard cap in `app.py` |

---

## Findings

### HIGH — No Horizontal Scaling Path

**Location:** `server/persistence.py`, `server/locks.py`, `server/workspace_manager.py`

All state is stored on the local filesystem. The write lock is an in-process `threading.Lock`. The workspace registry is a local JSON file. There is no mechanism for running multiple Bullpen processes against the same workspace, running across multiple machines, or load-balancing connections across instances.

This is **expected and correct** for the current use case but is a fundamental constraint for any hosted or team deployment.

**Growth path for an acquirer:**
1. Replace flat-file persistence with SQLite (single-machine multi-process)
2. Replace SQLite with PostgreSQL (multi-machine)
3. Replace in-process write lock with database transactions
4. Replace workspace-scoped Socket.IO rooms with a pub/sub system (Redis, NATS)
5. Run multiple stateless Flask workers behind a load balancer

**Recommendation:** Document the scaling roadmap in the architecture docs. No code change needed for MVP, but the roadmap should be explicit.

---

### MEDIUM — One OS Thread Per Worker Subprocess

**Location:** `server/workers.py`

Each running worker spawns a background Python thread to monitor the agent subprocess's stdout/stderr. With `async_mode="threading"`, Flask-SocketIO also uses threads for each connection. Under load (e.g., 10 workers running simultaneously across 5 workspaces):
- 10 worker monitor threads
- N connection threads (one per connected browser tab)
- 1 scheduler thread per workspace (5 scheduler threads)
- Total: 15+ active threads, plus Flask-SocketIO's internal threads

Python's GIL means CPU-bound work is serialized across these threads. For I/O-bound agent monitoring (waiting for subprocess output), this is acceptable. However, the thread-per-subprocess model does not scale beyond ~50 concurrent workers before hitting OS thread limits or excessive context switching.

**Recommendation:** For a scaled deployment, replace per-subprocess threads with an async event loop (`asyncio` + `aiohttp`) and use `asyncio.create_subprocess_exec()` for agent process monitoring. This supports hundreds of concurrent subprocesses per process instance.

---

### MEDIUM — Write Lock Serializes All Workspace Mutations

**Location:** `server/locks.py`, `server/events.py`

All Socket.IO event handlers that mutate layout or task state acquire a single write lock. With a 60Hz tick rate from the scheduler and concurrent events from the UI, the lock contention window is narrow but non-zero. Under sustained load (e.g., 10 workers completing tasks simultaneously and emitting state updates), the write lock becomes a queue that limits throughput to approximately one mutation per lock-hold duration.

**Recommendation:** Per-workspace write locks (see architecture review) would eliminate cross-workspace contention. Within a workspace, fine-grained locking (e.g., per-task lock for task updates) could further improve throughput.

---

### MEDIUM — Output Buffer Capped at 100KB Per Worker (No Overflow Handling)

**Location:** `server/workers.py`

Each worker's output is buffered in memory (capped at 100KB). When the cap is reached, older output is dropped. This means:
1. Long-running agent tasks that produce verbose output will have truncated history.
2. The focus view for a long-running worker will show incomplete output.
3. There is no way to retrieve truncated output after the fact.

**Recommendation:** Implement an append-only log file per worker execution in `.bullpen/logs/`. The in-memory buffer can remain for real-time streaming, but the file serves as the durable record. The focus view reconnect path should read from the file.

---

### LOW — Scheduler Thread Per Workspace

**Location:** `server/scheduler.py`, `server/workspace_manager.py`

Each registered workspace starts its own `Scheduler` daemon thread. With 10 workspaces, there are 10 scheduler threads, each sleeping for 60 seconds and waking to check triggers. This is very low overhead per thread, but it does not scale cleanly to hundreds of workspaces.

**Recommendation:** Replace per-workspace scheduler threads with a single shared scheduler that dispatches triggers per workspace. Use a priority queue keyed by next trigger time.

---

### LOW — Task File Iteration Is O(n) Per Read

**Location:** `server/tasks.py`

Listing all tasks for a workspace requires iterating all `.md` files in `.bullpen/tasks/`. Filtering by status, priority, or tags happens in Python after reading all files. For a workspace with 10,000 tasks (the hard cap), this iteration is slow and memory-intensive.

**Recommendation:** For large task counts, maintain an index file (e.g., `tasks/index.json`) with task metadata (id, title, status, priority, tags, order) that can be read without parsing all frontmatter. This reduces list-tasks latency from O(n * file_size) to O(index_size).

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| SCALE-01 | No horizontal scaling path (fundamental constraint) | HIGH |
| SCALE-02 | One OS thread per worker subprocess | MEDIUM |
| SCALE-03 | Write lock serializes all workspace mutations | MEDIUM |
| SCALE-04 | Output buffer capped at 100KB with no overflow to disk | MEDIUM |
| SCALE-05 | Scheduler thread per workspace | LOW |
| SCALE-06 | Task file iteration is O(n) | LOW |
