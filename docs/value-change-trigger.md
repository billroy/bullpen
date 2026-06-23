# Value Change Trigger

## Summary

Add a new worker activation mode, **On Value Change**, that starts a runnable
worker whenever any Value worker is written or whenever a Value worker with a
selected name or absolute coordinate reference is written. The run receives a
normal synthetic ticket that records which value was written, where it lives on
the grid, who/what wrote it, whether the normalized value changed, and the
old/new value metadata.

The trigger is intended for workflows where Value workers are live shared state:

- alert when a price, counter, budget, or threshold changes,
- regenerate derived artifacts after a configuration value changes,
- route a review ticket when an agent updates an operational variable,
- fan out notification or shell automation from spreadsheet-like grid cells.

Value workers remain non-runnable data cells. The trigger belongs to the
worker that reacts to the value, not to the Value worker itself.

## Goals

- Add `activation: "on_value_change"` for runnable worker types that process
  tickets or synthetic tickets.
- Let the worker configuration react to any Value worker, to Value workers with
  a selected name, or to one absolute coordinate reference for unnamed Value
  workers.
- Fire from every server-backed value mutation path, including inline UI edits,
  `worker:configure` saves that write a Value worker's value, `value:set`, and
  `value:increment`.
- Create a durable synthetic ticket for each accepted value-write event that
  matches the reacting worker's trigger settings.
- Include old/new value metadata in the ticket body and frontmatter.
- Queue and start the reacting worker through the normal worker lifecycle.
- Respect paused workers and global automation pause.
- Avoid duplicate runs for repeated deliveries and rapid noisy writes.
- Keep browser clients synchronized through normal `task:created`,
  `task:updated`, and `layout:updated` events.

## Non-Goals

- No formula recalculation graph.
- No multi-cell range subscriptions in v1.
- Conditional firing is supported through simple `new_value` predicates; see
  [Conditional Value Triggers](conditional-value-triggers.md). No compound
  expressions, formulas, or multi-field filters in v1.
- No trigger on worker movement, rename, formatting-only edits, or history
  pruning.
- No direct execution by Value workers.
- No cross-workspace value subscriptions.
- No new permission boundary. Any existing actor that can mutate a Value worker
  can cause subscribed automation to fire unless automation is paused.

## Worker Eligibility

The trigger applies to worker types that can run against a ticket or synthetic
ticket:

```text
ai | shell | notification
```

Marker, Value, Eval, unknown, and disabled worker types must not offer this
activation in their configuration UI and must reject it at validation time if
it is supplied.

Service workers are deferred for v1. They can receive ticket-triggered
start/restart orders, but they are not always one-shot ticket processors, so
they should get a separate design pass before joining this trigger.

## Configuration Model

Add the activation value:

```json
{
  "activation": "on_value_change",
  "value_trigger_scope": "name",
  "value_trigger_ref": "Interest rate",
  "value_trigger_fire_on_noop": true,
  "value_trigger_cooldown_seconds": 0
}
```

Fields:

| Field | Type | Default | Notes |
|---|---:|---:|---|
| `activation` | string | existing default | Adds `on_value_change` |
| `value_trigger_scope` | string | `"name"` | `"name"`, `"coord"`, or `"any"` |
| `value_trigger_ref` | string/null | `null` | Name text for `"name"`, absolute cell ref for `"coord"` |
| `value_trigger_fire_on_noop` | boolean | `true` | Fire when an accepted write stores the same normalized value |
| `value_trigger_cooldown_seconds` | integer | `0` | Optional per-worker debounce window, 0-86400 |
| `last_value_trigger_time` | string/null | `null` | Runtime/debug timestamp, server-owned |

`value_trigger_ref` is required when `value_trigger_scope` is `"name"` or
`"coord"` and is ignored when the scope is `"any"`.

Named triggers use loose binding by Value worker name. Bullpen stores the
target name text, not a slot id or cached label. On each accepted value write,
the server compares the changed Value worker's current normalized name against
the configured `value_trigger_ref`. This matches the spirit of worker-to-worker
handoff by name: moving a named Value worker around the grid does not break the
trigger, and deleting/recreating a Value worker with the same name keeps the
automation connected.

