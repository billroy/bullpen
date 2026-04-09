# Spec Review Comments (codex-3)

## Findings (Ordered by Severity)

### 1) [High] Loading a team / clearing workers can orphan assigned tasks
- **Spec refs:** `spec.md:236-238`, `spec.md:781-783`, `spec.md:604`
- **Issue:** Team load replaces the grid and only defines handling for running tasks (move to Blocked). It does not define what happens to queued/assigned tasks on workers being removed. `Clear All` similarly has no task migration rules.
- **Risk:** Tickets can retain `assigned_to` values pointing to non-existent slots, breaking queue/kanban consistency and creating hidden work.
- **Recommendation:** Reuse the worker-removal rule for bulk operations: before replacing/clearing grid, move all tasks from removed workers to `assigned` and clear `assigned_to` (except explicitly running tasks if you intentionally force them to `blocked`).

### 2) [High] Queue reorder is not restart-durable as currently specified
- **Spec refs:** `spec.md:654`, `spec.md:768`, `spec.md:735`
- **Issue:** UI supports explicit queue reorder (`worker:reorder`) and runtime queue processing uses `task_queue` array order, but startup reconciliation rebuilds queues from ticket `order`.
- **Risk:** Operator queue ordering can silently change after restart unless reorder updates canonical ticket `order` values.
- **Recommendation:** Specify that `worker:reorder` must persist by rewriting each affected ticket’s `order` key (or define a separate canonical queue-order field in ticket frontmatter).

### 3) [Medium] Stop semantics are inconsistent across normal vs bulk operations
- **Spec refs:** `spec.md:376`, `spec.md:781-783`
- **Issue:** Task outcome rules define `Stop` as a pause to `assigned`, but team load says “stop all running agents (tasks go to Blocked).”
- **Risk:** Different code paths for “stop” may produce surprising task outcomes and user confusion.
- **Recommendation:** Distinguish explicit outcome types in spec language, e.g. `operator_stop` -> `assigned`, `forced_abort_for_layout_replace` -> `blocked`.

### 4) [Medium] Worker status vocabulary is internally ambiguous
- **Spec refs:** `spec.md:255-259`, `spec.md:343-366`, `spec.md:631`
- **Issue:** UI says status pill shows “current worker state” including `QUEUED`, while the state machine says workers only have `IDLE` and `WORKING`.
- **Risk:** Event payloads and business logic may treat `QUEUED` inconsistently as either a state or a derived display status.
- **Recommendation:** Declare `QUEUED` as a UI-derived status (not state-machine node) and enumerate allowed `worker:status.status` values explicitly.

### 5) [Medium] Task creation API contract misses a user-visible field
- **Spec refs:** `spec.md:126`, `spec.md:643`
- **Issue:** Task creation modal includes `type`, but `task:create` payload omits it.
- **Risk:** Created tickets may ignore selected type or require an undocumented follow-up update.
- **Recommendation:** Add `type` to `task:create` payload schema (with default `task` server-side).

### 6) [Medium] Event validation is under-specified for fail-closed behavior
- **Spec refs:** `spec.md:813-817`
- **Issue:** Unknown fields are “stripped” rather than rejected, and field-level length/range constraints are not specified (titles, tags, prompt sizes per event field).
- **Risk:** Partial-accept behavior can mask bad/malicious clients and allow oversized values to pressure memory/UI.
- **Recommendation:** Prefer reject-on-unknown for mutating events and define concrete per-field constraints (max lengths, bounded arrays, enum-only values).

### 7) [Low] HTML preview sandbox is broader than necessary for MVP
- **Spec refs:** `spec.md:675`, `spec.md:828`
- **Issue:** Sandbox includes `allow-same-origin`.
- **Risk:** Increases attack surface versus a stricter sandbox, with little MVP benefit for passive preview.
- **Recommendation:** Default to no `allow-same-origin` unless a specific rendering need requires it, then document why.

## Open Questions / Assumptions
1. Assumed “slot ID” in `assigned_to` is stable across layout edits; if slot identity changes on resize/team load, explicit remapping rules are needed.
2. Assumed queue reordering is intended to persist across restarts (because explicit `worker:reorder` exists).

## Summary
The spec is substantially improved and close to implementation-ready. The most important remaining work is to close lifecycle integrity gaps for bulk worker replacement and to make queue ordering canonical/durable. Security posture is good for an MVP local tool, but event validation can be hardened with stricter fail-closed contracts.
