# Value-Change Worker Stampede Control

## Status

Proposed.

This specification refines the trigger lifecycle in
[Value Cell Formulas](value-cell-formulas.md) and
[Value Change Trigger](value-change-trigger.md). Where those documents imply
one ticket per matching event, this document supersedes them with compacted
pending work.

## Summary

Formula recalculation is already one server-owned generation. The subsequent
worker dispatch is not: one generation can create many tickets for the same
worker and start every distinct matching worker together.

Use the existing task queues and worker states to control that fan-out:

- group one generation's matching events by reacting worker slot;
- keep at most one pending value-trigger ticket per worker;
- merge later qualifying triggers into that pending ticket;
- for each Value, preserve the first `old_value` and latest `new_value`;
- never rewrite a ticket that is already running;
- admit no more than four value-trigger workers at a time per workspace; and
- drain value-trigger queues after enqueue, completion, resume, and startup.

This proposal adds no durable worker identity, outbox, dispatch history,
background dispatcher, persistent lease, concurrency setting, or new UI.

---

## Diagnosis

For one accepted Value mutation, the server currently:

1. acquires the workspace write lock;
2. stages the root write;
3. evaluates affected formulas once in dependency order;
4. persists the complete generation and emits one layout update;
5. orders the root event before changed formula results;
6. scans every worker separately for every event;
7. creates one ticket for every worker/event match; and
8. creates one deferred start for every match.

Browser windows do not recalculate formulas or originate the derived events.
Multiple windows therefore do not multiply the work; the server fan-out does.

The current behavior has three defects:

1. **Cross-worker burst.** All distinct matching workers may launch together
   after the write lock is released.
2. **Stale same-worker backlog.** A worker may queue several transitions of the
   same Value and process the oldest one first even though a newer value is
   already known.
3. **Stranded queues.** Completion auto-advances `on_drop` and `on_queue`
   workers, but not `on_value_change` workers.

Cooldown is not a solution. It is optional, defaults to zero, and deliberately
suppresses events by elapsed time. It does not provide latest-value compaction,
bounded starts, or queue progress.

---

## Goals

- Preserve one atomic formula generation per root mutation.
- Preserve root-first, dependency-order trigger metadata.
- Create at most one new dispatch per reacting worker per generation.
- Maintain at most one queued, non-running value-trigger ticket per worker.
- Give a waiting worker the latest qualifying value, not its oldest queued
  transition.
- Preserve the Value's state before the first compacted transition.
- Keep a running ticket immutable and accumulate later changes in one
  successor ticket.
- Limit concurrent value-trigger runs to four per workspace.
- Automatically advance value-trigger queues after all terminal outcomes.
- Resume ordinary persisted queues after restart.

## Non-Goals

- No durable trigger outbox or retained event journal.
- No stable worker or Value identity.
- No user-configurable concurrency or propagation controls.
- No background dispatcher service or dispatcher thread.
- No new execution-lease persistence.
- No cross-generation time-window debounce.
- No general feedback-loop prevention. That should be specified separately if
  required.
- No guarantee against losing a trigger if the server process dies after the
  formula generation is saved but before its ticket is saved.

---

## Functional Proposal

### Lifecycle

For a mutation that permits value-change triggers:

1. Acquire the existing workspace write lock.
2. Validate and stage the root mutation.
3. Calculate and persist the complete formula generation.
4. Produce trigger events in existing order: root first, followed by
   successfully changed formula results.
5. Match those events against current worker configuration.
6. Group matches by reacting worker slot.
7. Create or update each worker's one pending value-trigger ticket and queue
   it through the existing assignment path.
8. Release the write lock.
9. Call the stateless value-trigger queue drain.
10. Start eligible queued workers until four value-trigger workers are active.

Matching, ticket updates, and queue assignment stay within the locked server
mutation. This avoids unresolved dispatch plans and identity machinery. Worker
processes start only after the lock is released.

### Coalescing Within One Generation

One worker receives one ticket from one generation, even when several events
match it. A worker watching `any` receives an ordered collection containing the
root and every matching changed formula result, rather than one ticket for each
event.

Different reacting workers receive their own tickets because they have
independent queues and execution lifecycles.

### Compaction Across Generations

Each worker may have at most one queued, not-yet-running value-trigger ticket.
When a later generation matches the worker:

- create a ticket if none is pending;
- otherwise update the pending ticket in place;
- retain its task ID and queue position; and
- do not append another pending value-trigger ticket.

