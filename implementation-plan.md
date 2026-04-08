# Implementation Plan — Features-1

**Created:** 2026-04-08
**Source:** features-1.md (14 features + 12 issues A-L, all comments incorporated)

---

## Ordering Rationale

Tranches are ordered by: (1) blockers first, (2) dependency chains respected, (3) small isolated fixes grouped together for efficiency, (4) large features last.

The validation/activation fix (Issue A) is a prerequisite for items 11 and 12.
Items 3+4 are combined (Issue B).
Items 8→9→10 are strictly ordered (Issue C).
Server-side priority sort (Issue D) is grouped with other small fixes.
Issue G (worker swap on occupied slots) fits with T2 drag work.
Issue H (order key always "V") fits with T1 task fixes.
Issue I (write lock race) is fixed in T7 when modifying workers.py.
Issue J (FilesTab live reload) is added to T5 with the file editor.
Issue K (dead code) is already in T1.
Issue L (next_worker stub) is cleaned up in T1 with other validation work.

---

## Tranche 1 — Blockers and Small Fixes (~20 min)

**Goal:** Clear all blocking bugs and tiny fixes so subsequent work lands cleanly.

### T1.1 Fix activation validation (Issue A + Item 12)
- **File:** `server/validation.py:18`
- Change `VALID_ACTIVATIONS = {"on_drop", "watch_column"}` to `{"on_drop", "on_queue", "manual"}`
- **File:** `tests/test_events.py` — add test that saving a worker with `activation: "manual"` succeeds
- **File:** `tests/test_events.py` — add test that saving with `activation: "on_queue"` succeeds

### T1.2 Fix server-side priority sort (Issue D)
- **File:** `server/tasks.py` — in `list_tasks()` (~line 211), replace `sort(key=lambda t: t.get("order", ""))` with a two-key sort: priority weight first (urgent=0, high=1, normal=2, low=3), then `order` as tiebreaker
- **File:** `tests/test_tasks.py` — add test that `list_tasks` returns urgent before high before normal

### T1.3 Fix page title default (Item 6)
- **File:** `server/init.py:10` — change `"My Bullpen"` to `"Bullpen"`
- **File:** `static/app.js` — in the `state:init` handler, add `document.title = state.config.name || 'Bullpen'`
- **File:** `.bullpen/config.json` — change `"name": "My Bullpen"` to `"name": "Bullpen"` (fix live workspace)

### T1.4 Suggest unique worker names (Item 5)
- **File:** `server/events.py` — in `on_worker_add`, after loading layout, collect existing names from `layout["slots"]`. If candidate name exists, append ` 2`, ` 3`, etc. until unique. Only affects initial name suggestion; user can rename freely afterward.
- **File:** `tests/test_events.py` — add test: adding same profile twice produces `"Feature Architect"` then `"Feature Architect 2"`

### T1.5 Remove dead code and stubs (Issues K + L)
- **File:** `static/app.js` — remove dead `configureWorker` function (~line 100) that duplicates `saveWorkerConfig`. Verify no references to `configureWorker` exist in any component.
- **File:** `server/validation.py` — remove `"next_worker"` from `VALID_DISPOSITIONS`. It has no UI option, no routing logic in `_on_agent_success`, and would set task status to a non-existent Kanban column. If needed later, re-add with proper design.

### T1.6 Fix order key generation (Issue H)
- **File:** `server/tasks.py` — `generate_order_key()` currently always returns `"V"`. Fix `create_task` to compute a proper fractional key: read existing tasks in the target column, find the last task's order key, and generate a key that sorts after it using the existing `midpoint_key()` infrastructure. This ensures new tasks append to the end of their column in a meaningful order.
- **File:** `tests/test_tasks.py` — add test: creating 3 tasks produces 3 distinct, lexicographically ascending order keys

**Checkpoint:** Run full test suite, commit.

---

## Tranche 2 — Left Pane Enhancements (~20 min)