Coordinate triggers are for unnamed Value workers and use absolute cell refs.
Bullpen stores the coordinate text, such as `A1`, and resolves it against the
Value worker's current grid coordinate when a value is written. In v1 there is
no drag/move fixup: if a worker is configured for `A1`, it watches whatever
Value worker is at `A1` when a write happens. Moving the original unnamed Value
worker to `B1` does not update the trigger. This is deliberate for the first
cut: unnamed cells "just work" without forcing users to name everything, while
avoiding another hidden cache between the stored data and the UI.

No display label is persisted. The UI should fetch the current matching Value
workers from live layout state whenever it renders the config modal. This
avoids stale label/cache behavior.

Duplicate names are intentionally loose. If a worker subscribes to `Budget`,
then any current Value worker named `Budget` can trigger it. Teams that need a
unique signal should use unique Value worker names.

Nameless Value workers cannot be selected by the `"name"` scope. They can still
trigger workers configured with `"any"` scope or `"coord"` scope. If a user
selects an unnamed Value worker in the picker, Bullpen should save
`value_trigger_scope: "coord"` and its current absolute coordinate.

## UI Behavior

In the worker configuration modal:

- Add **On Value Change** to the Trigger/Activation selector for eligible
  workers.
- When selected, show a scope control: **Any Value** or **Selected Value**.
- For **Selected Value**, show a Value picker listing all current Value
  workers, named and unnamed.
- Each option should show name, coordinate, current value, and unit/format when
  available.
- Unnamed values should be selectable; saving them stores their current
  absolute coordinate.
- If no Value workers exist, show an empty state, disable **Selected Value**, and
  leave **Any Value** available.
- Show a checkbox for **Fire when the value is written even if it did not
  change**. It defaults checked.
- Show a numeric cooldown input only for this activation.
- Hide watched-column, time-of-day, and interval fields.
- Reopen must round-trip the scope, selected ref, no-op checkbox, and cooldown
  exactly. For coordinate refs, display the current Value worker at that
  absolute coordinate when one exists; otherwise show the saved coordinate as
  missing.

The Value picker should prefer a real picker over free text. Free text is still
useful as an advanced escape hatch, but the normal path should prevent typos.
The picker should not attempt to enforce uniqueness.

## Trigger Semantics

A value-write event is eligible when all of the following are true:

1. A Value worker write is accepted by the server.
2. The mutation is accepted by the server and persisted to `layout.json`.
3. At least one eligible worker has `activation: "on_value_change"` and either
   uses `value_trigger_scope: "any"`, targets the changed Value worker's
   current name, or targets the changed Value worker's current coordinate.
4. The reacting worker is not paused and global automation is not paused.
5. The reacting worker is not already in its cooldown window.

No-op writes fire by default. A worker may opt out by setting
`value_trigger_fire_on_noop: false`.

Workers may also add a condition over the event's `new_value`. Supported v1
operators are `any`, `contains`, `<`, `<=`, `==`, `>`, and `>=`. Conditions
filter events after scope/no-op/pause/cooldown checks and before synthetic
tickets are created, so filtered events do not consume cooldown or enqueue work.

Examples:

- writing `"5"` to a numeric value that is already stored as `5` fires when
  `value_trigger_fire_on_noop` is true and does not fire when it is false,
- saving a Value worker's name, icon, color, unit, or formatting without
  writing its value does not fire,
- failed validation, such as writing `"oops"` to a numeric Value worker, does
  not fire,
- a watcher configured with `>= 5` does not fire for a numeric write of `4.9`
  and does fire for `5`,
- a watcher configured with `contains 2026` can fire for string values such as
  `release/2026-06` and numeric values whose canonical text contains `2026`.

`value:increment` should fire once with the pre-increment and post-increment
values.

If one value write matches multiple workers, all matching workers should
receive their own synthetic ticket. Each worker's run follows its own queue,
busy, retry, cooldown, and disposition rules.

If the reacting worker is busy, Bullpen should enqueue the synthetic ticket
rather than dropping the trigger. This follows the queue-preserving direction
already documented for scheduler triggers.

## Synthetic Ticket Contract

Value-write triggers create a normal synthetic ticket through the same server
task creation path used by manual and scheduled empty-queue runs.

Title:

```text
[Auto] {worker_name} - value write {value_name_or_coord} - {timestamp}
```

