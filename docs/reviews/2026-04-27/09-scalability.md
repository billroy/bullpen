# Scalability Review
*Bullpen — 2026-04-27*

## Executive Summary

Bullpen is architected as a single-process, single-machine application. It uses Flask in threading mode with Socket.IO, flat-file storage (`.bullpen/` directories of Markdown files), and per-task worker subprocesses. This architecture is well-suited for small teams running on a personal server or a modest cloud VM, and it delivers genuine simplicity: no database to manage, no queue service to operate, no build pipeline. However, the design embeds several hard scalability ceilings that a buyer must understand before committing to growth beyond a handful of concurrent users or workspaces. Horizontal scaling is not possible without architectural surgery. Vertical scaling provides headroom for small-to-medium deployments but plateaus quickly as worker subprocess count, file I/O, and Socket.IO broadcast overhead grow. For a buyer planning to serve tens of teams or hundreds of concurrent workers, this architecture is a liability.

---

## Current Architecture Limits

| Dimension | Bottleneck | Practical Ceiling (estimated) |
|-----------|-----------|-------------------------------|
| Concurrent users per workspace | Socket.IO broadcasts to all clients on every event | ~20–50 before broadcast latency is noticeable |
| Workspaces per instance | Single registry, single process, per-workspace state objects in memory | ~10–30 before memory and GIL contention degrade responsiveness |
| Tasks per workspace | Directory scan of all `.md` files on every task listing | Degrades past ~1,000 tasks; painful past ~5,000 |
| Workers per workspace | One subprocess per active worker per task | Bound by OS process limits and host CPU/RAM; ~20–50 concurrent workers is practical |
| Data volume | Flat files with no indexing | Linear read time; no query capability |
| Message throughput | Flask threading + GIL; synchronous Socket.IO dispatch | Thousands of events/second is not achievable |
| Payload size | 1 MB hard cap | Suitable for text-based tasks; blocks large artifact workflows |

---

## Scaling Dimensions

### Users
Socket.IO broadcasts every state change to every connected client in a workspace. With few users per workspace this is negligible. As the user count grows, each event triggers proportionally more I/O and CPU serialization work in a single-threaded event loop. There is no per-user subscription filtering. Large organizations that put dozens of observers on a single workspace will observe latency growth that cannot be addressed without moving to a pub/sub model (e.g., Redis + Socket.IO adapter).

### Workspaces
Each workspace holds in-memory state objects in a single Python process protected by the GIL. Adding workspaces adds memory pressure and increases lock contention. There is no lazy-loading or eviction of idle workspace state. Ten to thirty workspaces on a well-specced machine is a reasonable limit before response times for active workspaces degrade.

### Tasks
Task listing is implemented as a directory scan that reads every `.md` file. This is an O(n) full-read operation — not just O(n) file count, but O(total bytes in all task files) because frontmatter must be parsed to extract metadata. A workspace with 5,000 tasks and 10 KB average task size requires reading 50 MB of files on every list request. There is no caching layer, no index, and no pagination at the storage layer.

### Workers
Each active worker runs as a child subprocess. The OS process table, available file descriptors, and host RAM are the binding constraints. On a 4-core, 8 GB VM, 20–50 concurrent worker subprocesses is a practical upper bound before context-switching overhead and memory pressure degrade throughput. There is no worker pool, no queue for pending work, and no back-pressure mechanism — a spike in triggered tasks will spawn a spike in subprocesses.

### Data Volume
Flat Markdown files have no indexing, no full-text search capability at scale, and no transactional guarantees. Concurrent writes to the same task file are not protected by a lock visible to external processes. Token usage tracking is stored per-ticket in file frontmatter, which must be read and rewritten for each update — this is a read-modify-write pattern with no atomicity.

---

## Horizontal Scaling Assessment

**Bullpen cannot scale horizontally in its current form.** The following mechanisms prevent it:

1. **Flat-file storage with no shared backend.** Each instance has its own `.bullpen/` directory. There is no shared database, distributed cache, or object store. Two instances cannot share state.

2. **Socket.IO without a message broker.** Socket.IO's horizontal scaling requires a shared adapter (Redis, MongoDB, etc.) to broadcast events across nodes. No adapter is configured. Events emitted on node A will not reach clients connected to node B.

3. **In-process workspace state.** Workspace registry and per-workspace state objects live in the memory of a single Python process. This state cannot be shared across machines.

4. **Worker subprocesses tied to host filesystem.** Workers read and write files relative to the host's `.bullpen/` directory. Moving workers to separate hosts would require shared network filesystem or a different storage model.

A horizontally scalable version of Bullpen would require, at minimum: replacing flat-file storage with a shared database (PostgreSQL, SQLite with WAL on shared NFS, or equivalent), adding a Redis Socket.IO adapter, and externalizing workspace state. This is a significant architectural investment.

---

## Vertical Scaling Assessment

Within a single machine, vertical scaling provides meaningful headroom:

- **CPU:** Adding cores helps with subprocess parallelism (each worker subprocess can run on its own core) but does not help with the Flask/Socket.IO event loop, which is GIL-bound. Hyperthreading provides marginal benefit for I/O-heavy workloads.
- **RAM:** Increasing RAM allows more concurrent worker subprocesses and larger in-memory workspace state. Practical benefit up to ~32 GB; beyond that, the GIL and process model become the binding constraint.
- **Storage I/O:** Fast NVMe SSD significantly improves task-listing performance and worker file I/O. This is the highest-return hardware investment for a heavily loaded single-node deployment.
- **Practical ceiling:** A well-tuned single-node instance (8-core, 32 GB RAM, NVMe) could support 3–5 active workspaces with 10–20 concurrent workers each and ~2,000 tasks per workspace before user-visible latency becomes unacceptable.