**Goal:** Items 1, 2, 3+4 — make the left pane worker roster interactive and visually informative.

### T2.1 Click working task to show detail (Item 1)
- **File:** `static/components/WorkerCard.js`
  - Add `'select-task'` to emits list
  - Add `@click.stop="$emit('select-task', t.id)"` to each `.worker-queue-item` div
- **File:** `static/components/BullpenTab.js`
  - Add `@select-task="$emit('select-task', $event)"` on each `<worker-card>` usage
  - Add `'select-task'` to emits list
- **File:** `static/app.js`
  - Wire `@select-task="selectTask"` on `<bullpen-tab>` in the template

### T2.2 Left pane roster drop targets (Item 2)
- **File:** `static/components/LeftPane.js`
  - Add `@dragover.prevent="onRosterDragOver($event, w)"` and `@dragleave="onRosterDragLeave"` and `@drop="onRosterDrop($event, w.slot)"` to each `.roster-item`
  - Add data: `rosterDragSlot: null`
  - Add methods: `onRosterDragOver(e, w)` — set `rosterDragSlot = w.slot`, verify `text/plain` type; `onRosterDragLeave` — clear; `onRosterDrop(e, slot)` — read task ID, call `$root.assignTask(taskId, slot)`, clear
  - Add `:class="{ 'drag-over': rosterDragSlot === w.slot }"` to `.roster-item`
- **File:** `static/style.css` — add `.roster-item.drag-over` style (highlight border or background)

### T2.3 Worker-to-worker swap on occupied slots (Issue G)
- **File:** `static/components/WorkerCard.js`
  - In `onDragOver`, also accept `application/x-worker-slot` type (currently only accepts `text/plain`)
  - In `onDrop`, check for `application/x-worker-slot` data first; if present, call `$root.moveWorker(fromSlot, this.slotIndex)` to swap the two workers. Fall through to existing `text/plain` task-drop logic otherwise.

### T2.4 Agent badge + colored border on roster (Items 3+4 combined, Issue B)
- **File:** `static/components/LeftPane.js`
  - In `workerList` computed, add `agent: s.agent` to the mapped object
  - Add a helper method or inline computed for agent color: `{ claude: '#da7756', codex: '#10a37f' }[w.agent] || '#6B7280'`
  - Add `:style="{ borderLeftColor: agentColor(w.agent) }"` to each `.roster-item`
  - Add `<span class="agent-badge">{{ w.agent }}</span>` after the worker name
- **File:** `static/style.css`
  - `.roster-item` — add `border-left: 3px solid transparent` as base
  - `.agent-badge` — small pill styling (font-size 10px, uppercase, opacity 0.7, padding 1px 5px, border-radius)

**Checkpoint:** Run full test suite, commit.

---

## Tranche 3 — UI Polish: Grid Label + Workspace Path (Item 13) (~15 min)

**Goal:** Replace redundant "Bullpen Grid (NxN)" with workspace path, clean up TopToolbar.

### T3.1 Move workspace path to BullpenTab header
- **File:** `static/app.js` — pass `:workspace="state.workspace"` prop to `<bullpen-tab>`
- **File:** `static/components/BullpenTab.js`
  - Add `'workspace'` to props
  - Replace `Bullpen Grid ({{ rows }}&times;{{ cols }})` with `{{ workspaceShort }}` (last 2 path segments)
  - Add `workspaceShort` computed property

### T3.2 Clean up TopToolbar
- **File:** `static/components/TopToolbar.js` — remove `<span class="toolbar-workspace">{{ workspaceShort }}</span>` and its computed property
- **File:** `static/style.css` — remove `.toolbar-workspace` rules if orphaned

**Checkpoint:** Run full test suite, commit.

---

## Tranche 4 — Light Theme (Item 7 + Issue F) (~20 min)

**Goal:** Full light theme with toggle and dual Prism themes.