This is not time-based debounce. Every qualifying trigger is represented in
the pending ticket's counts and latest values.

### Running-Ticket Boundary

Once a worker begins a ticket, that ticket is immutable input for that run.
Later triggers must not change it.

If triggers arrive during the run, create one pending successor or merge them
into the existing successor. A worker therefore has at most:

- one active value-trigger ticket; and
- one pending value-trigger successor.

### First-Old, Last-New Rule

The pending ticket contains one record per matched grid Value. The record key
is the Value's normalized absolute coordinate at the time of the event. This
keeps different cells with duplicate names separate without creating durable
identity. If a Value moves, its old and new coordinates are separate records.

For the first event at a coordinate, store the complete event. For every later
qualifying event at that coordinate:

- retain `old_value`, `old_value_type`, first event ID, and first timestamp;
- replace `new_value`, `new_value_type`, last event ID, last timestamp,
  `changed_by`, name, coordinate, units, and formula metadata;
- increment `occurrence_count`; and
- recompute `changed` by comparing the retained first typed value with the
  latest typed value.

Thus:

```text
10 -> 11 -> 12 -> 15
```

becomes:

```yaml
old_value: 10
new_value: 15
changed: true
occurrence_count: 3
```

If the Value changes away and back:

```text
10 -> 11 -> 10
```

the record has `old_value: 10`, `new_value: 10`, `changed: false`, and
`occurrence_count: 2`. The count records that qualifying writes occurred even
though the net value is unchanged.

### Several Values In One Ticket

A worker watching `any` may accumulate several coordinate records. They retain
the order in which each coordinate first entered the pending ticket.

The ticket identifies the record updated most recently. Backward-compatible
single-event fields are copied from that record, not the first record, so an
older consumer receives the latest triggered Value and its latest value.

### Meaning Of Current Value

In the durable trigger metadata:

- `old_value` is the Value before the first transition compacted into the
  pending ticket;
- `new_value` is the latest qualifying value compacted into the record; and
- `occurrence_count` is the number of qualifying events represented.

Normal Value interpolation still reads the live layout when the worker payload
is assembled. Consequently, the structured record supplies the latest value
that fired the trigger, while ordinary interpolation supplies the live value
if a later write did not qualify because of a condition or cooldown.

### Matching And Cooldown

Every incoming event still uses the existing gates:

- eligible worker type and `activation: on_value_change`;
- scope/name/coordinate match;
- no-op policy;
- optional condition;
- worker and workspace automation pause; and
- cooldown.

Only a qualifying event creates or updates pending work. A rejected event does
not rewrite the ticket. Cooldown is updated after the ticket create/update
succeeds; updating an existing ticket counts as delivered.

### Ticket Shape

Retain the existing synthetic ticket type, priority, and tags. Extend
`value_trigger` with compacted records:

```yaml
value_trigger:
  event_count: 6
  value_count: 2
  coalesced: true
  first_workspace_revision: 39
  workspace_revision: 42
  first_calculation_id: calc_first
  calculation_id: calc_latest
  most_recent_event_key: "coord:C4"

  # Compatibility summary from the most recently updated record.
  event_id: event_latest
  value_name: Counter
  value_coord: C4
  old_value: 10
  new_value: 15
  changed: true

  events:
    - event_key: "coord:C4"
      first_event_id: event_first
      last_event_id: event_latest
      occurrence_count: 4
      value_name: Counter
      value_coord: C4
      old_value: 10
      new_value: 15
      changed: true
    - event_key: "coord:D4"
      first_event_id: event_other
      last_event_id: event_other_latest
      occurrence_count: 2
      value_name: Status
      value_coord: D4
      old_value: pending
      new_value: ready
      changed: true
```

Regenerate the ticket title and body after a merge so they agree with the
structured metadata. Emit `task:created` for creation and `task:updated` for a
merge.

### Fixed Concurrency Limit

Use one server constant:

```python
MAX_CONCURRENT_VALUE_TRIGGER_WORKERS = 4
```

The limit is per workspace and counts workers whose active queue-head ticket is
an `on_value_change` task and whose state is `working` or `retrying`. Queued
tickets do not count. Retries retain their position. Manual and other automatic
activations are outside this limit.

The final `idle -> working` commit checks capacity under the existing write
lock. Competing drain calls therefore cannot commit a fifth start.

### Stateless Queue Drain

Use a function with no retained dispatcher state:

```python
def drain_value_trigger_queues(bp_dir, socketio=None, ws_id=None):
    capacity = 4 - count_active_value_trigger_workers(bp_dir)
    for worker in queued_idle_value_trigger_workers_in_row_major_order(bp_dir):
        if capacity <= 0:
            break
        if try_start_value_trigger_worker(worker):
            capacity -= 1
```

Call it after:

- trigger tickets are created or updated;
- a value-trigger run succeeds, is cancelled, or terminates in failure;
- a worker or workspace automation is resumed; and
- a workspace is loaded at server startup.

Repeated calls are harmless. The worker's atomic start transition remains the
final duplicate-launch guard.

### Queue Progress

Centralize the auto-draining activation predicate and include:

```text
on_drop | on_queue | on_value_change
```

A retry retains the active ticket. Success, cancellation, exhausted retry, and
terminal failure remove or dispose of it according to existing policy, make
the worker idle, and invoke the drain so its successor can run.

### Restart And Crash Behavior

Ordinary tasks and worker queues are already persisted. Startup drain resumes
them up to the fixed limit. No outbox is added.

If the process dies after the generation save but before every trigger ticket
is saved, some triggers may be lost. This narrow window is an accepted
limitation of the existing JSON persistence model. It should be revisited only
if operational evidence warrants a transactional event subsystem.

### Collaboration

All calculation, matching, compaction, queueing, and admission decisions remain
server-owned. Browser refresh, reconnect, or additional windows do not replay
triggers. Volatile activation recalculation continues to suppress triggers.

---

## Technical Proposal

### Batch Matching

Replace per-event `_fire_value_change_triggers` calls with:

```python
def build_value_trigger_dispatches(layout, ordered_events, now):
    """Return {reacting_slot: [matching_events]} in slot order."""
```

Apply the existing gates to every worker/event pair and return one ordered list
for each worker with matches. Do not start workers from this helper.

### Pure Merge Helper

Add:

```python
def merge_value_trigger_events(existing, incoming):
    """Retain first old values and last new values by coordinate key."""
```

The helper initializes or updates first/last IDs, typed values, timestamps,
descriptive metadata, counts, and net `changed`. It also returns the most
recently updated record for compatibility summary generation. Test it without
files, sockets, or worker starts.

### Find And Upsert Pending Ticket

Add helpers conceptually equivalent to:

```python
def find_pending_value_trigger_task(bp_dir, worker): ...

def upsert_pending_value_trigger_task(
    bp_dir, reacting_slot, worker, incoming_events, calculation_meta
): ...
```

Pending lookup rules:

- for `working` or `retrying`, the queue head is active and cannot be updated;
- return the first later queued `on_value_change` ticket;
- for an idle worker, a queued value-trigger ticket remains pending until its
  atomic start succeeds;
- ignore other task kinds; and
- do not bulk-rewrite legacy queues containing several trigger tickets. Merge
  new events into the first eligible pending ticket and let normal queue
  progress drain the legacy remainder.

Upsert creates and assigns a task with automatic start suppressed when none is
pending. Otherwise, it updates the existing task's metadata, title, and body
without changing its ID, assignment, status, or queue position.

Update `last_value_trigger_time` only after upsert succeeds.

### Lock And Post-Lock Drain

Calculation, matching, ticket upsert, and assignment occur under the existing
re-entrant workspace write lock. No worker process or external action occurs
there.

Extend the handler result or lock wrapper so a successful trigger mutation
requests one call to `drain_value_trigger_queues` after the lock is released.
Do not create one deferred thread per match.

### Atomic Admission

For an `on_value_change` queue head, the final run-start commit must:

1. acquire the write lock;
2. confirm the worker is idle and the expected task remains at queue head;
3. count active/retrying value-trigger workers;
4. return `capacity_unavailable` when four are already active; and
5. otherwise perform the existing worker/task start transition.

Capacity exhaustion is not an error and does not mutate the queue. A later
drain retries it.

### Completion Integration

Invoke the drain after every terminal AI, shell, and notification path, not
only normal success. Persist final worker/task state and release the write lock
before draining.

### Persistent State

Only value-trigger ticket metadata changes. The implementation adds no worker
ID, outbox file, dispatch log, lease record, workspace concurrency field,
dispatcher registry, or causal-chain record.

---

## Acceptance Scenarios

1. **One generation:** `A1` changes three formulas. A worker watching `any`
   receives one ticket containing four Value records and starts once.
2. **Six changes before start:** transitions `10 -> 11 -> 12 -> 13 -> 14 -> 15
   -> 16` leave one pending record with `old_value: 10`, `new_value: 16`, and
   `occurrence_count: 6`.