---

## Findings

### HIGH — O(n) Full Directory Scan on Every Task Listing

Every request to list tasks scans the workspace's task directory and parses every `.md` file. There is no in-memory index, no persistent index, no pagination at the storage layer, and no caching. This is a blocking read in the Flask request handler. As task history grows, list latency grows linearly and eventually dominates all other response times.

**Threshold:** Noticeable past ~1,000 tasks; unacceptable past ~5,000 tasks for interactive use.

**Remediation:** Introduce an in-memory index (dict keyed by task ID, rebuilt on startup, updated incrementally on write) or migrate to a lightweight embedded database (SQLite). Either approach can be done without changing the external API.

---

### HIGH — No Horizontal Scaling Path

The combination of flat-file storage, in-process state, and un-brokered Socket.IO means the system cannot run as more than one instance. There is no active-passive failover, no blue-green deployment, and no load-balancer-friendly health check. A single process failure takes down all workspaces simultaneously.

**Remediation:** Short-term: add a `/health` endpoint and configure systemd or Docker health checks for automatic restart. Medium-term: evaluate SQLite WAL mode + shared filesystem as a low-effort step toward multi-instance readiness. Long-term: Redis adapter for Socket.IO, PostgreSQL for storage.

---

### HIGH — Unbounded Worker Subprocess Spawning

When tasks are triggered (manually or by the scheduler), a new subprocess is spawned for each worker. There is no queue, no concurrency cap per workspace, and no global process limit. A workspace with many scheduled tasks firing simultaneously will spawn a large number of subprocesses, potentially exhausting OS process limits or host RAM.

**Remediation:** Implement a worker pool or concurrency cap (e.g., max N active subprocesses per workspace, additional work queued). The `MAX_HANDOFF_DEPTH=10` guard prevents infinite chain recursion but does not address spawn storms from independent tasks.

---

### MEDIUM — GIL-Bound Event Loop Under Load

Flask in threading mode allocates one thread per request. The Python GIL serializes CPU-bound work across all threads. Socket.IO event dispatch is CPU-bound (serialization, encryption if TLS is terminated in-process). Under moderate concurrent load, event latency will increase as threads queue behind the GIL. This cannot be fixed without moving to an async framework (Quart + python-socketio async) or using multiple processes (gunicorn multiprocess), which reintroduces the in-process state sharing problem.

**Remediation:** Profile under realistic load before the issue manifests in production. If GIL contention is observed, consider moving to `gevent` mode for Socket.IO (drops the GIL during I/O) or gunicorn + Redis state externalization.

---

### MEDIUM — No Rate Limiting on Core API Endpoints

Beyond a login throttle, there is no rate limiting on task creation, worker triggering, or file upload endpoints. A misbehaving agent or a runaway automation can flood the system with requests, triggering unbounded subprocess spawning and file I/O.

**Remediation:** Add per-workspace and per-IP rate limits on task-create, worker-trigger, and file-upload endpoints. Flask-Limiter adds this with minimal code changes.

---

### MEDIUM — Socket.IO Broadcasts Entire State on Every Change

State change events are broadcast to all connected clients without per-client filtering or delta compression. In a workspace with many users watching, every task update generates N full-object serializations (one per client). This is a common Socket.IO anti-pattern that becomes expensive at scale.

**Remediation:** Move to targeted room-based emit and consider delta/patch payloads for high-frequency updates (e.g., worker log streaming). This is a medium refactor but high-impact for user-facing responsiveness.

---

### LOW — No Connection Pooling for File I/O

File handles are opened and closed per operation. On high-throughput deployments this adds syscall overhead. The flat-file model does not support connection pooling by nature, but the absence of any I/O batching or write coalescing means every individual update is a separate filesystem transaction.

**Remediation:** If remaining on flat files, consider write coalescing (buffer updates for 50–100ms and flush as a batch). If migrating to SQLite, connection pooling is available natively.

---

### LOW — Scheduler Polling at Fixed 60-Second Interval

The background scheduler polls all workspaces every 60 seconds to check for due tasks. This is a linear scan across all workspaces and their tasks. At small scale this is imperceptible; at dozens of workspaces with thousands of tasks each, the scheduler thread itself becomes a source of periodic latency spikes.

**Remediation:** Replace fixed-interval polling with a priority queue sorted by next-due time. Only workspaces/tasks due within the current window need to be examined.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 3     |
| MEDIUM   | 3     |
| LOW      | 2     |

---

## Recommendations

1. **For small teams (1–5 workspaces, <500 tasks, <10 concurrent workers):** The current architecture is adequate. Prioritize adding a `/health` endpoint and systemd restart-on-failure as immediate operational hygiene.

2. **For medium teams (5–15 workspaces, up to 2,000 tasks, up to 30 concurrent workers):** Address the O(n) task scan (in-memory index or SQLite) and add subprocess concurrency limits before deploying. These are the binding constraints at this scale.

3. **For larger teams or SaaS aspirations:** The architecture requires fundamental changes. Budget for: SQLite or PostgreSQL migration, Redis Socket.IO adapter, async framework evaluation, and a proper job queue (Celery, RQ, or equivalent). This is a 2–4 engineer-quarter effort to do correctly.

4. **Immediate risk mitigation:** Add subprocess count limits and rate limiting on task-create/worker-trigger endpoints before any production deployment to prevent runaway resource consumption.

5. **Set buyer expectations clearly:** Bullpen's flat-file, single-process model is a deliberate simplicity trade-off. It is not a proto-scalable system that can grow into enterprise use with minor tuning. A buyer planning for significant growth should factor architectural rewrite costs into their acquisition model.