### T4.1 CSS light theme variables
- **File:** `static/style.css` — add `[data-theme="light"]` block after `:root` overriding all 17 CSS variables with light equivalents. Suggested palette:
  - `--bg-primary: #ffffff`, `--bg-secondary: #f8f9fa`, `--bg-tertiary: #f0f1f3`, `--bg-input: #ffffff`, `--bg-hover: #e9ecef`
  - `--border: #d1d5db`, `--text-primary: #1a1a2e`, `--text-secondary: #4a5568`, `--text-muted: #9ca3af`
  - `--accent: #5b6abf` (keep similar hue), semantic colors stay the same or slightly muted

### T4.2 Theme toggle in TopToolbar
- **File:** `static/components/TopToolbar.js` — add a sun/moon toggle button in the toolbar-right area. Emits `toggle-theme`.
- **File:** `static/app.js`
  - On mount: read `localStorage.getItem('bullpen-theme')`, apply `data-theme` attribute to `document.documentElement`
  - Add `toggleTheme()` method: flip attribute, save to localStorage, swap Prism stylesheet

### T4.3 Dual Prism themes (Issue F)
- **File:** `static/index.html` — give the Prism CSS `<link>` an `id="prism-theme"` attribute
- **File:** `static/app.js` — in `toggleTheme()`, set `document.getElementById('prism-theme').href` to the light CDN URL (`prism.min.css` or `prism-one-light`) when light, or `prism-tomorrow.min.css` when dark

### T4.4 Visual QA pass
- Check all major views (Kanban, Bullpen, Files, modals) in light mode
- Fix any missed contrast issues or hard-coded colors

**Checkpoint:** Run full test suite, commit.

---

## Tranche 5 — File Editor Phase 1 (Item 14) (~20 min)

**Goal:** Basic edit + save for text files in the Files tab.

### T5.1 Backend write endpoint
- **File:** `server/app.py` — add `PUT /api/files/<path:filepath>` route
  - Call `ensure_within(workspace, filepath)` for path traversal guard
  - Read request body as text; reject if > 1MB
  - Write to file atomically (write to temp, rename)
  - Return 200 on success, 400 on validation error, 403 on path traversal
- **File:** `tests/test_app.py` (or new `tests/test_file_api.py`) — test: PUT valid file, PUT path traversal rejected, PUT binary rejected, PUT >1MB rejected

### T5.2 FilesTab live reload after agent writes (Issue J)
- **File:** `server/workers.py` — in `_on_agent_success`, after disposition change, emit `socketio.emit("files:changed")` to notify clients that workspace files may have changed
- **File:** `static/app.js` — listen for `files:changed` socket event, set a reactive flag `state.filesChanged` (increment a counter or set a timestamp)
- **File:** `static/components/FilesTab.js` — watch the `filesChanged` prop; on change, re-fetch the file tree and reload the active file if one is open. This gives live updates when agents write to the workspace.

### T5.3 Frontend edit mode
- **File:** `static/components/FilesTab.js`
  - Add `editing: false` and `editContent: ''` to component data
  - Add "Edit" button in the file viewer header (visible only for text files, not images/PDFs)
  - When Edit clicked: set `editing = true`, copy `activeFileContent` to `editContent`
  - Render `<textarea v-model="editContent">` in place of the preview when `editing` is true
  - Add Save and Cancel buttons
  - Save: `fetch(PUT /api/files/${path}, { body: editContent })`, on success set `editing = false` and reload file
  - Cancel: set `editing = false`, discard `editContent`
  - Size guard: if file > 1MB, hide Edit button
- **File:** `static/style.css` — `.file-editor-textarea` styling (monospace, full-height, matching background)

**Checkpoint:** Run full test suite, commit.

---

## Tranche 6 — File Editor Phase 2: Find/Replace (Item 14 cont.) (~20 min)

**Goal:** Ctrl+F find and Ctrl+H replace overlay while in edit mode.

