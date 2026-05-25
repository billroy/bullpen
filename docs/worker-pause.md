# Worker Pause and Stop The Line

**Status:** Proposed  
**Date:** 2026-05-25  
**Scope:** Complete individual worker pause semantics, add workspace-level
automation pause/resume, and add an emergency Stop The Line action.

---

## Summary

Bullpen already has a `paused` field on workers, but its behavior is incomplete.
It was originally implemented for scheduled workers: paused workers are skipped
by the scheduler, and the UI exposes Pause/Unpause only for `at_time` and
`on_interval` activations. Some other backend paths also respect the field
(`on_queue` watching and queue draining), but direct assignment and direct start
paths can still run paused workers.

This spec defines two related but distinct controls:

- **Individual worker pause:** the worker may hold queued tickets, but it must
  not start new work until unpaused.
- **Pause Automation:** the workspace enters a resumable automation-paused state
  where no ticket-processing worker starts new work. Active runs are allowed to
  finish.
- **Stop The Line:** an emergency action for a shop-floor meltdown. It first
  pauses automation, then aborts active ticket-processing worker runs using
  existing non-failure stop semantics.

The implementation should first make individual worker pause correct, then build
workspace pause and Stop The Line on top of the same execution gates.

---

## Goals

- Provide a header-level Pause/Resume control for worker automation in the
  current workspace.
- Provide a separate emergency Stop The Line control for aborting active
  ticket-processing workers during a broad failure.
- Make `worker.paused` consistent across all start paths.
- Preserve queued work so users can resume without reconstructing assignments.
- Avoid treating operator pause as worker failure.
- Keep resume behavior predictable: automatic workers resume automatically;
  manual workers remain queued until explicitly run.
- Make pause durable across browser reloads and server restarts.
- Avoid hiding work: paused workers should still show queued ticket counts and
  assigned tickets.

## Non-Goals

- True in-process checkpoint/resume for an interrupted AI CLI session.
- Suspending a subprocess without terminating it.
- Pausing individual tickets independently of workers.
- Multi-user permissions or audit trails beyond existing task history/events.
- Changing existing Stop semantics except where Stop The Line intentionally
  invokes them.
- Stopping service workers as part of automation pause by default.

---

## Current State

### Implemented

- Worker records include `paused: false` by default.
- `worker:configure` accepts a `paused` boolean.
- Scheduler skips paused workers.
- `on_queue` watch-column claiming skips paused workers.
- Queue draining skips paused workers.
- Worker cards display a `PAUSED` status label when `worker.paused === true`.
- Worker card menu exposes Pause/Unpause only for `at_time` and `on_interval`
  workers.
- Worker config modal shows a `Paused` checkbox only for `at_time` and
  `on_interval` workers.

### Gaps

- `assign_task()` can still auto-start a paused `on_drop` / `on_queue` worker.
- `start_worker()` can be called directly against a paused worker.
- Shell handoff auto-start can bypass pause through `trigger_handoff_start`.
- Pause UI is hidden for non-scheduled workers even though the field exists.
- There is no workspace automation pause state.
- There is no emergency Stop The Line action.
- There is no central helper that answers "may worker execution start now?"

---

## Functional Spec

### Concepts

**Individual worker pause**

An individual worker is paused when `worker.paused === true`.

A paused worker:

- Can receive tickets in its `task_queue`.
- Keeps its assigned tickets visible.
- Does not start automatically from assignment, handoff, scheduler, watch-column
  claim, or queue drain.
- Does not start from manual Run.
- Can be edited, moved, copied, exported, or deleted using normal worker rules.
- Can be unpaused later.

**Workspace automation pause**

A workspace has paused worker automation when
`config.worker_automation_paused === true`.

When automation is paused:

- No ticket-processing worker in the workspace may start new work.
- Tickets may still be created, edited, moved, assigned, and queued.
- Active worker runs are not stopped by Pause Automation. They may finish
  naturally.
- Scheduled triggers do not fire.
- Watch-column claims do not claim new work.
- Queue drain does not start queued workers.
- Manual Run is disabled.
- Worker-specific pause values are preserved.
- Service workers are not stopped and are not blocked by automation pause by
  default.

Automation pause is independent of individual pause. If automation pause is
disabled, workers that were individually paused remain paused.

**Stop The Line**

Stop The Line is an emergency workspace action. It is not "pause/resume"; it is
"abort active ticket-processing runs and hold the floor."

When Stop The Line is triggered:

- Persist `config.worker_automation_paused = true` first.
- Stop active AI and Shell runs using existing non-failure Stop semantics.
- Do not stop Service workers by default, because a service may be needed to
  recover the workspace or inspect the failure.
- Do not block Service worker Start/Restart by default.
- Do not consume retry budget.
- Do not move tasks to Blocked.
- Leave queued work queued.
- Require an explicit Resume Automation action before auto workers can start
  again.

This is intentionally stronger than Pause Automation. Without setting the
automation pause flag first, aborting active workers would be unsafe because
queued `on_drop` / `on_queue` work could immediately restart.

### Header Controls

Add workspace controls in the app header or top toolbar for the active
workspace.

Primary control: Pause/Resume Automation.

States:

- **Active:** label/action is "Pause automation".
- **Paused:** label/action is "Resume automation".
- **Transitioning:** button is disabled while the server is applying the action.

Secondary emergency control: Stop The Line.

- Always available when automation is active or workers are running.
- Visually distinct from Pause Automation.
- Requires confirmation unless an existing app-level command palette/shortcut
  invokes it with an explicit emergency intent.
- Confirmation copy should say that active AI/Shell runs will be stopped, queued
  work will remain queued, services will keep running, and automation will stay
  paused until resumed.

The UI should make the automation-paused state visible near the header control.
A compact status pill such as `AUTOMATION PAUSED` is enough.

### Pause Automation Action

When the user clicks Pause Automation:

1. Persist `config.worker_automation_paused = true`.
2. Prevent queued or future ticket-processing work from starting while the flag
   is true.
3. Let already-running AI/Shell runs continue.
4. Leave Service workers alone.
5. Emit updated config and any affected UI state.

The action is idempotent. Clicking pause while already paused should be a no-op
success.

### Resume Automation Action

When the user clicks Resume Automation:

1. Persist `config.worker_automation_paused = false`.
2. Re-evaluate runnable queues.
3. Re-evaluate watch columns.
4. Start only workers that would normally auto-start:
   - `on_drop` workers with queued tickets.
   - `on_queue` workers with queued tickets.
   - `on_queue` workers watching columns that currently contain unclaimed
     matching tickets.
5. Do not start `manual` workers merely because they have queued tickets.
6. Do not start individually paused workers.

The action is idempotent. Clicking resume while already active should be a no-op
success.

### Stop The Line Action

When the user confirms Stop The Line:

1. Persist `config.worker_automation_paused = true`.
2. Stop active AI and Shell worker runs using the same semantics as the existing
   Stop action:
   - The active task returns to `assigned` or the existing assigned state.
   - The task remains associated with the worker/queue as appropriate.
   - No retry is consumed.
   - No error output is appended.
3. Do not stop Service workers by default.
4. Emit updated config, layout, and task events as needed.
5. Display a clear status message that automation is paused and must be resumed
   explicitly.

The action is idempotent. Triggering Stop The Line when no workers are active
still pauses automation and succeeds.

### Individual Worker Pause UI

Worker cards should expose Pause/Unpause for all runnable worker types where the
concept makes sense:

- AI: yes.
- Shell: yes.
- Service: yes for explicit per-service pause, but workspace automation pause
  and Stop The Line do not affect services by default.
- Marker: no, because marker workers do not have a long-running execution path.
- Eval/unknown: no.

The worker config modal should expose the same `Paused` checkbox for runnable
worker types, not only scheduled activations.

The existing `PAUSED` status pill should remain. When automation pause is
active, cards may show the workspace-level paused state separately, but
automation pause must not overwrite `worker.paused`.

### Manual Run Behavior

Manual Run on a paused worker must not start a process.

Recommended UI behavior:

- Hide or disable the Run menu item for individually paused workers.
- Hide or disable Run for ticket-processing workers while automation pause is
  active.
- If a stale client sends `worker:start` anyway, the server returns without
  starting and may emit a warning toast.

### Assignment and Queuing Behavior

Assigning or dropping a ticket onto a paused worker should queue it and set the
ticket to `assigned`, but should not start execution.

This applies to:

- Human drag/drop assignment.
- `task:assign`.
- Worker handoff via `worker:NAME`.
- Directional handoff via `pass:DIRECTION`.
- Random worker handoff via `random:`.
- Watch-column claiming, if a paused worker is considered by a claim path.

Paused workers should not be selected for random handoff when an unpaused idle
candidate is available. A paused worker is not idle-available for random handoff.

### Scheduler Behavior

While a worker is individually paused or workspace automation is paused:

- `at_time` does not fire.
- `on_interval` does not fire.
- Scheduler state should not consume a one-shot `at_time` trigger by flipping it
  to manual while paused.