3. **Changes during a run:** an active `10 -> 11` ticket remains unchanged.
   Later `11 -> 12 -> 15` transitions produce one successor with
   `old_value: 11`, `new_value: 15`, and `occurrence_count: 2`.
4. **Away and back:** `off -> on -> off` produces one record with first and
   last value `off`, net `changed: false`, and count 2.
5. **Several Values:** repeated changes to `A1` and `B1` produce one ticket
   with two independently compacted records and a summary of the latest event.
6. **Twenty workers:** all receive pending work, no more than four run, and the
   rest start in row-major order as capacity becomes available.
7. **Busy worker:** it receives one pending successor, which starts after
   success, cancellation, or terminal failure without another Value write.
8. **Retry:** the active retry ticket counts against capacity and remains
   immutable while later events update one successor.
9. **Restart:** persisted queued tickets are discovered by startup drain; no
   more than four start.
10. **Multiple windows:** all windows observe the same tickets and starts; none
    originates additional work.

---

## Test Strategy

Add tests for:

- present duplicate-ticket, unbounded-start, stale-value, and stranded-queue
  behavior before changing it;
- first-old/last-new numeric and string merging;
- away-and-back net comparison and occurrence counts;
- multiple coordinate records and latest-event compatibility summary;
- active-ticket exclusion and one pending successor;
- mixed and legacy queues;
- matching, conditions, no-op, pause, and cooldown suppression;
- concurrent drain calls never exceeding four starts;
- success, retry, exhausted retry, failure, cancellation, pause/resume, and
  startup queue progress;
- AI, shell, and notification execution paths;
- two browser contexts producing no duplicate work; and
- a load case with 100 changed formulas and 50 matching workers, including
  repeated generations while workers wait.

---

## Decisions Embodied

1. One ticket per worker per generation, compacted further into that worker's
   one pending ticket.
2. First typed `old_value`, last typed `new_value`, and an occurrence count for
   each Value coordinate.
3. An immutable active ticket and at most one pending successor.
4. Current worker slots plus the existing write lock instead of stable IDs.
5. Existing tickets and queues instead of an outbox or dispatch history.
6. A fixed concurrency limit of four instead of workspace controls.
7. Stateless drain calls instead of a dispatcher service or leases.
8. Acceptance of the narrow post-generation/pre-ticket crash window.
9. Feedback-loop prevention deferred to separate work.

---

## Tranched Build Plan

Each tranche ends with focused tests, a commit, and a Bullpen ticket status
update.

### Tranche 1 — Queue Progress

- Characterize duplicate, stale, unbounded, and stranded behavior.
- Centralize auto-draining activation rules and include `on_value_change`.
- Add drain hooks for success, retry exhaustion, failure, cancellation,
  pause/resume, and startup.

Checkpoint: commit queue-lifecycle correction and the terminal-path test matrix.

### Tranche 2 — Generation Aggregation

- Collect ordered root and formula events once per generation.
- Match each worker against the batch.
- Create one ticket per worker per generation.
- Add ordered event metadata and latest-event compatibility fields.

Checkpoint: commit aggregation with before/after large-generation ticket counts.

### Tranche 3 — Pending Latest-Value Compaction

- Implement and unit-test the first-old/last-new merge helper.
- Find and update one non-active pending ticket per worker.
- Keep active tickets immutable and maintain one successor.
- Regenerate metadata, title, and body on merge.
- Cover six-change, away-and-back, several-Value, running, and legacy-queue
  cases.

Checkpoint: commit compaction with exact acceptance-scenario payloads.

### Tranche 4 — Fixed-Cap Admission

- Add `MAX_CONCURRENT_VALUE_TRIGGER_WORKERS = 4`.
- Count active runs from current worker and task state.
- Enforce capacity in the atomic start commit.
- Add stateless row-major drain and replace per-match deferred starts.
- Test competing drains and 20/50-worker cases.

Checkpoint: commit bounded admission with measured peak concurrency.

### Tranche 5 — End-To-End Reconciliation

- Run multi-window and AI/shell/notification end-to-end tests.
- Verify startup recovery of ordinary queued tickets.
- Run high-fan-out and repeated-generation load tests.
- Update the formula and value-trigger specifications to reference this
  contract.
- Document the accepted crash window and deferred feedback-loop issue.

Checkpoint: commit the completed remediation and update the implementation
ticket with the tranche/commit/test matrix.