### T6.1 Find/Replace overlay
- **File:** `static/components/FilesTab.js`
  - Add data: `showFind: false`, `findText: ''`, `replaceText: ''`, `findCount: 0`, `findIndex: 0`
  - Add keyboard listener on the edit area: `Ctrl+F` → open find bar; `Ctrl+H` / `Cmd+H` → open find+replace bar
  - Find bar: input for search term, match count display, Next/Prev buttons
  - Replace bar (shown on Ctrl+H): second input + Replace / Replace All buttons
  - Replace: `editContent = editContent.replace(findText, replaceText)` (first occurrence)
  - Replace All: `editContent = editContent.replaceAll(findText, replaceText)`
  - Close on Escape
- **File:** `static/style.css` — `.find-replace-bar` overlay styling (position absolute at top of editor, compact inputs)

**Checkpoint:** Run full test suite, commit.

---

## Tranche 7 — Worktree Separation (Item 8) (~20 min)

**Goal:** Workers can optionally run agents in git worktrees for branch isolation.

### T7.1 Data model + validation
- **File:** `server/validation.py` — add `use_worktree` (bool) to `validate_worker_configure` allowlist
- **File:** `static/components/WorkerConfigModal.js` — add checkbox: `<input type="checkbox" v-model="form.use_worktree">` in a new "Git Integration" section below the existing form rows
- **File:** `server/events.py` — in `on_worker_add`, add `"use_worktree": False` to the worker dict default

### T7.2 Fix write lock race condition (Issue I)
- **File:** `server/workers.py`
  - The `_write_lock` is defined in `events.py` and used by socket event handlers, but `_on_agent_success` and `_on_agent_error` run in background threads and do `_load_layout`/`_save_layout` without it.
  - Move `_write_lock` to a shared location (e.g., `server/persistence.py` or a new `server/locks.py`) so both `events.py` and `workers.py` can import and use the same lock.
  - Wrap all `_load_layout`/`_save_layout` sequences in `_on_agent_success`, `_on_agent_error`, and the retry logic with `with _write_lock:`.
  - **File:** `tests/test_workers.py` — verify that the lock is acquired (mock test or integration test with two concurrent completions)

### T7.3 Worktree creation in start_worker
- **File:** `server/workers.py`
  - In `start_worker`, after building prompt and before spawning thread:
    - If `worker.get("use_worktree")` is truthy:
      - Check `git rev-parse --git-dir` in workspace to verify it's a git repo; if not, error with clear message
      - Create worktree dir: `.bullpen/worktrees/<task_id>/`
      - Run `git worktree add <worktree_path> -b bullpen/<task_id>` via subprocess
      - If worktree creation fails, set task to `blocked` with error message, return
      - Pass `worktree_path` as `cwd` to `_run_agent` instead of `workspace`
    - Store `worktree_path` on the task (in body or a metadata field) so user can find it

### T7.4 Tests
- **File:** `tests/test_workers.py` — test: worktree created when `use_worktree=True`, graceful error when not a git repo, worktree path passed as cwd
- **File:** `tests/test_workers.py` — test: write lock is shared between events and worker threads

**Checkpoint:** Run full test suite, commit.

---

## Tranche 8 — Auto-Commit (Item 9) (~20 min)

**Goal:** Workers can auto-commit agent output after successful execution.

### T8.1 Data model + validation
- **File:** `server/validation.py` — add `auto_commit` (bool) to allowlist
- **File:** `static/components/WorkerConfigModal.js` — add checkbox in "Git Integration" section (same row as `use_worktree`)
- **File:** `server/events.py` — add `"auto_commit": False` to worker dict default

### T8.2 Commit logic in _on_agent_success
- **File:** `server/workers.py`
  - New helper: `_auto_commit(cwd, task_title, task_id)` → runs `git add -A && git commit -m "bullpen: {task_title} [{task_id}]"` in the given cwd
  - Returns commit hash on success, None on failure (not a repo, nothing to commit, commit error)
  - In `_on_agent_success`: after appending output but before disposition change, if `worker.get("auto_commit")`, call `_auto_commit`. If it returns a hash, append to task output (`Commit: <hash>`)