Type and priority:

```text
type: chore
priority: normal
tags: ["synthetic", "worker-run", "value-change"]
```

Frontmatter:

```yaml
synthetic_run: true
trigger_kind: on_value_change
synthetic_run_key: "{reacting_slot}:on_value_change:{event_id}"
value_trigger:
  event_id: "..."
  scope: "name"
  configured_ref: "Interest rate"
  value_slot: 12
  value_name: "Interest rate"
  value_coord: "A1"
  units: "percent"
  old_value: 5
  old_value_type: "number"
  new_value: 5.25
  new_value_type: "number"
  changed: true
  changed_at: "2026-06-19T14:03:12Z"
  changed_by: "ui | mcp | worker_configure | unknown"
```

Body:

```text
Worker: Rate watcher
Worker type: notification
Trigger kind: on_value_change
Workspace: /path/to/workspace

Value written:
- Name: Interest rate
- Coordinate: A1
- Units: percent
- Old value: 5
- New value: 5.25
- Changed: true
- Changed at: 2026-06-19T14:03:12Z
- Changed by: ui
```

The exact frontmatter shape can be JSON-compatible if Bullpen's task storage
prefers that, but the data should be structured rather than only embedded in
the body. Shell workers using `stdin-json`, Notification templates, and AI
prompts should all be able to inspect the value-change metadata.

## Worker Payloads And Templates

Synthetic tickets generated by this trigger should appear to workers like other
synthetic tickets, with additional `value_trigger` metadata.

Shell `stdin-json` should include:

```json
{
  "trigger_kind": "on_value_change",
  "value_trigger": {
    "scope": "name",
    "configured_ref": "Interest rate",
    "value_name": "Interest rate",
    "value_coord": "A1",
    "old_value": 5,
    "new_value": 5.25,
    "changed": true
  }
}
```

Notification templates should support the same metadata through ticket
placeholders, for example:

```text
{ticket.value_trigger.value_name} changed from {ticket.value_trigger.old_value}
to {ticket.value_trigger.new_value}
```

Existing Value interpolation remains separate. `{A1}` should resolve to the
current value at render time, while `ticket.value_trigger.old_value`,
`ticket.value_trigger.new_value`, and `ticket.value_trigger.changed` describe
the event that caused this run.

## Server Architecture

Implement the trigger as a server-side value mutation observer.

Required canonical path:

1. Resolve the target Value worker before mutation.
2. Capture its old normalized value, type, name, coordinate, units, and slot.
3. Apply and persist the accepted mutation.
4. Compare old and new normalized stored values and record `changed`.
5. Emit the normal `layout:updated` event.
6. Create synthetic tickets for matching value-change workers, honoring each
   worker's `value_trigger_fire_on_noop` setting.
7. Assign those tickets to their workers with `suppress_auto_start` when
   needed, then drain/start through the shared lifecycle.

Do not implement this by diffing arbitrary `layout:updated` payloads on the
frontend. The trigger must fire from UI edits and MCP mutations, and it must
not fire for client-local render state.

The implementation should reuse the existing Value lookup, name normalization,
and coordinate helpers used by MCP, interpolation, and the Go to dialog. It
should not introduce another coordinate parser or a cached target-label system.

### Matching Helper

Add a small server-side matcher that takes the changed Value worker and a
reacting worker config:

```python
def value_trigger_matches(changed_value_slot, changed_value_index, reacting_worker) -> bool:
    ...
```

Rules:

- `value_trigger_scope == "any"` matches every accepted Value worker write.
- `value_trigger_scope == "name"` normalizes `value_trigger_ref` and the
  changed Value worker's current `name` with the existing Value lookup rules.
- `value_trigger_scope == "coord"` parses `value_trigger_ref` with the shared
  cell-ref parser and compares it to the changed Value worker's current
  row/column.
- Invalid or missing refs do not match. They should be visible as config
  warnings but should not throw during unrelated value writes.

### Value Write Event

Represent each accepted Value worker write as a small internal object before
creating tickets:

```python
{
  "event_id": "...",
  "value_slot": 12,
  "value_name": "Interest rate",
  "value_coord": "A1",
  "units": "percent",
  "old_value": 5,
  "old_value_type": "number",
  "new_value": 5.25,
  "new_value_type": "number",
  "changed": True,
  "changed_at": "...",
  "changed_by": "ui",
}
```

