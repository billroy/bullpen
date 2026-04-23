# Queue Bug Story

Date: April 23, 2026

## Summary

This was not a single bug. It was a cascade of interacting faults that all
presented as one user-visible symptom:

> Drag one ticket from Inbox to Approved. It gets claimed and moves to In
> Progress. Try to drag a second ticket to Approved. The drop appears to be
> rejected, and after that drag-and-drop and cancellation behavior can become
> erratic across the whole board.

The difficulty was that the visible symptom suggested a kanban drop bug, while
the actual breakage lived deeper in the queue-fed worker lifecycle. The second
drop *did* reach the server. The server *did* move the ticket to `approved`.
The queue-fed worker then auto-claimed it, hit a stale-worktree failure, and
the error handler itself crashed while trying to record retry history. That
secondary crash left Bullpen in a half-cleaned-up state and made the control
plane feel haunted.

## The Fault Chain

The final fault chain looked like this:

1. A ticket is dragged into `approved`.
2. An `on_queue` worker watching `approved` claims it and starts work.
3. A second ticket is dragged into `approved`.
4. The second `task:update` event is accepted by Socket.IO and the ticket is
   written to `approved`.
5. The queue-fed worker auto-claims that ticket too.
6. Worker startup attempts to create a worktree branch derived from the ticket
   id, for example `bullpen/<task-id>`.
7. Git rejects the setup because that branch already exists from an earlier run.
8. Bullpen enters `_on_agent_error()` to record a retry or block the task.
9. `_on_agent_error()` reads the ticket `history` field back from frontmatter.
10. That `history` field is malformed because a previous retry detail contained
    a literal newline from `git` stderr.
11. The retry row is parsed back as a string rather than a dict.
12. `_on_agent_error()` does `h.get("event")` on that string and crashes with:

```text
AttributeError: 'str' object has no attribute 'get'
```

At that point the system is no longer dealing with one clean startup failure.
It is dealing with a failure while handling failure. That is why later drags,
stop actions, and cancel attempts could look unrelatedly broken.

## Why It Was So Hard To Find

### 1. The symptom pointed at the wrong layer

The user experience said "kanban drop rejected." That naturally points toward:

- drag target wiring
- column acceptance rules
- custom-column bugs
- worker-watch arbitration

But the drop was not actually being rejected at the event boundary. Once debug
logging was enabled, Bullpen clearly showed:

- packet received
- `task:update` handler invoked
- `task:updated` emitted with `status: "approved"`

So the board symptom was downstream of the drop, not at the drop itself.

### 2. Clean-room repros worked

In a temporary workspace with simple mock workers, the queue-fed claim path
looked healthy:

- first worker busy
- second ticket enters watched column
- second idle worker claims it

That pushed suspicion back toward the frontend, because the isolated server
behavior appeared correct. The hidden condition was stale repo/worktree state
inside the real `pr-workflow-test` workspace.

### 3. The first failure masked the second failure

If worktree setup had simply failed cleanly, the diagnosis would have been much
shorter: "stale branch/worktree reuse bug."

Instead, the worktree failure triggered an error-path crash inside retry
history handling. The original fault became obscured by a second, more chaotic
fault in the cleanup/reporting path.

### 4. Global locking amplified the damage

Bullpen uses a shared write lock across task and worker mutations. That is
reasonable for consistency, but it means a bad worker path can poison unrelated
UI actions:

- later drags can stall behind the same shared lock
- stop/cancel can appear to fail
- the board can feel globally broken even though the root cause is one worker
  startup failure

This created the impression of a kanban-wide breakdown rather than a queue-fed
worker failure.

### 5. Frontmatter is brittle for multiline structured data

Bullpen stores `history` in frontmatter using inline objects. That is fragile
when details contain raw newlines, such as:

```text
fatal: a branch named 'bullpen/<task-id>' already exists
```

The retry detail split the inline object across lines, so on the next read the
row came back as a string instead of a dict. The persistence format turned a
normal startup failure into a corrupted metadata failure.

### 6. Several bugs were adjacent and easy to conflate

Along the way, multiple real issues surfaced:

- queue-fed workers were not updating `last_trigger_time`
- worker auto-start from inside locked event paths risked deadlock
- stop/cancel path lookup was weaker than yank lookup
- worktree branch reuse was not idempotent
- multiline retry details could corrupt `history`

All of these touched the same area of the product. That made it easy to fix one
real problem while still not having found the one currently driving the user's
symptom.

## The Adventure

The debugging sequence went roughly like this:

1. Start with the obvious theory: watch-column claiming is rejecting the second
   ticket.
2. Read the queue-fed worker code and existing tests.
3. Notice that unit coverage proves simple claiming, but not the real kanban
   event path.
4. Reproduce the watcher logic in a clean temp workspace and see it work.
5. Suspect the frontend and spend time on drag/drop hypotheses.
6. Learn from the live workspace that after a refresh the symptom still
   survives while a worker is running, which points away from a pure client bug.
7. Add websocket debug logs and discover that the second `task:update` *does*
   arrive.
8. See `task:updated` emitted with `status: "approved"`, proving the drop
   itself succeeded.
9. Capture the Python traceback from the worker thread.
10. Realize the queue-fed worker is failing during worktree setup, then failing
    again while handling that failure.
11. Inspect the ticket file and find the malformed `history` row on disk.
12. Finally separate the stack into its component bugs instead of treating it as
    one mysterious kanban problem.

That was the turning point. Before the traceback, every theory still had to
compete with the user's visible symptom. After the traceback, the system told us
exactly where it was dying.

## Concrete Bugs Identified

### Bug 1: Worktree setup is not idempotent

Bullpen derives worktree branch names directly from the ticket id. If the
branch already exists, startup fails. For queue-fed workers this is especially
bad because downstream retries and reclaims may hit the same deterministic
failure repeatedly.

### Bug 2: Retry history serialization cannot safely handle multiline detail

Retry details were written directly into inline frontmatter objects. Multiline
stderr from Git broke the serialization format and caused readback corruption.

### Bug 3: Error handling trusted `history` shape too much

`_on_agent_error()` assumed every history row was a dict and did not defend
against malformed legacy/string rows.

### Bug 4: Worktree setup failure was treated as retryable

"Branch already exists" is deterministic and should not go through the normal
retry loop. Retrying only creates more noise and more chances to hit broken
cleanup paths.

### Bug 5: Stop/cancel path was weaker than yank

The stop path relied on narrower process lookup assumptions than the yank path,
which made the safety valve less reliable under messy runtime conditions.

### Bug 6: Auto-starting workers from inside locked event flows is risky

Queue-fed auto-start can be triggered from task updates. If worker startup
re-enters mutation-heavy logic while the global lock is still conceptually "in
flight," failures become much harder to contain.

## Lessons

### Product lesson

Queue-fed workers were never seriously exercised under stale real-world repo
state. The happy path was tested. The "same queue after restart, same repo after
partial work, same branch after previous attempt" path was not.

### Persistence lesson

Inline frontmatter objects are too brittle for arbitrary structured operational
data. If Bullpen wants to store retry history, worker runs, or tool failures, it
needs either:

- stricter escaping/serialization rules, or
- a safer structured format for complex history rows

### Error-handling lesson

The error path must be more robust than the happy path, not less. In this case:

- startup failure should not be retryable
- history parsing should be defensive
- malformed operational metadata should degrade gracefully, never crash cleanup

### Debugging lesson

The live failing workspace mattered more than the clean-room repro. The clean
repro proved that the abstract watcher logic worked. The live workspace proved
that stale branch/worktree state and malformed frontmatter were what actually
made the system misbehave.

## Bottom Line

This bug was difficult to find because the visible symptom lived at the kanban
surface, while the true failures lived in:

- queue-fed worker startup
- stale worktree lifecycle
- retry-path serialization
- retry-path crash handling
- shared mutation locking

It looked like "the second drop is rejected."

It was really:

> "the second drop succeeds, the queue-fed worker auto-claims it, worktree setup
> deterministically fails, retry history is written in a format that cannot
> survive multiline stderr, the error handler crashes, and the rest of the app
> starts feeling cursed."

That is why it took so long. The symptom lied, the clean repro lied, and only
the traceback told the truth.