### T8.3 Tests
- **File:** `tests/test_workers.py` — test: auto-commit runs when enabled, commit hash appended to output, graceful skip when nothing to commit, graceful skip when not a git repo

**Checkpoint:** Run full test suite, commit.

---

## Tranche 9 — Auto-PR (Item 10) (~20 min)

**Goal:** Workers can auto-file a GitHub PR after auto-commit, requires worktree.

### T9.1 Data model + validation + UI constraints
- **File:** `server/validation.py` — add `auto_pr` (bool) to allowlist
- **File:** `static/components/WorkerConfigModal.js`
  - Add checkbox in "Git Integration" section
  - Disable `auto_pr` checkbox unless both `use_worktree` and `auto_commit` are checked
  - Show helper text: "Requires worktree + auto-commit"
- **File:** `server/events.py` — add `"auto_pr": False` to worker dict default

### T9.2 PR logic in _on_agent_success
- **File:** `server/workers.py`
  - New helper: `_auto_pr(cwd, task_title, task_id, branch_name)` → runs `git push -u origin <branch>` then `gh pr create --title "bullpen: {task_title}" --body "Task: {task_id}"` in the given cwd
  - Returns PR URL on success, error string on failure
  - In `_on_agent_success`: after `_auto_commit` succeeds and returned a hash, if `worker.get("auto_pr")`, call `_auto_pr`. Append PR URL to task output on success; append error and send toast on failure
  - Guard: verify `gh` is available (`shutil.which("gh")`); if not, skip with clear error

### T9.3 Tests
- **File:** `tests/test_workers.py` — test: PR creation attempted when enabled, skipped when `gh` not available, error handling for push failure

**Checkpoint:** Run full test suite, commit.

---

## Tranche 10 — Time-Based Activation Phase 1: Scheduler (Item 11) (~20 min)

**Goal:** Backend scheduler infrastructure that can trigger workers on time-based rules.

### T10.1 Scheduler thread
- **File:** `server/scheduler.py` (new file)
  - `Scheduler` class with `start()`, `stop()`, `_tick()` methods
  - `_tick()` runs every 60 seconds: loads layout, iterates workers, checks activation type and trigger conditions
  - For `at_time`: compare current HH:MM (local) to `trigger_time`; if match and worker is idle with tasks queued, call `start_worker`. If `trigger_every_day` is False, reset activation to `manual` after firing.
  - For `on_interval`: compare elapsed time since `last_trigger_time` to `trigger_interval_minutes`; if exceeded and idle with tasks, fire. Store `last_trigger_time` on the worker in layout.
  - On server start: instantiate and start scheduler. On server stop: stop scheduler thread.
  - Missed triggers (server restart): do NOT fire retroactively. Simply start fresh from current time.

### T10.2 Wire scheduler to app
- **File:** `server/app.py` — import and start scheduler on app init, stop on teardown
- **File:** `tests/test_scheduler.py` (new) — test: tick with `at_time` worker fires at correct time, tick skips idle worker with no tasks, tick does not fire retroactively

**Checkpoint:** Run full test suite, commit.

---

## Tranche 11 — Time-Based Activation Phase 2: UI (Item 11 cont.) (~20 min)

**Goal:** UI controls for time-based activation types.

### T11.1 Validation updates
- **File:** `server/validation.py`
  - Add `"at_time"` and `"on_interval"` to `VALID_ACTIVATIONS`
  - Add `trigger_time` (string, HH:MM format), `trigger_interval_minutes` (int, 1-1440), `trigger_every_day` (bool) to `validate_worker_configure` allowlist
  - Validate `trigger_time` matches `^\d{2}:\d{2}$` pattern