- `last_trigger_time` should not advance merely because the worker was paused.

When resumed:

- `at_time` should wait for the next matching minute unless product explicitly
  chooses catch-up behavior. Recommended: no catch-up.
- `on_interval` should fire after the next full interval from its existing
  schedule anchor. Recommended: do not immediately fire all missed intervals.

### Running Workers

Pause Automation should not stop active AI or Shell workers. Stop The Line
should stop active AI and Shell workers.

Individual worker pause should not automatically stop a currently running worker
unless the user explicitly chooses a "Pause now" action. To keep the first
version simple:

- Setting `worker.paused = true` on an idle worker prevents future starts.
- Setting `worker.paused = true` on a running AI/Shell worker prevents future
  starts after the current run ends, but does not stop the current run.
- Stop The Line stops current AI/Shell runs because the emergency action means
  "stop everything ticket-processing-related now."

If the product wants individual Pause to stop the current run too, add a
separate confirmation or menu label such as "Pause after stopping current run".

### Service Workers

Service worker semantics need an explicit decision because services can be
infrastructure, not ticket-processing automation.

Recommended v1 behavior:

- Pause Automation is automation-only and does not stop Service workers.
- Stop The Line does not stop Service workers by default.
- Service worker Start/Restart remains available while automation is paused.
- If the app later needs a true all-process shutdown, add a separate explicit
  action such as `Stop services too` or `Shutdown workspace processes`.

Rationale: a service worker may be needed to inspect, reproduce, or recover from
the very failure that caused the operator to pause automation.

### Copy, Export, Import, and Team Load

- Copying a worker with `reset_runtime=True` should keep the current behavior of
  clearing `paused` to `false`.
- Export/import should preserve individual `paused` values unless a security
  rule intentionally forces imported executable workers to paused.
- Team load should preserve the team file's worker pause values, but workspace
  automation pause should continue to gate execution after the team is loaded.

---

## Technical Spec

### Data Model

Add a workspace-level flag in `.bullpen/config.json`:

```json
{
  "worker_automation_paused": false
}
```

Rules:

- Missing value means `false`.
- Value is boolean-normalized on config read/update.
- This flag is workspace-scoped, not global across all projects.
- Existing `worker.paused` remains per-worker and is preserved.

### Central Execution Gate

Add shared helpers in `server/workers.py`:

```python
def worker_automation_paused(bp_dir) -> bool:
    """Return true when workspace worker automation is paused."""

def worker_start_blocked(bp_dir, worker, *, manual=False) -> tuple[bool, str | None]:
    """Return whether this worker is blocked from starting and a reason."""
```

`worker_start_blocked` should return blocked when:

- Workspace `worker_automation_paused` is true and the worker is a
  ticket-processing worker.
- Worker has `paused` true.
- Worker is missing, disabled, or not runnable if the caller wants one central
  gate for those cases.

At minimum, every execution path must consult the same pause gate. Avoid
duplicating ad hoc `worker.get("paused")` checks in new code.

### Backend Paths That Must Respect Pause

Update or verify these paths:

- `assign_task()`: queue assignment is allowed, but auto-start is blocked when
  the worker is paused or workspace automation is paused.
- `start_worker()`: direct start returns without launching when pause gate is
  blocked.
- `_begin_run()`: guard here too so type-specific runner entry points cannot
  bypass pause.
- `drain_runnable_queues()`: skip ticket-processing workers when automation
  pause is true; skip individually paused workers.
- `check_watch_columns()`: return early when automation pause is true; skip
  individually paused workers.
- `_refill_from_watch_column()`: return early when automation pause is true or
  the worker is paused.
- `Scheduler._tick()`: return early when automation pause is true; skip
  individually paused workers.
- Worker handoff helpers: do not trigger auto-start when the target is paused or
  automation is paused.
- Random worker handoff: consider only unpaused idle-empty workers as preferred
  idle candidates.
- Service worker start/restart entry points: do not apply the automation pause
  gate by default.

### Socket Events

Add workspace-level events:

- `workers:pause_automation`
- `workers:resume_automation`
- `workers:stop_line`

Alternative acceptable naming:

- `workspace:automation_pause`
- `workspace:automation_resume`
- `workspace:stop_line`

Payload:

```json
{
  "workspaceId": "optional active workspace id"
}
```

Pause Automation response effects:

- Persist config update.
- Emit `config:updated` or existing config event.
- Emit toast/status message on success or error.

Resume Automation response effects:

- Persist config update.
- Emit config update.
- Trigger queue/watch reevaluation outside the write lock.
- Emit layout/task updates from the normal worker start paths.

Stop The Line response effects:

- Persist automation pause config update before stopping any processes.
- Emit config update.
- Emit `layout:updated` if worker runtime state changed.
- Emit `task:updated` for tasks moved by stopping active workers.
- Emit toast/status message on success or error.

### Locking and Race Handling

Stop The Line must set `worker_automation_paused = true` before stopping active
workers. This prevents a race where queued work restarts while active runs are
being stopped.

Pause Automation only needs to persist `worker_automation_paused = true` because
it does not stop active runs.

Resume Automation must set `worker_automation_paused = false` before draining
queues or checking watched columns.

Avoid calling `start_worker()` while holding the write lock. Follow existing
patterns: collect work under lock, then start/drain after the lock is released.

### Active Process Stop Semantics

Stop The Line should reuse existing process stop helpers where possible.

For AI/Shell worker runs:

- Detach or terminate the live subprocess.
- Mark the worker idle.
- Keep or restore the active ticket in a resumable assigned state.
- Do not append error output.
- Do not consume retry budget.
- Emit updates.

If current helpers only stop one slot at a time, implement `stop_line_workers`
as a loop over occupied AI/Shell slots using the existing stop routine.

### Frontend State

Expose `worker_automation_paused` through the existing config object in
`static/app.js`.

Add app-level methods:

```js
function pauseAutomation() {
  socket.emit('workers:pause_automation', _wsData({}));
}

function resumeAutomation() {
  socket.emit('workers:resume_automation', _wsData({}));
}

function stopTheLine() {
  socket.emit('workers:stop_line', _wsData({}));
}
```

Header Pause/Resume derives state from
`state.config.worker_automation_paused === true`.

WorkerCard changes:

- Accept or read workspace automation pause state.
- Disable Run for ticket-processing workers when automation pause is active.
- Continue disabling Run when `worker.paused` is true.
- Show individual Pause/Unpause for runnable worker types.

WorkerConfigModal changes:

- Show `Paused` checkbox for runnable worker types.
- Keep schedule fields separate from pause.

### Accessibility and Copy

Button labels:

- Active state: `Pause automation`
- Paused state: `Resume automation`
- Emergency action: `Stop The Line`

Tooltip/help text:

- Pause: `Prevent new AI and Shell worker runs in this workspace.`
- Resume: `Allow queued and scheduled AI and Shell workers to run again.`
- Stop The Line: `Stop active AI and Shell runs now and pause automation.`

ARIA labels should match visible labels.

Do not rely on color alone. The header should include text such as
`AUTOMATION PAUSED` when automation is paused, and worker cards should show the
existing `PAUSED` pill for individual pause.

---

## Implementation Plan

### Phase 1: Finish Individual Worker Pause

Files:

- `server/workers.py`
- `server/validation.py`
- `static/components/WorkerCard.js`
- `static/components/WorkerConfigModal.js`
- `tests/test_workers.py`
- relevant frontend text tests

Tasks:

1. Add a small `worker_is_paused(worker)` or `worker_start_blocked()` helper.
2. Update `assign_task()` so `should_auto_start` requires the worker not be
   paused.
3. Update `start_worker()` and `_begin_run()` to return early for paused
   workers.
4. Ensure shell handoff auto-start respects pause.
5. Expand WorkerCard Pause/Unpause visibility to all runnable worker types.
6. Expand WorkerConfigModal paused checkbox visibility to all runnable worker
   types.
7. Add tests for:
   - paused `on_drop` assignment queues but does not start.
   - paused `on_queue` assignment queues but does not start.
   - direct `start_worker()` on paused worker does not start.
   - handoff into paused worker queues but does not start.
   - unpausing an auto worker allows queued work to start through normal drain.

### Phase 2: Add Workspace Automation Pause Flag

Files:

- `server/events.py`
- `server/validation.py` or config validation module
- `server/workers.py`
- `server/scheduler.py`
- `static/app.js`
- `static/components/TopToolbar.js` or the current header component
- tests for events/config/frontend

Tasks:

1. Add `worker_automation_paused` config normalization, defaulting to `false`.
2. Add `worker_automation_paused(bp_dir)` helper.
3. Add socket event to pause automation.
4. Add socket event to resume automation.
5. Add pause gate to all backend start paths listed above.
6. Add header Pause/Resume Automation control and state indicator.
7. Add app methods to emit pause/resume automation events.
8. Add tests for:
   - pause automation event persists config.
   - resume automation event persists config.
   - automation pause blocks scheduler.
   - automation pause blocks direct start for AI/Shell.
   - automation pause blocks assignment auto-start.
   - automation pause blocks watch-column claim/drain.
   - automation pause does not stop active AI/Shell runs.
   - automation pause does not stop or block Service workers.
   - resume drains queued `on_drop` / `on_queue` work.
   - resume does not start manual workers.

### Phase 3: Add Stop The Line

Files:

- `server/events.py`
- `server/workers.py`
- `server/service_worker.py` if service workers are included
- `tests/test_workers.py`
- `tests/test_shell_worker.py`
- `tests/test_service_worker.py` if service workers are included

Tasks:

1. Implement `stop_line_workers(bp_dir, socketio, ws_id)` or equivalent.
2. Set automation pause before stopping active runs.
3. Iterate occupied AI/Shell worker slots.
4. Stop active AI/Shell runs using existing stop semantics.
5. Leave Service workers running and startable by default.
6. Emit updates.
7. Add tests for:
   - active AI run is stopped and task is assigned, not blocked.
   - active Shell run is stopped and task is assigned, not blocked.
   - retry counters are not consumed.
   - queued tasks remain queued.
   - automation remains paused after Stop The Line.
   - Service workers are not stopped by Stop The Line.
   - resume after Stop The Line drains queued auto workers but does not start
     manual workers.

### Phase 4: Polish and Documentation

Files:

- `README.md` or user docs as appropriate
- frontend tests
- visual/manual QA checklist

Tasks:

1. Add concise user-facing docs for Pause Automation, Resume Automation, and
   Stop The Line.
2. Verify header layout at desktop and mobile widths.
3. Verify automation paused state survives reload.
4. Verify newly created/imported workers do not auto-run while automation pause
   is active.
5. Verify automation pause, individual pause, and Stop The Line compose
   correctly.

---

## Test Matrix

| Scenario | Expected |
| --- | --- |
| Assign ticket to paused `on_drop` worker | Ticket queues; worker remains idle |
| Assign ticket to paused `on_queue` worker | Ticket queues; worker remains idle |
| Manual Run on paused worker | No process starts; UI blocks or server warns |
| Scheduler tick for paused worker | No trigger; no synthetic ticket |
| Watch column with paused watcher | No claim |
| Handoff to paused worker | Ticket queues on target; no auto-start |
| Random handoff with idle unpaused worker available | Chooses from idle unpaused empty workers |
| Random handoff with only paused/busy workers | Falls back according to existing candidate rules |
| Pause Automation while idle | Config updates; no new AI/Shell work starts |
| Pause Automation while AI worker running | Existing run continues; no new run starts |
| Pause Automation while Shell worker running | Existing run continues; no new run starts |
| Pause Automation while service running | Service keeps running |
| Assign while automation paused | Ticket queues; no auto-start |
| Scheduler while automation paused | No triggers |
| Stop The Line while AI worker running | Process stops; task returns to assigned; no failure |
| Stop The Line while Shell worker running | Process stops; task returns to assigned; no failure |
| Stop The Line while service running | Service keeps running |
| Stop The Line while no workers are active | Automation pause is persisted |
| Resume with queued `on_drop` work | Worker starts normally |
| Resume with queued manual work | Worker remains idle until Run |
| Resume with individually paused queued worker | Worker remains idle |
| Browser reload while automation paused | Header still shows paused; no workers start |

---

## Resolved Decisions

- Workspace pause is automation-only. Service workers may be needed to recover
  from a failure and should keep running by default.
- Stop The Line is the emergency abort control. It pauses automation first, then
  stops active AI/Shell runs.
- Individual worker Pause only prevents the next run. It does not stop an active
  run.
- Stop The Line requires confirmation for mouse/touch activation. A command
  palette action may skip the second prompt if its label is explicit, such as
  `Stop The Line: abort active AI/Shell runs`.
- Resuming after missed `at_time` / `on_interval` triggers does not catch up; it
  waits for the next trigger.
- Workspace export should include `worker_automation_paused`; team export should
  not include it.

---

## Recommended Defaults

- Individual Pause prevents future starts but does not stop a currently running
  worker.
- Pause Automation prevents future AI/Shell starts but does not stop current
  runs.
- Stop The Line pauses automation and stops active AI/Shell runs.
- Pause Automation and Stop The Line do not stop Service workers by default.
- Resume does not catch up missed scheduled triggers.
- Resume drains queued auto workers but does not start manual workers.
