# On Drop vs Manual Worker Modes

## Executive readout

`Manual` and `On Drop` were not small variations of the same user idea.
They are different queue policies:

- `On Drop` means "when a ticket is assigned to this worker, start if idle, then
  keep draining queued work."
- `Manual` means "tickets may be assigned and queued here, but do not start or
  drain them unless someone presses Run."
- `Run` with an empty queue is already available outside `Manual`: it creates a
  synthetic ticket and runs it. That makes "Manual" a confusing name for what is
  really "hold queued work until Run."

That mismatch explains the current workspace case. Slot 48, `sleep 2 copy`, is
a manual shell worker with three assigned tickets in its queue. It is idle and
not paused. Nothing is broken at the process layer; it is parked because manual
workers do not auto-start queued work. From the user's point of view, though,
those tickets were received from a neighboring worker, so the worker looks like
it accepted work and then forgot what workers are for.

The most confusing backend behavior has been removed: worker-to-worker handoff
now follows the target worker's activation policy. Auto-start targets start;
manual/held targets queue until Run.

The UI now keeps the persisted activation values for compatibility but labels
them by behavior:

- `on_drop`: `Auto on Assignment`
- `manual`: `Hold for Run`

Idle manual workers with queued tickets now show `WAITING FOR RUN`, and their
menu action reads `Run next (n)`.

## Current behavior

The code treats queue start/drain as activation-specific.

`drain_runnable_queues()` only kicks idle workers whose activation is
`on_drop` or `on_queue`; manual workers with queued work are intentionally
skipped. See `server/workers.py:578`.

`assign_task()` queues the ticket, marks it `assigned`, and starts only when:

- the worker is idle,
- the worker is not blocked or paused,
- and activation is `on_drop` / `on_queue`.

If activation is `manual`, the socket path emits the toast:
`Task queued on {worker}. Use Run to start this manual worker.`

`_begin_run()` creates a synthetic ticket whenever a started worker has an empty
queue. This is the actual "run without needing a ticket" feature, and it is not
unique to manual workers.

On completion, `_on_agent_success()` only starts the next queued ticket when the
worker activation is `on_drop` or `on_queue`. Manual workers process one queued
ticket per explicit Run.

Worker handoffs call the same `assign_task()` path as direct assignment. The
target worker's activation policy decides whether the ticket starts now or waits
in queue.

## Current workspace case

The live layout currently has:

- slot 47: `sleep 2`, shell, `manual`, disposition `pass:right`, queue empty.
- slot 48: `sleep 2 copy`, shell, `manual`, disposition `pass:left`, queue
  length 3.

The queued tickets on slot 48 are:

- `auto-sleep-2-manual-2026-05-27-1725-R4MU`
  - status `assigned`, assigned to slot 48, handoff depth 23, 24 worker-run
    history rows.
- `auto-sleep-2-manual-2026-05-27-1739-IXEq`
  - status `assigned`, assigned to slot 48, handoff depth 1, one worker-run
    history row.
- `auto-sleep-2-manual-2026-05-27-1739-oGMS`
  - status `assigned`, assigned to slot 48, handoff depth 1, one worker-run
    history row.

This was a perfect example of the confusing policy boundary. Slot 47's manual
Run created synthetic tickets, then `pass:right` handed them to slot 48. The
first ticket was able to ping-pong between slot 47 and slot 48 because the
old manual-shell handoff exception started an idle, empty target. Once slot 48
had queued work, later handoffs parked behind it because manual queues do not
auto-drain.

There is also a loop-control smell here. `MAX_HANDOFF_DEPTH` is 10, but
`ENFORCE_HANDOFF_CHAIN_LIMIT` was `False`, so a pass loop could continue well
beyond the nominal depth cap. The first queued ticket reached depth 23. The
depth cap is now enabled by default.

## What is useful

Manual queued execution is useful if the real product meaning is "hold assigned
work until I explicitly run it." That is a legitimate mode for risky deploy
steps, local shell commands, merge workers, or anything that should collect a
ticket but wait for human timing.

The empty-queue synthetic ticket path is very useful. It gives every ad hoc run
an auditable ticket, output, history, status, and disposition. This should stay,
but it should be understood as a `Run` action feature rather than the definition
of the `Manual` activation mode.

