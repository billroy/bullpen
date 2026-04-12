# Scalability Review — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Assessment of the system's ability to handle increased load: more concurrent workers, more tasks, more workspaces, more users, and higher request rates.

---

## Summary

Bullpen is architecturally a single-user, single-process tool. Its scalability ceiling is well-matched to its current use case (one developer, one team, ~10 active workers). Each major architectural component hits a hard ceiling before the system could support shared team deployment or high-frequency agent workflows.

---

## Findings

### HIGH — Flat-file storage does not scale with task volume

**Files:** `server/tasks.py`, `server/app.py:610–619` (load_state)

Every client connection loads the full task set into memory:

```python
# app.py load_state()
for fname in sorted(os.listdir(tasks_dir)):
    if fname.endswith(".md"):
        meta, body, slug = read_frontmatter(path)
        tasks.append(...)
```

And in `tasks.py`, `list_tasks()` reads every `.md` file on every call. There is no indexing, caching, or pagination at the persistence layer.

- At 100 tasks: imperceptible.
- At 1,000 tasks: measurable delay on state:init and every task-affecting event.
- At 10,000 tasks: blocking I/O in the main Flask thread; potential connection timeouts.

**Recommendation:** Add pagination support to `list_tasks()` and lazy-load tasks in the frontend. For scale beyond 10,000 tasks, a database backend (SQLite minimum) is necessary.

---

### HIGH — Single write_lock serializes all state mutations

**File:** `server/locks.py`, `server/events.py`, `server/workers.py`

All writes to layout.json (worker state changes), task updates, and config changes share a single `threading.Lock`. Under 10 concurrent workers each completing tasks and writing output, all state mutations queue sequentially. This effectively serializes parallel agent work at the persistence layer.

Measurement: if each state write takes 5ms (file I/O), 10 concurrent workers with 1 update/second each would experience average wait times of ~25ms per update — acceptable. At higher worker counts or faster update rates (streaming output events), this becomes a bottleneck.

**Recommendation:** Per-workspace locks (one lock per workspace) would allow concurrent operations across workspaces. Within a workspace, task-level locking (one lock per task file) would enable concurrent task updates.

---

### HIGH — Worker output buffer grows unbounded until task completion

**File:** `server/workers.py` (output streaming loop)

Worker output is captured into an in-memory buffer (`MAX_OUTPUT_BUFFER = 500,000` characters, ~500KB per worker). With 10 concurrent workers, peak memory use from output buffers alone is ~5MB. This is fine for a single user. For a shared server with 50+ concurrent workers across multiple users, this becomes 25MB of output buffers before the main application state.

More critically, if an agent generates output faster than the buffer is drained/trimmed, the trimming logic (`MAX_OUTPUT_BUFFER`) will cut the beginning of the output, potentially discarding important early output.

**Recommendation:** Stream output to a per-task log file instead of accumulating in memory. The frontend can tail the log file via a streaming endpoint. This eliminates the memory pressure and preserves full output history.

---

### MEDIUM — `build_file_tree()` is O(n) over all workspace files on each call

**File:** `server/app.py:499–554` (`build_file_tree`)

The file tree endpoint (`/api/files`) recursively walks the entire workspace directory on each request, with limits of `MAX_DEPTH=20` and `MAX_NODES=10,000`. On a large workspace (monorepo with 50,000 files), the walk would hit `MAX_NODES` but would have already performed 10,000 `os.path.islink` and `os.path.isdir` calls, blocking the request thread.

**Recommendation:** Cache the file tree with a short TTL (e.g., 5 seconds) keyed by workspace path and mtime. Invalidate on file write events.

---

### MEDIUM — git operations in `/api/commits` have no connection pooling

**File:** `server/app.py:280–318` (`get_commits`, `get_commit_diff`)

Each call to `/api/commits` spawns two `subprocess.run()` calls (git log + rev-list count). Each call to `/api/commits/<hash>/diff` spawns one `subprocess.run()` (git show). Under rapid commit tab refreshes (e.g., polling), these calls accumulate and create subprocess overhead. There is a 10-second timeout, but no rate limiting or caching.

**Recommendation:** Cache git log results with a 2–5 second TTL. Rate-limit per client to 1 request/second for git endpoints.

---

### MEDIUM — WorkspaceManager loads all workspaces at startup

**File:** `server/app.py:92–99`

At startup, `create_app()` calls `register_project()` for every entry in `~/.bullpen/projects.json`. If a user has 20+ registered workspaces, startup will attempt to initialize each one (read config, check for stale paths, start a scheduler thread). This is unnecessary for workspaces the user will not actively use in this session.

**Recommendation:** Lazy-load workspace state on first access rather than eagerly loading all workspaces at startup.

---

### LOW — SocketIO room membership grows with workspace count

**File:** `server/app.py:459–461`

On each Socket.IO connection, the client is joined to rooms for all active workspaces:

```python
for ws in manager.all_workspaces():
    join_room(ws.id)
```

With N workspaces, each connect/disconnect involves N room operations. This is fine at small N but adds overhead at scale.

---

### LOW — Scheduler polling interval is hardcoded at 30 seconds

**File:** `server/scheduler.py` (sleep interval in background thread)

The scheduler polls every 30 seconds. This means at-time triggers fire within 30 seconds of their configured time, not exactly at that time. For workflows requiring precise timing, 30-second jitter is significant.

---

## Positive Observations

- `atomic_write` prevents partial writes, which is correct for single-process use.
- `MAX_NODES = 10,000` and `MAX_DEPTH = 20` in `build_file_tree()` prevent runaway walks.
- `MAX_OUTPUT_BUFFER = 500,000` limits per-worker memory usage.
- `MAX_HANDOFF_DEPTH = 10` prevents infinite worker chain loops.
- Per-workspace state in `WorkspaceState` isolates concerns and is a good foundation for future per-workspace locking.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| SC1 | HIGH | Full task list loaded on every client connect — O(n) over task count |
| SC2 | HIGH | Single write_lock serializes all concurrent worker state updates |
| SC3 | HIGH | Worker output buffered in memory — 500KB per worker |
| SC4 | MEDIUM | File tree walk O(n) per request with no caching |
| SC5 | MEDIUM | Git subprocess calls not rate-limited or cached |
| SC6 | MEDIUM | All workspaces eagerly loaded at startup |
| SC7 | LOW | SocketIO room join overhead grows with workspace count |
| SC8 | LOW | Scheduler 30-second polling jitter |
