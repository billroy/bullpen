# Implementation Plan — Features-2

**Created:** 2026-04-08
**Source:** features-2.md (9 items, analysis complete)

---

## Feature Analysis

### 1. Model dropdown completeness
- **File:** `static/components/WorkerConfigModal.js:35-42`
- `modelOptions` computed property hardcodes a limited set. The model field is a free-text `<input>` with `<datalist>` suggestions, so users can type any slug — but the suggestions should be comprehensive.
- Update Claude models: add `claude-haiku-4-6`, ensure all current slugs are accurate.
- Update Codex models: add `o3`, `gpt-4.1`.
- The slug is passed directly to `--model` in the CLI adapter, so it must match the API model name exactly.

### 2. Rename "Agent" label to "AI Provider"
- **File:** `static/components/WorkerConfigModal.js:58` — change form label text from "Agent" to "AI Provider"
- The data field stays `agent` internally. The roster badge (`LeftPane.js:38`) and card status line (`WorkerCard.js:24`) display the value (`claude`/`codex`), not the label — no change needed there.

### 3. Clarify trigger time is local
- **File:** `static/components/WorkerConfigModal.js:91` — change label from `Trigger Time (HH:MM)` to `Trigger Time (HH:MM, local)`
- The scheduler (`scheduler.py:47`) uses `datetime.now()` (local time), so the label should reflect this.

### 4. No start button for manual workers with empty queue
- **File:** `static/components/WorkerCard.js:45-46` — `canStart` requires `task_queue.length > 0`
- Manual/self-directed workers whose job is in their expertise prompt have no way to trigger when queue is empty.
- Need to show start button for idle workers even with empty queue.
- On start with empty queue, auto-create an ephemeral task server-side (same pattern as `scheduler.py:_create_auto_task`).
- **File:** `server/workers.py` — `start_worker` currently returns early if queue is empty (line 71-72). Need to handle the auto-task case.

### 5+6. Pause/unpause for scheduled workers
- No pause concept exists. Only way to stop scheduled execution is changing activation to `manual`.
- Add `paused: bool` to worker data model.
- Scheduler (`scheduler.py:_tick`) skips paused workers.
- Worker card header shows pause/unpause toggle for workers with time-based activation.
- Files: `WorkerCard.js`, `server/scheduler.py`, `server/events.py`, `server/validation.py`

### 7. Show worker name on active Kanban cards
- **File:** `static/components/TaskCard.js:10-13` — currently shows priority + type badges only
- Need to show the assigned worker's name on cards that are assigned/in_progress.
- Requires threading `layout` prop through `KanbanTab` → `TaskCard`.
- Look up `task.assigned_to` (slot index) in `layout.slots` to get worker name.

### 8. Move bullpen name + layout selector to tab header
- **File:** `static/components/BullpenTab.js:13-20` — bullpen header with workspace path + grid selector is inside the grid container
- **File:** `static/app.js:178-186` — tab bar is a simple row of buttons
- Move workspace path and grid selector into the tab bar area, visible only when Bullpen tab is active.
- Free up the bullpen pane to be purely the grid.
- Also adjust `static/style.css` for tab bar layout.

### 9. Double-click worker card opens config
- **File:** `static/components/WorkerCard.js:5` — no `@dblclick` handler on `.worker-card` div
- Add `@dblclick="$emit('configure', slotIndex)"` to the div. One line.

---

## Tranches

### Tranche 1 — Small fixes (~15 min)

**Goal:** Quick UI polish items that don't touch backend.

#### T1.1 Update model dropdown slugs
- **File:** `static/components/WorkerConfigModal.js`
- In `modelOptions` computed property (~line 35):
  - Claude: `['claude-sonnet-4-5-20250514', 'claude-sonnet-4-6', 'claude-opus-4-5-20250514', 'claude-opus-4-6', 'claude-haiku-4-5-20250414', 'claude-haiku-4-6']`
  - Codex: `['o3', 'o3-mini', 'o4-mini', 'gpt-4.1', 'codex-1']`

#### T1.2 Rename "Agent" label to "AI Provider"
- **File:** `static/components/WorkerConfigModal.js:58`
- Change label text from `Agent` to `AI Provider`

#### T1.3 Clarify trigger time is local
- **File:** `static/components/WorkerConfigModal.js:91`
- Change label from `Trigger Time (HH:MM)` to `Trigger Time (HH:MM, local)`

#### T1.4 Double-click worker card opens config
- **File:** `static/components/WorkerCard.js:5`
- Add `@dblclick="$emit('configure', slotIndex)"` to the `.worker-card` div

**Checkpoint:** Run full test suite, commit.

---

### Tranche 2 — Kanban worker name + tab bar rearrange (~20 min)

**Goal:** Show who's working on what in Kanban; clean up Bullpen layout.

