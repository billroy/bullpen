

---

## Implementation Status

All 14 features and 12 issues (A-L) have been implemented across tranches T1-T11.

| Item | Description | Tranche | Commit |
|------|-------------|---------|--------|
| 1 | Click working task to show detail | T2 | de5dde3 |
| 2 | Left pane roster drop targets | T2 | de5dde3 |
| 3+4 | Agent badge + colored border on roster | T2 | de5dde3 |
| 5 | Suggest unique worker names | T1 | 4e65888 |
| 6 | Fix page title default | T1 | 4e65888 |
| 7 | Light theme with toggle | T4 | bc1b3aa |
| 8 | Worktree separation | T7 | f11bb2b |
| 9 | Auto-commit | T8 | 2e0ea14 |
| 10 | Auto-PR | T9 | 42fc897 |
| 11 | Time-based activation (scheduler + UI) | T10+T11 | 3185daf, 430ab4a |
| 12 | Fix manual activation | T1 | 4e65888 |
| 13 | Replace grid label with workspace path | T3 | 9a01c67 |
| 14 | File editor (edit/save + find/replace) | T5+T6 | 69ef91a, 3692998 |

**Deferred work:**
- Worktree auto-cleanup (UI button or GC pass)
- Configurable timezone for scheduler (currently local time)
- `pr_base_branch` config field for auto-PR

---

## Feature Analysis (reviewed 2026-04-08, comments incorporated)

---

### 1. Clicking on a Working task does not show the task detail

**Finding:** The `worker-queue-item` divs in `WorkerCard.js:27-30` have no `@click` handler -- the items are purely display. Live agent output IS already shown (last 20 lines, `WorkerCard.js:32-34`), but clicking a task in the queue does nothing.

