# Implementation Plan — Marker Worker

**Created:** 2026-04-23
**Source:** `marker-worker.md`

---

## Scope guard

This plan stays inside the current Marker worker spec.

In scope:

- new built-in worker type `marker`
- label + note card presentation
- Go to / navigation inclusion
- same trigger/disposition model as ordinary workers
- immediate pass-through routing with no subprocess
- Add Worker library entry and config modal narrowing
- removal of the Eval stub from the Create Worker library

Out of scope for this implementation:

- new loop detection or handoff-depth enforcement
- a marker-only lifecycle or queue model
- rich text, multi-cell spans, overlays, or annotation canvases
- Watch / Stop / Restart for Marker

---

## Ordering rationale

The riskiest part of the feature is not the card chrome; it is the runtime
path for a worker that participates in shared routing without ever entering the
subprocess-backed `working` lifecycle.

So the work should land in this order:

1. Register Marker as a real worker type and make it round-trip cleanly.
2. Add the shared-runtime instant path for Marker.
3. Expose Marker in creation, configuration, and card rendering.
4. Add focused tests around the new type and its no-subprocess behavior.

That sequence keeps the backend contract stable before the UI starts depending
on it.

---

## Implementation shape

### Runtime framing

Marker should be treated as a **no-op worker** whose runtime shape is closest
to a Shell worker, with one crucial difference: it never prepares or launches
an external command.

That means the implementation should borrow the Shell/AI outer flow:

- acquire work through `_begin_run()`
- complete through shared disposition and refill logic
- block deterministically on configuration problems

But Marker should **not** be modeled as "Shell worker with an empty command."

Reasons:

- Shell currently requires a command and treats missing command as a
  misconfiguration.
- Shell carries command/cwd/env/timeout/ticket-delivery semantics that Marker
  does not have.
- Shell commits to the subprocess-backed `working` lifecycle before launching.
- Reusing Shell literally would force special cases into validation, config UI,
  runtime state, and operator-facing copy in the wrong abstraction.

So the implementation target is:

- **same outer lifecycle shape as Shell where useful**
- **separate top-level worker type and dedicated runner**

### Preferred backend shape

Keep `start_worker()` as the single router in `server/workers.py`, and add a
dedicated `_run_marker_worker()` sibling beside `_run_ai_worker()` and
`_run_shell_worker()`.

Marker should reuse:

- `_begin_run()` for task acquisition and synthetic-ticket behavior
- the existing disposition helpers (`_handoff_to_worker`,
  `_pass_to_direction`, `_pass_to_random_worker`)
- the existing watch-column refill checks after completion
- the existing output append/failure helpers where possible

Marker should not reuse `_commit_run_start()`, because that helper is defined
around a subprocess launch and visible `working` transition.

### Preferred instant-worker helper extraction

Add a narrow shared helper for "complete this ticket without spawning a
process", rather than teaching `_on_agent_success()` to special-case Marker in
many places.

Suggested shape:

- `_complete_instant_worker_run(...)` or `_finish_worker_run(...)`
- called by Marker after `_begin_run()`
- handles:
  - optional output append
  - queue pop
  - disposition application
  - failure-to-blocked fallback
  - layout/task/socket emits
  - refill/start-next behavior

`_on_agent_success()` can then either call that helper internally or continue
to own the subprocess-backed path with only small shared extractions.

The important design constraint is: Marker should not fake a subprocess run
just to fit the existing helper boundaries.

---

## Tranche 1 — Type registration and persistence

**Goal:** Make `type: "marker"` a first-class built-in worker type that
round-trips through layout normalization, copy/paste, and config saves.

### T1.1 Register Marker in the worker type registry

- **File:** `server/worker_types.py`
- Add `marker` to `VALID_WORKER_TYPES`
- Add `MarkerWorkerType`
  - `type_id = "marker"`
  - `default_icon()` returns `"square-dot"`
  - `default_color()` returns `"marker"` or another explicit key chosen for the
    new light-card palette
  - `validate_config()` requires a non-empty name and keeps validation narrow