The value write object is runtime-only. Persist the resulting synthetic ticket,
not an additional event log, in v1.

### Mutation Hook Points

The observer must be called from all server-backed Value write paths:

- `worker:configure` when the configured worker is `type: "value"` and its
  stored `value` is written,
- `value:set`,
- `value:increment`,
- any future MCP wrapper that ultimately writes a Value worker.

The hook should run after validation and persistence have succeeded. Failed
writes never trigger.

### Synthetic Ticket Creation

Add a helper alongside the existing synthetic-run creation path, for example:

```python
create_value_trigger_task(
    bp_dir,
    reacting_slot,
    reacting_worker,
    value_event,
    trigger_config,
    socketio,
    ws_id,
)
```

This helper should:

- build the title, body, tags, and structured `value_trigger` metadata,
- set `trigger_kind: "on_value_change"`,
- set a best-effort `synthetic_run_key`,
- emit `task:created`,
- assign the task to the reacting worker with the normal assignment path,
- let the shared worker lifecycle decide whether to start immediately or queue.

Do not route around `assign_task`, queue priority, pause checks, or the normal
worker lifecycle.

### Cooldown And Duplicate Guard

Store `last_value_trigger_time` on the reacting worker as runtime state. Since
cooldown is per worker, a broad **Any Value** watcher suppresses all matching
value writes during its cooldown window.

Duplicate protection can be best-effort in v1:

- keep an in-memory set of event/run keys for the current process, or
- check existing live/archived tickets for `synthetic_run_key` before creating
  another one.

This is not a durable event journal. Strong replay handling is deferred.

## Validation And Persistence

Implementation touchpoints:

- Add `on_value_change` to the server activation enum.
- Add validation for `value_trigger_scope`, `value_trigger_ref`,
  `value_trigger_fire_on_noop`, and `value_trigger_cooldown_seconds`.
- Ensure worker type validation rejects this activation for non-runnable types.
- Normalize/copy/export/import/team-save the new config fields.
- Treat `last_value_trigger_time` as server-owned runtime state.
- Preserve unknown future trigger fields for unknown worker types.

The feature should survive:

- browser refresh,
- server restart,
- team save/load,
- worker copy/paste,
- worker transfer,
- bento/package import where worker automations are allowed.

Import safety should follow existing package policy: imported effectful
automation should be visible for review and should not start firing until the
user accepts the imported worker configuration.

## Deduplication, Cooldown, And Ordering

Each accepted value write should get a stable-enough `event_id`, for example:

```text
value:{value_slot}:{updated_at}:{hash(old,new,changed_by)}
```

The `synthetic_run_key` combines the reacting worker slot and event id. V1 does
not need a fully durable replay ledger, but it should avoid creating duplicate
tickets from the same in-process delivery. Before creating a synthetic ticket,
Bullpen may check live and archived tickets for the same key as a best-effort
guard.

Cooldown is a per-worker debounce. During cooldown, Bullpen should update
`last_value_trigger_time` only when it actually creates a ticket. Skipped
events should produce a debug log entry but no user-facing noise unless the
worker config modal is open.

Ordering:

- Multiple value writes are processed in server mutation order.
- Multiple matching workers for one event are processed in slot order.
- A busy reacting worker queues new synthetic tickets behind existing queued
  work.

## Automation Pause

Global automation pause and per-worker pause must suppress value-change
triggers. Suppression means no synthetic ticket is created.

This matches scheduled automation behavior rather than manual worker starts.
When automation resumes, Bullpen should not replay skipped value writes in v1.

## Security And Safety

Writing a Value worker can cause code execution indirectly through Shell,
Notification, or AI workers, and through Service workers if they join this
trigger later. That is already true for scheduled and queue-driven workers, but
this feature creates a new path from data mutation to automation.

Safety requirements:

- The config modal must make the effectful trigger visible.
- Imported workers with this trigger should be reviewed before activation.
- MCP docs should warn that `set_value` and `increment_value` can trigger
  automation, including conditional value-change automation when the predicate
  matches.
- Worker prompts should label value-change ticket content as Bullpen-generated
  metadata plus user/agent-controlled values.