**Action:** Add `@click.stop="$emit('select-task', t.id)"` to each `worker-queue-item`, add `'select-task'` to the emits list, thread the event up through `BullpenTab` (which needs to forward it to the root app's task-selection handler). Three-file change: `WorkerCard.js`, `BullpenTab.js`, `app.js`. Small scope.

---

### 2. LeftPane Workers should be drop targets for task assignment

**Finding:** `LeftPane.js:29-33` renders `.roster-item` elements with no drag event handlers. The inbox already broadcasts `text/plain` task IDs on dragstart (`LeftPane.js:57-60`). WorkerCards also accept `text/plain` drops successfully.

**Action:** Add `@dragover.prevent="onRosterDragOver"` and `@drop="onRosterDrop($event, w.slot)"` to each `.roster-item`, implement handlers that read `text/plain` from the transfer and call `$root.assignTask(taskId, w.slot)`. Two-file change: `LeftPane.js` (handler logic) and `style.css` (hover feedback). Small scope.

---

### 3. LeftPane Workers should show a tiny badge depicting their assigned AI

**Finding:** `LeftPane.js:52` maps worker slots to `{ slot, name, state }` -- `agent` is not included. The roster renders only a status dot and name.

**Action:** Include `agent` in the `workerList` computed property. Add a small colored badge element after the name: `<span class="agent-badge agent-{{ w.agent }}">{{ w.agent }}</span>`. Style with agent colors (claude `#da7756`, codex `#10a37f`) as a pill or colored dot. CSS-only styling work + one line in the computed property. Small scope.

---

### 4. LeftPane Workers should be styled like the Monopoly Card Headers in the Kanban

**Finding:** WorkerCard headers use `:style="{ background: agentColor }"` for a full-bleed colored band. Roster items have only a status dot. A matching treatment in the narrow left pane would mean a colored left border or a compact colored strip on the left edge of each roster row.

**Action:** Add a colored left border (`border-left: 3px solid <agentColor>`) to each `.roster-item` using `:style` bound to the agent color (same formula as `WorkerCard.agentColor`). This requires `agent` from item 3 above. Purely CSS-driven once item 3 lands. Small scope, depends on item 3.

---

### 5. Suggest unique worker display names at creation time

**Finding:** `events.py:on_worker_add` (lines 116-130) sets `"name": profile["name"]` with no uniqueness check. If the same profile is added twice, both workers get identical names.

**Action:** After loading layout, collect all existing worker names. If the candidate name already exists, append ` 2`, ` 3`, etc. until unique. This is a *suggestion* for the initial display name only -- do not enforce uniqueness at load time or overwrite user-assigned names that happen to match. One-function change in `events.py`. Small scope.

---

### 6. Page title is "Bullpen" not "My Bullpen"

**Finding:** `index.html` already has `<title>Bullpen</title>`. However, `init.py:10` sets `DEFAULT_CONFIG["name"] = "My Bullpen"` -- any workspace initialized with the current defaults will show "My Bullpen" in the TopToolbar. Existing workspaces with this default are already written to `config.json` and won't update.

**Action:** Change `DEFAULT_CONFIG["name"]` in `init.py:10` to `"Bullpen"`. Optionally update `app.js` to sync `document.title` to the config name dynamically. One-line fix for new workspaces; existing workspaces need a manual rename or a one-time migration on startup. Small scope.

---

### 7. Add a light theme and a toggle in the header

**Finding:** `style.css:1-23` has all colors as `:root` CSS variables, dark-mode only. No theme toggling exists anywhere. Prism.js uses the `prism-tomorrow` (dark) theme loaded statically.

**Action:**
1. Add a `[data-theme="light"]` block in `style.css` overriding the background, text, and border variables with light values.
2. Add a sun/moon toggle button to `TopToolbar.js`.
3. In `app.js`, store theme preference in `localStorage`, apply `data-theme` to `document.documentElement` on load and on toggle.
4. Prism theme swap is deferred -- accept that code blocks may look slightly off in light mode initially.

Medium scope (mostly CSS authoring).

---

### 8. Worktree separation feature

**Finding:** No worktree support exists. Agent subprocess runs with `cwd=workspace` (`workers.py:94`). No git operations happen before or after agent execution.

**Action:**
- Add `use_worktree: bool` to worker data model and `WorkerConfigModal.js` (checkbox in header area).
- Update `validation.py` to pass through the new boolean field.
- In `workers.py:start_worker`, if `use_worktree` is set: run `git worktree add <temp_path> -b bullpen/<task_id>` before launching the agent, pass the worktree path as `cwd` instead of workspace.
- After agent completion (success or error), leave the worktree in place for the user to inspect/merge.

**Deferred work:** Worktree auto-cleanup (UI button or GC pass) is a future task -- not part of this initial implementation.

**Issues:**
- Must fail gracefully if workspace is not a git repo.
- Worktree path: `.bullpen/worktrees/<task_id>/`. Needs cleanup strategy (deferred).
- Auto-PR (#10) depends on this for clean branch isolation.
- Worktrees block deletion if the branch is checked out elsewhere; `git worktree remove --force` needed on cleanup.

Large scope. Implement without auto-cleanup first.

---

### 9. Auto-commit

**Finding:** `_on_agent_success` in `workers.py:236` handles disposition and queue advancement but runs no git commands.

**Action:**
- Add `auto_commit: bool` to worker data, validation, and a checkbox in `WorkerConfigModal.js`.
- In `_on_agent_success`, if enabled, run `git add -A && git commit -m "bullpen: {task_title} [{task_id}]"` via subprocess in the relevant working directory (workspace or worktree).
- Append commit hash to the task's agent output section.
- Must handle: not a git repo (skip gracefully), nothing to commit (skip silently), commit failure (log as error but don't block disposition).

Medium scope. Does not require worktrees but pairs naturally with item 8.

---

### 10. Auto-PR

**Finding:** No git/GitHub automation exists.

**Action:**
- Add `auto_pr: bool` to worker data, validation, and `WorkerConfigModal.js`. Only enable if `auto_commit` is also enabled (enforce in UI). **Require `use_worktree` when `auto_pr` is enabled** -- filing PRs from the main branch is a bad pattern.
- After the auto-commit succeeds, run `gh pr create --fill` (or with a title derived from the task title).
- Capture the PR URL and append it to the task's agent output.
- Must handle: `gh` not installed, not authenticated, no remote configured -- fail with clear error toast.
- Consider adding a `pr_base_branch` config field.

Medium-large scope. Depends on items 8 and 9 being solid.

---

### 11. Time-based activation

**Finding:** No scheduler exists. Activation is purely event-driven (`on_drop`, `on_queue`). `WorkerConfigModal.js:69-73` shows three options; the backend only supports two.

**Action (phased):**

**Phase 1 -- Scheduler infrastructure (standalone PR):**
- Backend scheduler thread (one per app instance) that wakes every minute, scans workers for time-based activations, calls `start_worker` for eligible idle workers with tasks queued.
- Persistence: if the server restarts, missed triggers should NOT fire retroactively.
- Timezone: run in local time initially; defer configurable timezone to future work.

**Phase 2 -- UI and activation types:**
- Add two new activation types: `at_time` (fire once at a given clock time) and `on_interval` (fire every N minutes/hours).
- New fields on worker: `trigger_time` (HH:MM string), `trigger_interval_minutes` (int), `trigger_every_day` (bool).
- `at_time` with `every_day=false` fires once and resets to idle. With `every_day=true` it fires daily.
- `on_interval` skips silently if no tasks are queued. If tasks are queued, pops and runs the next one on the interval.
- `WorkerConfigModal.js`: conditional fields for time and interval inputs, shown when the matching activation type is selected.

Large scope.

---

### 12. Manual activation is broken / needs play button

**Status: FIXED.** `VALID_ACTIVATIONS` now includes all five activation modes: `{"on_drop", "on_queue", "manual", "at_time", "on_interval"}`.

---

### 13. Replace "Bullpen Grid (4x6)" with bullpen path location

**Finding:** `BullpenTab.js:14` shows `<span>Bullpen Grid ({{ rows }}&times;{{ cols }})</span>`. The workspace path is already displayed in `TopToolbar.js:10`. The grid size selector dropdown already conveys the dimensions, making the label redundant.

**Action:** In `BullpenTab.js`, replace the "Bullpen Grid (NxN)" text with the workspace path (pass `workspace` as a new prop from app.js). In `TopToolbar.js`, remove the `<span class="toolbar-workspace">` from the center. Two-file change. Small scope.

---

### 14. Edit mode for the Files tab

**Finding:** `FilesTab.js` is entirely read-only. Files are fetched via `GET /api/files/<path>` (`app.py:42-74`). There is no write endpoint. The `ensure_within()` path-traversal guard in `persistence.py` is available for reuse.

**Action (phased):**

**Phase 1 -- Basic edit + save:**
1. Backend: Add `PUT /api/files/<path:filepath>` to `app.py`. Read request body as text, call `ensure_within(workspace, filepath)`, then `atomic_write(full_path, content)`. Reject binary files (not valid UTF-8).
2. Frontend: Add an "Edit" toggle button in `FilesTab.js` when a text file is active. In edit mode, replace the preview area with a `<textarea>`. Add Save/Cancel buttons. On save, `PUT` to the API and refresh.

**Phase 2 -- Find/Replace:**
- `Ctrl+F` for Find, `Ctrl+H` / `Cmd+H` for Replace.
- Overlay bar with two inputs (find + replace) and buttons (Replace, Replace All).
- In-memory string replacement before save. No streaming.

**Risks:**
- Binary files must be excluded from edit mode (file-type detection already exists).
- Concurrent edits will silently overwrite. Acceptable for single-user local tool.
- Large files (>1MB) in a textarea are sluggish. Add a size guard.

Medium scope. Implement basic edit+save first, find/replace second.

---

## New Issues to Address Before Implementation

### A. Validation/activation mismatch blocks multiple features

Item 12 reveals that `VALID_ACTIVATIONS` in `validation.py:18` is `{"on_drop", "watch_column"}` which is out of sync with both the UI (`on_drop`, `on_queue`, `manual`) and `workers.py` (`on_drop`, `on_queue`). This blocks items 11 and 12 and likely breaks saving any worker with "On Queue" activation today. **Fix this first as a prerequisite.** APPROVED.

### B. Items 3 + 4 should be a single unit of work

Items 3 (agent badge) and 4 (colored border styling) share the same prerequisite (adding `agent` to `workerList`). Implementing them separately would touch the same lines twice. Combined into one task. APPROVED.

### C. Dependency chain: 8 -> 9 -> 10

Worktree (8), auto-commit (9), and auto-PR (10) form a strict dependency chain. Auto-PR requires `use_worktree` (per your accepted recommendation). The implementation plan should enforce this ordering and not allow 9 or 10 to start until their predecessor is complete and tested.

### D. The `order` field on tasks has no priority awareness server-side

The server-side task list endpoint (`tasks.py:211`) sorts by `order` only, same as the old broken Kanban sort we just fixed client-side. If any future consumer (API client, export, etc.) reads tasks from the server, they'll get wrong ordering. **Server should sort by priority.** APPROVED.

### E. WorkerConfigModal validation gap for new fields

Items 8-10 each add boolean fields (`use_worktree`, `auto_commit`, `auto_pr`) to the worker data model. `validation.py:validate_worker_configure` currently uses an allowlist approach. The implementation plan needs to ensure each new field is added to both the validation allowlist AND the `WorkerConfigModal.js` form, or saves will silently drop the fields.

### F. Prism theme in light mode (item 7) needs a decision

The feature analysis defers the Prism theme swap. If we ship a light theme with dark-only code blocks, it will look broken for the Files tab and any task body with code fences. **Ship with dual Prism themes:** `prism-one-light` for light mode, keep `prism-tomorrow` for dark. Swap stylesheet dynamically on toggle. APPROVED.