#### T2.1 Show worker name on active Kanban cards
- **File:** `static/components/TaskCard.js`
  - Add `layout` prop
  - Add computed `assignedWorkerName`: look up `task.assigned_to` in `layout.slots`, return worker name or null
  - Add a small line below badges: `<span v-if="assignedWorkerName" class="task-card-worker">{{ assignedWorkerName }}</span>`
- **File:** `static/components/KanbanTab.js`
  - Add `layout` prop
  - Pass `:layout="layout"` to each `<TaskCard>`
- **File:** `static/app.js`
  - Pass `:layout="state.layout"` to `<KanbanTab>`
- **File:** `static/style.css`
  - `.task-card-worker` styling (small text, muted color)

#### T2.2 Move bullpen name + layout selector to tab header
- **File:** `static/app.js`
  - In the tab bar area, add bullpen-specific controls (workspace path + grid selector) that show only when `activeTab === 'bullpen'`
  - Pass necessary props/data for workspace path and grid resize handler
- **File:** `static/components/BullpenTab.js`
  - Remove the `.bullpen-header` div (workspace path + grid selector)
  - The component becomes just the grid + profile library popup
- **File:** `static/style.css`
  - Adjust `.tab-bar` to accommodate the extra controls
  - May need a `.tab-bar-right` section for the grid selector

**Checkpoint:** Run full test suite, commit.

---

### Tranche 3 — Manual start for empty-queue workers (~15 min)

**Goal:** Self-directed workers can be started manually without pre-queued tasks.

#### T3.1 Extract auto-task creation to shared helper
- **File:** `server/workers.py`
  - Add `create_auto_task(bp_dir, slot_index, worker, socketio=None)` function that creates a `[Auto] WorkerName — timestamp` task with type `chore`, assigns it, and returns the task
  - This is the same logic currently in `scheduler.py:_create_auto_task`
- **File:** `server/scheduler.py`
  - Replace `_create_auto_task` with a call to the shared helper in `workers.py`

#### T3.2 Server: start_worker handles empty queue
- **File:** `server/workers.py`
  - In `start_worker` (~line 70-72), instead of returning early when queue is empty, call `create_auto_task` to create and assign an ephemeral task, then continue with normal execution

#### T3.3 UI: show start button for manual+idle workers
- **File:** `static/components/WorkerCard.js`
  - Change `canStart` computed (~line 45-46):
    - From: `workerState === 'idle' && task_queue.length > 0`
    - To: `workerState === 'idle'` (always show start for idle workers)

#### T3.4 Tests
- **File:** `tests/test_workers.py` — test: starting a worker with empty queue auto-creates a task and executes
- **File:** `tests/test_workers.py` — test: auto-created task has correct title format and type

**Checkpoint:** Run full test suite, commit.

---

### Tranche 4 — Pause/unpause scheduled workers (~15 min)

**Goal:** Prevent scheduled workers from firing without changing their activation type.

#### T4.1 Data model
- **File:** `server/validation.py` — add `paused` (bool) to `validate_worker_configure` allowlist
- **File:** `server/events.py` — add `"paused": False` to worker dict default in `on_worker_add`

#### T4.2 Scheduler respects pause
- **File:** `server/scheduler.py`
  - In `_tick`, after checking `worker.get("state") != "idle"`, add: `if worker.get("paused"): continue`

#### T4.3 UI: pause/unpause buttons
- **File:** `static/components/WorkerCard.js`
  - Add computed `isScheduled`: true when activation is `at_time` or `on_interval`
  - Add computed `isPaused`: `this.worker.paused === true`
  - In the header actions area, show:
    - Pause button (⏸) when `isScheduled && !isPaused`
    - Unpause/resume button (▶) when `isScheduled && isPaused`
  - Pause button calls `$root.configureWorker(slotIndex, { paused: true })`
  - Unpause calls `$root.configureWorker(slotIndex, { paused: false })`
  - Show a visual indicator (e.g., dimmed header or "PAUSED" pill) when paused
- **File:** `static/components/WorkerConfigModal.js`
  - Add `paused` to form data (initialized from worker)
  - Add checkbox in the activation row area: `Paused` (only visible for at_time/on_interval)

#### T4.4 Tests
- **File:** `tests/test_scheduler.py` — test: paused worker is skipped by scheduler tick
- **File:** `tests/test_scheduler.py` — test: unpaused worker fires normally

**Checkpoint:** Run full test suite, commit.

---

## Summary

| Tranche | Features | Est. Time | Key Files |
|---------|----------|-----------|-----------|
| T1 | Items 1, 2, 3, 9 | 15 min | WorkerConfigModal.js, WorkerCard.js |
| T2 | Items 7, 8 | 20 min | TaskCard.js, KanbanTab.js, BullpenTab.js, app.js, style.css |
| T3 | Item 4 | 15 min | workers.py, scheduler.py, WorkerCard.js, tests |
| T4 | Items 5+6 | 15 min | validation.py, events.py, scheduler.py, WorkerCard.js, WorkerConfigModal.js, tests |

**Total estimated time: ~65 min (4 tranches)**

All tranches are independent — can be done in any order.