- Shell workers still receive raw text; command authors must quote values when
  interpolating current Value workers into shell commands.

## Testing Plan

Backend tests:

- `worker:configure` accepts `activation: "on_value_change"` with scope
  `"any"` for AI, Shell, and Notification workers.
- `worker:configure` accepts `activation: "on_value_change"` with scope
  `"name"` and a valid nonblank `value_trigger_ref`.
- `worker:configure` accepts `activation: "on_value_change"` with scope
  `"coord"` and a valid absolute cell ref in `value_trigger_ref`.
- Non-runnable worker types reject or disable `on_value_change`.
- Service workers reject or hide `on_value_change` in v1.
- UI `worker:configure` value write fires exactly once.
- `value:set` fires exactly once.
- `value:increment` fires exactly once with correct old/new values.
- No-op writes fire by default.
- No-op writes do not fire when `value_trigger_fire_on_noop` is false.
- Failed numeric validation does not fire.
- Paused worker and global automation pause suppress ticket creation.
- Busy reacting worker queues the synthetic ticket instead of dropping it.
- Multiple reacting workers each receive one synthetic ticket.
- `"any"` scope fires for unnamed and named Value workers.
- `"name"` scope fires for any Value worker currently matching the configured
  name.
- `"coord"` scope fires for the Value worker currently occupying the configured
  absolute coordinate.
- Moving a named Value worker does not break the trigger.
- Moving an unnamed coordinate-watched Value worker intentionally changes what
  the watcher observes; the watcher stays bound to the saved absolute
  coordinate.
- Deleting all Value workers with a configured name leaves the reacting worker
  valid but non-firing until a matching name exists again.
- Duplicate event id does not create duplicate tickets.
- Cooldown suppresses rapid repeated changes.

Frontend/source tests:

- Trigger selector shows **On Value Change** only for eligible worker types.
- Selecting it shows the Any/Selected scope control, Value picker, no-op
  checkbox, and cooldown input.
- Watched-column/time/interval fields are hidden.
- Empty Value picker still allows **Any Value** to be configured.
- Empty Value picker disables **Selected Value** until a Value worker exists.
- Reopen round-trips the scope, selected ref, no-op checkbox, and cooldown.
- Selecting a named Value worker saves scope `"name"` and its name as
  `value_trigger_ref`.
- Selecting an unnamed Value worker saves scope `"coord"` and its current
  coordinate as `value_trigger_ref`.

End-to-end tests:

- Create a named Value worker and Notification worker, configure the
  notification on named value write, edit the value inline, and verify it
  receives a synthetic ticket containing old/new metadata.
- Configure a Notification worker for **Any Value**, edit an unnamed Value
  worker inline, and verify the notification receives a
  synthetic ticket containing old/new metadata.
- Configure a Notification worker for an unnamed selected Value worker, edit
  that value inline, and verify the trigger uses the saved absolute coordinate.
- Configure a Shell worker on value write, call `set_value` through MCP or the
  Socket.IO event, and verify `stdin-json` contains `value_trigger`.
- Verify two connected browser clients see the synthetic ticket and queue
  updates without a refresh.

## Open Issues

1. **Changed-by attribution.** The server currently has mutation source paths
   (`worker:configure`, `value:set`, `value:increment`, MCP wrappers) but may
   not have a durable user/agent identity for every path. V1 should at least
   record the mutation channel.
2. **Import activation safety.** Value-change triggers are effectful
   automation. Bento/team import flows should show and require acceptance for
   this trigger before it can fire.
3. **Trigger loops.** A worker can update the same Value worker that triggered
   it, especially through MCP. This is useful for counters and state machines
   but can create runaway loops. Cooldown helps, but implementation should
   decide whether to add an explicit self-trigger guard or rely on user
   configuration.
4. **No-op default noise.** Firing on no-op writes by default matches the desired
   UI behavior, but it makes broad **Any Value** watchers chatty. The cooldown
   control may be enough; implementation should verify the UI makes this trade
   off obvious.
5. **Duplicate names are intentionally broad.** Loose name binding means every
   Value worker with a matching name can trigger the same watcher. This is
   consistent with avoiding cached identities, but teams that accidentally use
   duplicate names may get more runs than expected.
