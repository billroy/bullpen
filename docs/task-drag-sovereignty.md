## Task Drag Sovereignty: Human vs. Worker Control of Tickets

Status: Proposal

---

### Problem

Dragging a ticket between kanban columns calls `task:update` with the new status. This writes to the task's frontmatter and nothing else. It does not interact with the worker system at all — it doesn't touch `task_queue`, doesn't stop running processes, doesn't clear `assigned_to`. This creates three classes of bug:

1. **Queued task dragged away.** Task stays in the worker's `task_queue`. When the worker reaches it, it reclaims the task, sets status to `in_progress`, and processes it. The user's drag is silently undone.

2. **In-progress task dragged away.** The Claude subprocess keeps running. When it completes, `_on_agent_success` overwrites the status with the worker's disposition. The drag is silently undone, and work was wasted (or worse, unwanted changes were committed).

3. **Task dragged into `assigned` or `in_progress`.** These statuses have mechanical meaning — they imply a worker relationship. Dragging a task into `assigned` puts it in a column where it looks queued but no worker has it in `task_queue`. It's stranded.

### Column Taxonomy

Columns fall into two categories based on who legitimately controls tasks there:

| Category | Columns | Controller |
|----------|---------|------------|
| **Human columns** | inbox, backlog, review, done, blocked, custom | Human moves tasks in/out freely |
| **Worker columns** | assigned, in_progress | Worker system manages entry/exit |

The distinction is mechanical: worker columns have invariants (task must be in a `task_queue`, may have a running process). Human columns have no invariants beyond the status string.

### Proposal

#### Rule 1: Prevent drag INTO worker columns

Tasks cannot be dragged into `assigned` or `in_progress` via the kanban board. These statuses are entered only through the worker assignment path (`assign_task`) which correctly maintains `task_queue` and `assigned_to`.

_Implementation:_ `KanbanTab.js` `onDrop` checks the target column key. If the target is `assigned` or `in_progress`, reject the drop (no-op or show a toast: "Use the worker to assign tasks"). The data model marker is a `worker_managed: true` flag on the column config, or a hardcoded set — the latter is simpler since these two columns are structurally special, not user-configurable.

#### Rule 2: Drag OUT of `assigned` dequeues

When a task with status `assigned` is dragged to a human column, the server must remove it from the owning worker's `task_queue` and clear `assigned_to`. The task cleanly leaves the worker system.

_Implementation:_ In `on_task_update` (events.py), when the incoming status differs from the current status, and the current status is `assigned`:

1. Read the task's `assigned_to` field to find the slot index.
2. Remove the task ID from that worker's `task_queue` in the layout.
3. Clear `assigned_to` on the task.
4. Save layout, emit `layout:updated`.

This is safe because the task is queued but not running — no process to kill.

#### Rule 3: Drag OUT of `in_progress` stops the agent

When a task with status `in_progress` is dragged to a human column, the server must:

1. Find the worker via `assigned_to`.
2. Terminate the running subprocess (same as `stop_worker`).
3. Remove the task from `task_queue`.
4. Clear `assigned_to`, set worker state to `idle`.
5. Save layout, emit updates.
6. If the worker has remaining tasks in its queue, trigger `start_worker` to advance.

This is the "kill the runaway agent" path. It is intentionally more disruptive than stop_worker (which keeps the task in queue as `assigned`). Dragging away means "I don't want this worker touching this task anymore."

_Implementation:_ In `on_task_update`, when current status is `in_progress` and the new status is a human column, call a new helper `_yank_from_worker(bp_dir, task_id, socketio, ws_id)` that encapsulates steps 1-6.

#### Rule 4: No special behavior for human-to-human drags

Moving a task between human columns (inbox → backlog, review → done, etc.) continues to work exactly as today — a simple status update. No worker system interaction needed.

### The Stop Button vs. Drag-Away

These serve different intents:

| Action | Intent | Task stays with worker? | Process killed? |
|--------|--------|------------------------|-----------------|
| **Stop button** | "Pause this, I'll resume later" | Yes (stays in queue as `assigned`) | Yes |
| **Drag away** | "Take this task back entirely" | No (removed from queue) | Yes |

Both kill the process. The difference is what happens to the queue relationship.

### Edge Cases

**Task is in_progress and worker finishes between drag and server processing.** The `_on_agent_success` path and the `on_task_update` path both hold `_write_lock`. One will win. If the drag wins, the process is killed (or already exited) and the task moves. If the agent wins first, the task has already moved to disposition — the drag then just moves it from the disposition column to the target, which is a clean human-to-human move.

**Worker has `on_queue` watching a column the task is dragged into.** This is fine — `check_watch_columns` runs after status changes and the worker will claim the task through the proper `assign_task` path.

**Custom columns used as disposition targets.** Custom columns are human columns. A worker depositing a task into `"qa"` via disposition is the worker relinquishing control — the task is in a human column with no queue relationship. Dragging it elsewhere is a simple human move.

### Not Addressed Here

- **Dragging between workers.** Currently not supported (you'd unassign and reassign). Could be a future feature but orthogonal to this proposal.
- **Batch operations.** Selecting multiple tickets and moving them. Same rules would apply per-task.
- **Column deletion with worker-status tasks.** The column manager already handles migration. Worker columns should probably be undeletable via UI (they already effectively are since removing `assigned`/`in_progress` would break the worker system).