Shell pipelines are still useful, but should be modeled explicitly by setting
the downstream shell workers to `Auto on Assignment`. Hidden type-specific
autostart is too surprising to keep.

## What is confusing or dysfunctional

`Manual` is overloaded. It sounds like "I can start this myself," but it also
means "do not start when tickets arrive" and "do not continue to the next queued
ticket." The first meaning is an action. The second and third are queue policy.

`On Drop` is undernamed. It actually means "auto-start on assignment." The
assignment can come from drag/drop, worker pass, CLI/API assignment, or a
synthetic ticket path. Calling it `On Drop` hides the shared assignment model.

Manual workers can still accumulate assigned tickets by design. That is
reasonable for held work, but it needs to stay visible. The worker card now
shows `WAITING FOR RUN` for idle manual workers with queued tickets; the
remaining gap is a server-backed bulk release/reassign action.

Handoff semantics used to vary by target type and queue emptiness. A manual
shell target started on handoff if empty, a manual AI target did not, and a
manual shell target with an existing queue did not. That behavior made pipelines
hard to reason about and has been removed.

The depth limit used to be a paper tiger. The code had a handoff cap, but
enforcement was disabled. A two-worker pass loop could therefore generate many
history entries and then leave tickets parked rather than clearly blocking the
loop. The cap is now enabled.

Manual synthetic tickets can pile up with identical visible titles and even the
same minute-level `synthetic_run_key`. That is not the primary bug, but it makes
the resulting queue harder to inspect after several manual Runs.

## Remediation plan

### 1. Split trigger/action from queue policy

Make `Run` the thing that creates a synthetic ticket when the queue is empty.
That behavior already exists and should be available for auto-start workers too.

Then define the worker's assignment policy separately:

- `auto`: start when assigned and drain queued work while idle.
- `hold`: accept assignments but wait for Run; Run processes either one queued
  ticket or all queued tickets depending on the chosen drain policy.

The UI label change is implemented:

- `On Drop` -> `Auto on Assignment`
- `Manual` -> `Hold for Run`

That alone makes the present behavior much less surprising.

### 2. Decide whether hold mode is one-shot or drain-on-run

Today manual workers are one-shot: each Run processes at most one queued ticket,
and completion does not advance the queue.

If `Manual` is meant to be "start this worker manually, then let it behave like
the same worker," change completion so a manually started queue can drain until
empty. That likely needs a transient run flag such as `manual_drain_active`,
because the persisted activation alone cannot distinguish "idle with held work"
from "currently draining after an explicit Run."

If one-shot is desired, expose it: label the button `Run next` when a queue
exists and show `Waiting for Run` on the worker card.

### 3. Remove the shell-only handoff exception or make it explicit

Implemented product shape: handoff follows the target's assignment policy. Auto
targets start. Hold targets park. If shell pipelines need a convenience later,
make it a visible policy such as `Run handoffs immediately`, or use
`Auto on Assignment`.

### 4. Re-enable or replace handoff loop protection

`ENFORCE_HANDOFF_CHAIN_LIMIT` is now on. A more explicit cycle detector may
still be worth adding later. At minimum, two neighboring workers with reciprocal
`pass:*` dispositions should not generate dozens of runs without a visible stop
condition.

When a loop is detected, block the ticket or move it to a configured failure
column with a clear output note naming the pass chain.

### 5. Add queue visibility and repair paths

For any idle worker with a non-empty queue:

- show why it is idle: `Waiting for Run`, `Paused`, `Automation paused`, or
  `Blocked by config`.
- label Run as `Run next (3)` or `Drain queue (3)` depending on policy.
- provide a safe "release queued tickets" action that unassigns or moves queued
  tickets through the server-backed task API.

Also consider a startup reconciliation warning for impossible-looking state:
idle manual worker, non-empty queue, no visible waiting reason, or a queued task
whose assigned worker no longer exists.

## Recommended direction

Collapse the user's mental model around assignment:

> Workers receive tickets. Some workers start automatically when tickets arrive;
> held workers wait for Run. Run can also create an ad hoc synthetic ticket when
> there is no queued ticket.

That model keeps the useful parts, removes the misleading `Manual` label, and
makes the current three-ticket pileup legible: it is held work, not a worker
that mysteriously failed to notice its queue.