- Add Marker to `WORKER_TYPES`

### T1.2 Normalize Marker slots

- **File:** `server/worker_types.py`
- Extend `normalize_worker_slot()` with a `marker` branch
  - default activation: `on_drop`
  - preserve shared trigger/disposition fields
  - default `note` to `""`
  - default `icon` to `"square-dot"` if unset
  - default `color` to the new marker color key or theme token choice
  - force marker-specific runtime defaults: `task_queue`, `state`, `paused`,
    trigger fields
- Keep `copy_worker_slot()` behavior unchanged except ensuring Marker runtime
  state resets the same way as other workers

### T1.3 Validation updates

- **File:** `server/validation.py`
- Add Marker color support to `VALID_WORKER_COLOR_KEYS`
- Add explicit sanitization for `note`
  - cap length to the modest size already described in the spec
- Leave the existing "unknown/type-specific fields pass through" strategy in
  place so Marker-specific fields keep round-tripping cleanly

### T1.4 Creation defaults in the socket event layer

- **File:** `server/events.py`
- Extend `on_worker_add()` to accept `type == "marker"`
- Add a Marker creation branch with defaults roughly like:
  - `type: "marker"`
  - `name: "Marker"`
  - `note: ""`
  - `activation: "on_drop"`
  - `disposition: "review"` or another agreed default from the spec
  - `icon: "square-dot"`
  - `color: "marker"` or the selected theme token
  - ordinary trigger fields / empty runtime fields
- Reuse the existing unique-name helper so repeated adds become `Marker 2`,
  `Marker 3`, etc.

### T1.5 Persistence and compatibility tests

- **Files:** `tests/test_worker_types.py`, `tests/test_events.py`,
  `tests/test_validation.py`
- Add coverage for:
  - Marker slot normalization
  - Marker note preservation
  - Marker add event succeeds
  - Marker names uniquify on repeated creation
  - Marker copy/reset clears runtime fields but preserves label fields

**Checkpoint:** Marker can be created through the backend and survives
save/load/copy paths before any runtime behavior is added.

---

## Tranche 2 — Shared runtime instant-worker path

**Goal:** Let Marker participate in ordinary worker flow without entering the
subprocess-backed `working` lifecycle.

### T2.1 Route Marker through `start_worker()`

- **File:** `server/workers.py`
- Extend `start_worker()` dispatch:
  - `marker` -> `_run_marker_worker(bp_dir, slot_index, socketio, ws_id)`

### T2.2 Add `_run_marker_worker()`

- **File:** `server/workers.py`
- Reuse `_begin_run()` for:
  - head-ticket resolution
  - empty-queue synthetic ticket creation for `manual`, `at_time`, and
    `on_interval`
  - parity with existing trigger behavior
- Do not call `_commit_run_start()`
- The marker runner should:
  - validate that disposition is actually routable for the current ticket
  - optionally append a brief output/history line if that is part of the shared
    pattern we choose
  - finish immediately through the shared instant-run completion helper

### T2.3 Extract shared completion logic

- **File:** `server/workers.py`
- Extract the disposition/queue-pop/socket/refill portion of
  `_on_agent_success()` into a helper that can be reused by Marker
- Keep subprocess-only responsibilities in `_on_agent_success()`:
  - usage accounting
  - auto-commit / auto-PR
  - worktree cleanup
  - structured output from agent/shell execution
- Keep Marker-specific logic out of AI/Shell/Service paths as much as possible

### T2.4 Marker failure behavior

- **File:** `server/workers.py`
- Introduce a narrow helper for deterministic Marker failures, reusing
  `_append_output()` and/or the existing blocked-task path where practical
- Cases to handle:
  - blank disposition on ticket arrival
  - invalid disposition token
  - `worker:NAME` target not found
  - `pass:DIRECTION` with no adjacent worker
- Result:
  - task moves to `blocked`
  - `assigned_to` clears
  - worker returns to `idle`
  - operator gets the usual toast when the action was user-initiated