### T11.2 UI controls
- **File:** `static/components/WorkerConfigModal.js`
  - Add `"At Time"` and `"On Interval"` options to the Activation dropdown
  - Add conditional fields:
    - When `at_time`: time input for `trigger_time` (HH:MM), checkbox for `trigger_every_day`
    - When `on_interval`: number input for `trigger_interval_minutes` with label "minutes"
  - Initialize new fields in the `watch: worker` handler with defaults
- **File:** `server/events.py` — add `"trigger_time": None`, `"trigger_interval_minutes": None`, `"trigger_every_day": False`, `"last_trigger_time": None` to worker dict default

### T11.3 Tests
- **File:** `tests/test_events.py` — test: save worker with `at_time` activation and `trigger_time` field succeeds
- **File:** `tests/test_scheduler.py` — test: interval-based activation fires after elapsed time

**Checkpoint:** Run full test suite, commit.

---

## Tranche 12 — Final Polish + Plan Update (~15 min)

**Goal:** Address any remaining issues, clean up, final verification.

### T12.1 Audit all features against requirements
- Verify each of the 14 features works end-to-end
- Run full test suite one final time

### T12.2 Update features-1.md
- Mark each feature as IMPLEMENTED with the commit hash
- Note any deferred work (worktree cleanup, timezone config, etc.)

### T12.3 Update project memory
- Update `project_context.md` to reflect current implementation status

**Checkpoint:** Run full test suite, final commit.

---

## Summary

| Tranche | Features / Issues | Est. Time | Key Files |
|---------|-------------------|-----------|-----------|
| T1 | Issues A, D, H, K, L + Items 5, 6, 12 | 20 min | validation.py, tasks.py, init.py, events.py, app.js |
| T2 | Issues B, G + Items 1, 2, 3+4 | 20 min | WorkerCard.js, BullpenTab.js, LeftPane.js, app.js, style.css |
| T3 | Item 13 | 15 min | BullpenTab.js, TopToolbar.js, app.js, style.css |
| T4 | Item 7 + Issue F | 20 min | style.css, TopToolbar.js, app.js, index.html |
| T5 | Item 14 phase 1 + Issue J | 20 min | app.py, FilesTab.js, workers.py, app.js, style.css, tests |
| T6 | Item 14 phase 2 | 20 min | FilesTab.js, style.css |
| T7 | Item 8 + Issue I | 20 min | validation.py, WorkerConfigModal.js, events.py, workers.py, persistence.py, tests |
| T8 | Item 9 | 20 min | validation.py, WorkerConfigModal.js, events.py, workers.py, tests |
| T9 | Item 10 | 20 min | validation.py, WorkerConfigModal.js, events.py, workers.py, tests |
| T10 | Item 11 phase 1 | 20 min | scheduler.py (new), app.py, tests |
| T11 | Item 11 phase 2 | 20 min | validation.py, WorkerConfigModal.js, events.py, tests |
| T12 | Polish + audit | 15 min | features-1.md, docs |

**Total estimated time: ~4.5 hours (12 tranches)**

All issues A-L are now integrated into the plan. No issues remain deferred.

---

## Issues A-L: Resolution Map

All discovered issues are now integrated into specific tranches.

| Issue | Description | Tranche |
|-------|-------------|---------|
| A | Activation validation mismatch (blocks items 11, 12) | T1.1 |
| B | Items 3+4 combined into one task | T2.4 |
| C | Dependency chain 8→9→10 enforced | T7→T8→T9 |
| D | Server-side priority sort missing | T1.2 |
| E | Validation allowlist for new boolean fields | T7.1, T8.1, T9.1 |
| F | Dual Prism themes for light/dark | T4.3 |
| G | Worker-to-worker drag on occupied slots silent no-op | T2.3 |
| H | All tasks get same order key "V" | T1.6 |
| I | Write lock race in background agent threads | T7.2 |
| J | FilesTab no live reload after agent writes | T5.2 |
| K | Dead `configureWorker` function in app.js | T1.5 |
| L | `next_worker` disposition stub with no implementation | T1.5 |