6. **Absolute coordinate refs can surprise after moves.** Coordinate refs make
   unnamed values work, but in v1 they intentionally watch the coordinate, not
   the original slot. Dragging an unnamed watched value elsewhere changes what
   the watcher observes.

## Deferred

- **Service worker support.** Deferred until Service workers have a separate
  value-trigger design for their long-running/ticket-order semantics.
- **Durable event replay ids.** V1 only needs best-effort in-process duplicate
  protection. A stronger monotonic event log can wait until Bullpen has a
  broader event journal.
- **Coordinate trigger fixups on move.** Future work may rewrite
  `value_trigger_scope: "coord"` refs when a selected unnamed Value worker is
  dragged. V1 does not do this; coordinate refs are absolute.

## Implementation Outline

1. Extend validation, worker normalization, copy/export/import, and frontend
   config fields for `on_value_change`, including scope, ref, no-op behavior,
   and cooldown.
2. Add a shared value-write observer around all accepted Value worker mutation
   paths.
3. Add trigger matching for `"any"`, loose `"name"`, and absolute `"coord"`
   scopes.
4. Add synthetic ticket creation for `trigger_kind: "on_value_change"` with
   structured `value_trigger` metadata.
5. Queue/start reacting workers through the existing lifecycle.
6. Add cooldown and duplicate-key protection.
7. Add backend, frontend, and e2e coverage.

## Task Breakdown

### 1. Shared Trigger Schema

- Add `on_value_change` to `VALID_ACTIVATIONS`.
- Add config validation for:
  - `value_trigger_scope` in `any | name | coord`,
  - `value_trigger_ref` as nonblank text for `name`,
  - `value_trigger_ref` as a valid absolute cell ref for `coord`,
  - `value_trigger_fire_on_noop` as boolean,
  - `value_trigger_cooldown_seconds` as integer `0..86400`.
- Ensure AI, Shell, and Notification workers accept the activation.
- Ensure Service, Marker, Value, Eval, unknown, and disabled workers reject or
  hide the activation.
- Add the new fields to worker normalization, copy/paste, transfer, team
  save/load, and package import/export paths.

### 2. Frontend Configuration

- Add **On Value Change** to eligible worker trigger controls.
- Add **Any Value** and **Selected Value** scope UI.
- Populate the picker with all Value workers.
- Save named selections as `scope: "name"` plus the Value worker name.
- Save unnamed selections as `scope: "coord"` plus the current absolute cell
  ref.
- Reopen and render missing refs:
  - missing name means "waiting for a Value named X",
  - missing coordinate means "no Value at A1".
- Add the no-op checkbox, checked by default.
- Add cooldown input and validation messaging.

### 3. Backend Value Write Observer

- Extract a shared post-write helper for Value worker mutations.
- Capture old/new values and type metadata around `worker:configure`,
  `value:set`, and `value:increment`.
- Compute `changed` after normalization.
- Skip failed writes and non-value-only config saves.
- Respect `value_trigger_fire_on_noop`.
- Respect global automation pause and worker pause before creating tickets.

### 4. Trigger Matching

- Implement matching for `any`, loose `name`, and absolute `coord`.
- Reuse existing name normalization and coordinate parsing/display helpers.
- Treat invalid saved refs as non-matching config warnings.
- Process matching reacting workers in slot order.

### 5. Synthetic Ticket And Queueing

- Create structured value-trigger synthetic tickets.
- Include `scope`, `configured_ref`, actual value name, actual coordinate,
  old/new values, old/new types, `changed`, timestamp, and mutation channel.
- Emit normal task events.
- Assign through the normal server path and let busy workers queue.
- Verify disposition, retry, output capture, and notification template behavior
  remain ordinary worker lifecycle behavior.

### 6. Safety, Import, And Docs

- Add warning text to MCP docs that `set_value` and `increment_value` can fire
  automation.
- Mark value-change trigger fields as effectful during team/Bento import review.
- Add prompt/payload wording that treats values as user/agent-controlled data.

### 7. Tests

- Add backend unit tests for validation, matching, observer hook points,
  cooldown, no-op writes, pause behavior, busy-worker queueing, and synthetic
  ticket metadata.
- Add frontend/source tests for the config modal and picker save behavior.
- Add closed-loop tests for Notification and Shell workers.
- Add at least one two-client sync test for created/queued synthetic tickets.