### T2.5 Preserve current flow-management behavior

- **File:** `server/workers.py`
- Marker should call the same handoff helpers other workers use
- Do not add new cycle detection or re-enable handoff-depth enforcement here
- Marker-to-marker chains should behave exactly like any other existing
  worker-to-worker chain

### T2.6 Runtime tests

- **Files:** `tests/test_workers.py`, `tests/test_worker_lifecycle.py`,
  `tests/test_scheduler.py`
- Add coverage for:
  - marker disposition to a column
  - marker handoff to named worker
  - marker `pass:right` to adjacent worker
  - blank disposition -> blocked
  - missing target -> blocked
  - manual run on empty queue follows existing synthetic-ticket rules
  - `on_queue` marker claims and immediately forwards
  - scheduled marker triggers do not require subprocess state
  - Marker never enters `_processes` and never emits a persistent `working`
    state

**Checkpoint:** Marker can receive a ticket and route it correctly without
pretending to be subprocess-backed.

---

## Tranche 3 — Create Worker library and utilities

**Goal:** Make Marker available in the Add Worker flow and utility helpers.

### T3.1 Frontend worker utility support

- **File:** `static/utils.js`
- Add Marker to `BUILTIN_WORKER_TYPES`
- Add `isMarkerWorker(worker)`
- Extend `getWorkerTypeIcon()` to return Marker icon fallback
- Extend `workerTypeLabel()` to return `Marker`
- Extend `workerColorKey()` and `DEFAULT_AGENT_COLORS` to support the chosen
  Marker color key

### T3.2 Add Worker library entry

- **File:** `static/components/BullpenTab.js`
- Add a new Marker tab beside AI, Shell, Service
- Remove the disabled Eval tab from the library
- Add a simple Marker library body:
  - blank marker worker
  - optional one-click examples only if they are truly useful; otherwise keep
    first cut to a single blank Marker entry
- Add `addMarkerWorker()` to mirror `addShellWorker()` / `addServiceWorker()`
- After add, open the config modal immediately and focus Name

### T3.3 Creation-flow tests

- **Files:** `tests/test_events.py`, `tests/test_frontend_worker_create_modal.py`,
  `tests/test_frontend_menu_item_icons.py`
- Add checks that:
  - Marker appears in the Create Worker library
  - Eval stub is gone from the library
  - Marker create emits a `worker:add` with `type: "marker"`

**Checkpoint:** Users can create a Marker from the empty-cell flow without
touching the backend directly.

---

## Tranche 4 — Config modal narrowing for Marker

**Goal:** Reuse the normal worker editor shell while trimming it to Marker’s
real fields.

### T4.1 Modal model initialization

- **File:** `static/components/WorkerConfigModal.js`
- Extend the form initializer to include:
  - `note`
  - `icon`
  - `color`
- Add `isMarker` computed
- Ensure activation defaults match Marker semantics

### T4.2 Marker-specific field visibility

- **File:** `static/components/WorkerConfigModal.js`
- Reuse the existing modal shell and shared trigger/disposition controls
- Show for Marker:
  - Name
  - Note
  - Icon
  - Color
  - Input Trigger
  - Watch Column when relevant
  - schedule fields when relevant
  - Output, relabeled to `Pass tickets to`
- Hide for Marker:
  - AI provider/model/prompt/trust controls
  - shell command/cwd/env controls
  - service lifecycle/health controls
  - max retries
  - worktree / auto-commit / auto-pr

### T4.3 Save-path shaping

- **File:** `static/components/WorkerConfigModal.js`
- Update `onSave()` payload shaping so Marker:
  - keeps only shared + marker-specific fields
  - does not inherit AI-only cleanup logic by accident
  - does not emit shell/service-only fields

### T4.4 Modal tests

- **Files:** `tests/test_frontend_worker_create_modal.py`,
  `tests/test_frontend_modal_cmd_enter.py`,
  `tests/test_frontend_modal_escape.py`
- Add checks that:
  - Marker badge/header renders in the modal
  - Marker shows Note/Icon/Color
  - Marker hides command/model/service sections
  - Marker relabels Output as `Pass tickets to`

