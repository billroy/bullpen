# Codex Queue Watch Analysis

Date: 2026-04-08

## Summary

A worker configured with `activation: on_queue` and `watch_column: assigned` does not auto-pick tasks when tasks enter the Assigned column because the watch-column claim path is not implemented on `task:update`.

## Findings

1. `task:update` does not trigger watch-column claim logic.
- `on_task_update` updates task fields and emits `task:updated`, then returns.
- There is no handoff into any watcher/claim evaluator.
- Evidence: `server/events.py` lines 79-86.

2. `watch_column` is configurable but not used by worker runtime.
- UI exposes `on_queue` and `watch_column`.
- Validation accepts and persists `watch_column`.
- Worker runtime does not consult `watch_column` when deciding assignments.
- Evidence: `static/components/WorkerConfigModal.js` lines 95-105, `server/validation.py` line 172, `server/workers.py` lines 79, 543, 659.

3. Kanban status changes are not worker assignment.
- Frontend drag/move emits `task:update { id, status }` only.
- That changes ticket status but does not queue to a worker.
- Evidence: `static/app.js` line 250.

4. Spec/code mismatch is explicit.
- Spec requires event-driven watch claim whenever task enters watched column.
- Code currently does not implement that event path.
- Evidence: `spec.md` lines 391-393 vs `server/events.py` lines 79-86.

## Expected vs Actual

Expected:
- With worker set to `on_queue` watching `assigned`, moving tasks into Assigned should cause idle watcher to claim oldest unassigned matching tasks and start processing.

Actual:
- Tasks enter Assigned and remain unclaimed/unqueued; worker does nothing.

## Likely Root Cause Chain

1. Worker config is saved correctly (`activation=on_queue`, `watch_column=assigned`).
2. Tasks are moved to Assigned via `task:update`.
3. Server emits `task:updated` but never runs watch-column claim evaluation.
4. No call to `assign_task`, queue remains empty, worker does not start.

## Recommended Development Approach

1. Add watch-claim invocation on `task:update` status changes.
- On status transition, evaluate idle `on_queue` workers watching the new column.

2. Add watch-claim invocation on `task:create`.
- If a new task is created directly in a watched column (or future defaults change), it should be eligible immediately.

3. Add on-queue idle refill behavior after completion.
- When an `on_queue` worker returns to idle with empty queue, claim from its watch column if available.

4. Add regression tests.
- Event-level test: `task:update` into watched column causes assignment/queueing.
- Lifecycle test: `on_queue` worker completion followed by next watch-column claim.

## Risk Notes

- Multiple watchers on same column need deterministic arbitration (spec says round-robin by least-recently-active).
- Reassignment rules should preserve canonical task ownership fields (`assigned_to`, `status`) and avoid duplicate queue entries.