**Checkpoint:** Marker configuration feels like a native worker editor, not a
generic form with irrelevant fields hanging around.

---

## Tranche 5 — Worker card presentation and controls

**Goal:** Render Marker as a label-first card that still lives inside the
ordinary worker-card family.

### T5.1 Marker card identity

- **Files:** `static/components/WorkerCard.js`, `static/style.css`
- Add Marker-specific rendering hooks:
  - show large name prominently
  - show optional note beneath it
  - use the selected/default Marker icon and color
- Keep the same overall card shell and pass indicators

### T5.2 Menu and action gating

- **File:** `static/components/WorkerCard.js`
- Add `isMarker`
- Menu rules for Marker:
  - show `Edit`, `Run`, `Duplicate`, `Copy Worker`, cross-workspace copy/move,
    `Delete`
  - hide `Watch`, `Stop`, `Restart`
- `Run` should remain available for manual/scheduled start-of-chain use

### T5.3 State/queue presentation

- **Files:** `static/components/WorkerCard.js`, `static/style.css`
- For the common instant pass-through case:
  - no visible long-lived `working` pill
  - no output pane
  - no meaningful steady-state queue rendering required
- Preserve normal queue/task click affordances if a ticket is ever visibly
  present during assignment before routing completes

### T5.4 Card-rendering tests

- **Files:** `tests/test_frontend_worker_card_readouts.py`,
  `tests/test_frontend_worker_focus.py`,
  `tests/test_frontend_worker_pass_tooltip.py`
- Add checks that:
  - Marker uses the ordinary card shell
  - Marker defaults to the expected icon/color
  - Marker menu omits Watch/Stop/Restart
  - Marker card does not expose service/output affordances

**Checkpoint:** Marker reads as a real card in the grid, but visually behaves
like a landmark rather than a runner.

---

## Tranche 6 — Navigation, group ops, and regression sweep

**Goal:** Confirm Marker behaves like a normal occupied cell everywhere else.

### T6.1 Go to / navigation inclusion

- **File:** `static/components/BullpenTab.js`
- Verify Marker naturally appears anywhere worker names are enumerated
- If current worker filters accidentally exclude Marker, widen them without
  introducing type-specific special cases

### T6.2 Group operations and transfer parity

- **Files:** `server/events.py`, `static/components/BullpenTab.js`,
  existing copy/paste helpers if needed
- Verify Marker works with:
  - move
  - duplicate
  - copy/paste
  - copy to workspace
  - move to workspace
  - team save/load and export/import via normalized layout

### T6.3 Regression tests

- **Files:** `tests/test_frontend_bullpen_goto_worker.py`,
  `tests/test_frontend_worker_group_ops.py`,
  `tests/test_export_import_api.py`, `tests/test_transfer.py`
- Add or extend tests so Marker:
  - appears in Go to
  - survives copy/paste and duplicate
  - survives transfer/export/import without losing `note` or type identity

**Checkpoint:** Marker is fully integrated into the worker-grid ecosystem, not
just individually renderable.

---

## Recommended implementation order

If this is executed as one focused feature branch, the safest sequence is:

1. Tranche 1
2. Tranche 2
3. Tranche 3 + Tranche 4 together
4. Tranche 5
5. Tranche 6

The key breakpoint is after Tranche 2. Once the backend instant-worker path is
working and tested, the frontend work becomes much lower risk.

---

## Remaining implementation issues

These are no longer product-definition issues; they are implementation choices
to settle while coding:

1. Whether the shared completion extraction should be a new
   `_complete_instant_worker_run()` helper or a broader refactor of
   `_on_agent_success()`.
2. Whether Marker failures should always append through `## Worker Output` /
   `## Agent Output`, or only fall back there when the existing blocked-task
   helpers already do so cleanly.
3. What exact frontend color key/theme token name to use for Marker so it fits
   the existing provider-color plumbing without overloading an agent color.

None of those should block implementation kickoff.
