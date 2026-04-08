
# Features-4 Specification

Status: Planning (Features 1-5), Deferred (Features 6-7)

---

## 1. Worker Card Double-Click: Open Task Detail Instead of Config Modal

### Summary
Double-clicking a worker card body should open the task detail panel for the worker's active task (if working) or its first queued task, rather than opening the configuration modal. The configuration modal remains accessible via the `...` menu.

### Current State
The `@dblclick` handler is on the root `.worker-card` element (`WorkerCard.js:11`), which emits `configure`. This means double-clicking anywhere on the card — header or body — opens the config modal. There is no way to quickly jump from a worker card to the task it's working on other than clicking the small queued-task title text.

### Desired Behavior
- **Double-click on card body** (`.worker-card-body`): emits `select-task` with the ID of the currently active task (if `workerState === 'working'`), or the first queued task. If no task is associated, does nothing.
- **Double-click on card header** (`.worker-card-header`): opens the configuration modal (preserves current behavior).
- The `...` menu "Edit" item continues to open the config modal (unchanged).

### Changes Required
- `WorkerCard.js`: Move `@dblclick="$emit('configure', slotIndex)"` from the root `.worker-card` div to the `.worker-card-header` div.
- `WorkerCard.js`: Add `@dblclick.stop="onBodyDblClick"` to `.worker-card-body`.
- Add `onBodyDblClick()` method: determine the relevant task ID (active task if working, else first queued task), emit `select-task` if found.
- The active task ID is available from `worker.current_task` (when working) or `queuedTasks[0]?.id`.

### Edge Cases
- Worker is idle with no queued tasks: double-click body does nothing.
- Worker is working but `current_task` is not in the `tasks` prop: do nothing (task may have been deleted).

### Issues to Resolve Before Planning
- **Confirm `worker.current_task` field**: Verify the server sends a `current_task` field (or equivalent) on worker state that identifies the task currently being executed. If not, the worker state update event may need to include this. Check `workers.py` worker state payload.

---

## 2. Files Tab: Edit Mode Text Disappearing

### Summary
When editing a file in the Files tab, clicking "Edit" causes all but the first line (and sometimes a partial second line) of text to disappear. The textarea appears to render at the wrong height.

### Current State
The file editor uses a `<textarea>` (`FilesTab.js:101`) inside `.file-edit-container` (`style.css:1008-1013`). The container uses `flex: 1; overflow: hidden; display: flex`. The textarea has `width: 100%; height: 100%` (`style.css:1015-1017`).

The parent `.files-viewer-body` (`style.css:866-870`) has `flex: 1; overflow: auto` but does **not** set `display: flex` or `flex-direction: column`. This means the flex `height: 100%` on the textarea resolves against an auto-height parent, collapsing to roughly one line of content.

### Root Cause (Probable)
The `.files-viewer-body` is not a flex container, so `height: 100%` on the textarea doesn't stretch it to fill available space. The content is there (in the `v-model`), but the textarea is visually collapsed. The partial line effect is the textarea's `padding: 12px` plus one line of `line-height: 1.5` at `font-size: 13px`.

### Fix
- `.files-viewer-body` needs `display: flex; flex-direction: column` when in edit mode, or:
- The `.file-edit-container` should use `position: absolute; inset: 0` relative to the viewer body (which already has `position: relative` or can be given it), rather than relying on flex sizing.
- Alternatively, add `min-height: 0` to the flex chain and ensure the viewer body is a flex child with explicit height.

### Verification
After fix, open a file with 50+ lines, click Edit, confirm all lines are visible and the textarea fills the viewer body area. Scroll to bottom of file in edit mode to verify content is intact.

### Issues to Resolve Before Planning
- **Reproduce and confirm**: The root cause above is a strong hypothesis based on the CSS chain, but it should be confirmed by inspecting the computed styles in the browser. The fix depends on whether the issue is height collapse or an overflow clipping problem.

---

## 3. Archive Done Tasks

### Summary
Provide a way to move completed ("done") tasks out of the active kanban board and into an archive subdirectory, reducing UI clutter while preserving history.

### Current State
Done tasks remain in `.bullpen/tasks/` alongside active tasks. They appear in the "Done" kanban column indefinitely. There is no archive mechanism.

### Desired Behavior

**Storage:**
- Archived tasks move from `.bullpen/tasks/{slug}.md` to `.bullpen/tasks/archive/{slug}.md`.
- The archive directory is created on first use.
- Archived tasks retain their original file content and frontmatter unchanged.
- Archived tasks are not loaded into server state on startup (they are excluded from the task scan).

**UI trigger — manual:**
- The "Done" kanban column header gets an "Archive All" button (small, secondary style) that archives all tasks currently in the done column.
- Individual task context menu (if one exists) or the task detail panel gets an "Archive" action for single-task archival.
- Confirmation prompt before bulk archive ("Archive N done tasks?").

**UI trigger — no automatic archival:**
- Automatic/time-based archival adds complexity (what's the threshold? what about tasks still being reviewed?) and is not needed for the initial implementation. The manual trigger addresses the clutter problem directly.

**Restore:**
- No UI for restoring archived tasks in this iteration. Archived files can be moved back manually via the filesystem if needed.
- A future iteration could add an "Archived" pseudo-column or a separate view.

### Server Changes
- New endpoint: `POST /api/tasks/archive` — accepts `{ task_ids: string[] }`. Moves each task file to the archive directory. Removes them from server state. Broadcasts `tasks_updated` event.
- New endpoint: `POST /api/tasks/archive-done` — convenience endpoint that archives all tasks with `status: "done"`.
- Task scan on startup: skip `.bullpen/tasks/archive/` subdirectory.

### Frontend Changes
- `KanbanTab.js`: Add "Archive All" button in the done column header. Button calls the `archive-done` endpoint via socket or REST. Only visible when done column has tasks.
- `TaskDetailPanel.js`: Add "Archive" button (secondary/danger style) visible when task status is "done".

### Issues to Resolve Before Planning
- **Bulk vs. single archive API**: The spec proposes both a bulk endpoint and a convenience "archive all done" endpoint. Confirm this is preferred over a single endpoint that accepts a filter parameter.
- **Task detail panel context**: Does the TaskDetailPanel show task actions (buttons) currently? If not, where should the single-task "Archive" action live — in the kanban card's right-click/context menu, or as a button in the detail panel?

---

## 4. Worker Config Modal: Text Selection Dismisses Modal

### Summary
When editing the Name field in the worker config modal, if you select all text and the mouse cursor drifts outside the modal before releasing, the modal is dismissed. The expected behavior is for the text selection to complete normally.

### Current State
The modal overlay has `@click.self="$emit('close')"` (`WorkerConfigModal.js:55`). The `click.self` modifier means only clicks directly on the overlay (not on children) trigger close. However, a click-and-drag that starts inside the modal but ends on the overlay fires a `click` event on the overlay — and since the `event.target` is the overlay, `.self` passes and the modal closes.

### Root Cause
This is a well-known issue with overlay-click-to-dismiss. The `mousedown` starts on an input inside the modal, but `mouseup` occurs on the overlay. The browser synthesizes a `click` event on the overlay, which passes the `.self` check.

### Fix
Replace `@click.self="$emit('close')"` with a two-phase check:
1. On `@mousedown.self`, set a flag (`overlayMouseDown = true`).
2. On `@click.self`, only emit `close` if `overlayMouseDown` is true. Reset the flag.
3. On `@mouseup` (anywhere), reset the flag if the target is not the overlay.

This ensures the modal only closes when both mousedown and click originate on the overlay, not when a drag operation from inside the modal ends on the overlay.

### Changes Required
- `WorkerConfigModal.js`: Add `overlayMouseDown: false` to `data()`.
- Replace `@click.self="$emit('close')"` with `@mousedown.self="overlayMouseDown = true" @click.self="onOverlayClick"`.
- Add method `onOverlayClick()`: if `overlayMouseDown`, emit `close`. Always reset `overlayMouseDown = false`.
- Add `@mouseup="overlayMouseDown = false"` on the modal content div (`.modal.modal-wide`) to catch mouseup events that land back inside.

### Issues to Resolve Before Planning
- None. The fix pattern is well-established and self-contained to `WorkerConfigModal.js`.

---

## 5. Worker Config Modal Height: Save Button Below Fold

### Summary
The worker config modal requires scrolling to reach the Save button, which makes it non-obvious. The modal should be tall enough to show all fields and the footer without scrolling at typical viewport heights.

### Current State
The modal uses `max-height: 85vh` (`style.css:1103`) with `overflow-y: auto`. The modal content includes: header, 7 form fields (name, provider/model row, activation row, disposition/retries row, checkboxes row, expertise prompt textarea with `rows="8"`), and footer. The expertise prompt textarea at 8 rows is the largest single element.

### Fix Options

**Option A — Reduce expertise prompt rows:**
Change `rows="8"` to `rows="4"` in `WorkerConfigModal.js:155`. The textarea will still be scrollable for long prompts, but the modal fits on screen. This is the simplest fix.

**Option B — Sticky footer:**
Make `.modal-footer` sticky at the bottom of the modal so it's always visible regardless of scroll position. Add `position: sticky; bottom: 0; background: var(--bg-secondary);` to `.modal-footer` in `style.css`.

**Option C — Increase max-height:**
Change `max-height: 85vh` to `90vh`. This may not fully solve the problem on smaller screens.

### Recommendation
**Option B (sticky footer)** is the most robust: it works regardless of content length and benefits any future modal that grows in content. It can be combined with Option A for an even better fit.

### Issues to Resolve Before Planning
- **Viewport assumptions**: What is the minimum expected viewport height? If this is a desktop-only tool, 85vh at 1080p gives ~918px which should be sufficient. The issue may only manifest at smaller window sizes or higher DPI. Clarify target viewport.

---

## 6. Worker Disposition: Hand Off to Another Worker's Queue

> **Status**: Spec complete — see `docs/worker-handoff.md`. Ready for implementation planning. Stable IDs replaced with weak name binding; circular detection via runtime depth counter.

### Summary
Extend the Disposition field in the worker config modal to support routing completed tasks to another worker's queue, in addition to kanban columns.

### Current State
Disposition is a simple dropdown with two options: "Review" and "Done" (`WorkerConfigModal.js:119-125`). These map to kanban column keys. When a worker finishes a task, the task's status is set to the disposition value.

### Desired Behavior
After a worker completes a task, it can:
1. Move the task to a kanban column (current behavior), OR
2. Assign the task to another worker's queue (new behavior).

This enables worker pipelines: Worker A does initial analysis, then hands off to Worker B for implementation, then Worker B hands off to the "review" column for human review.

### Proposed UI: Single Picker with Grouped Options

Use a single `<select>` dropdown with `<optgroup>` sections:

```
Disposition
├─ Columns
│  ├─ Review
│  ├─ Done
│  ├─ (other kanban columns...)
├─ Workers
│  ├─ Worker A
│  ├─ Worker B
│  ├─ (other workers, excluding self...)
```

**Rationale:** A single dropdown is simpler than a two-step "type picker + target picker" approach. The `<optgroup>` labels make the two categories visually distinct. The list is short enough (typically <10 items) that a flat dropdown works well.

**Value encoding:**
- Column targets: `column:<key>` (e.g., `column:review`, `column:done`)
- Worker targets: `worker:<slot_index>` (e.g., `worker:3`)
- For backward compatibility, bare values like `"review"` and `"done"` are treated as `column:review` and `column:done` during migration.

### Server Changes
- `workers.py`: When a worker finishes a task, parse the disposition value. If it starts with `worker:`, assign the task to that worker's queue (set `assigned_to` and trigger the target worker's activation if applicable). If it starts with `column:` (or is a bare column key), set the task status to that column.
- Handle the case where the target worker has been deleted: fall back to the "review" column and log a warning.

### Frontend Changes
- `WorkerConfigModal.js`: Replace the disposition `<select>` with a grouped dropdown. Needs access to the worker list (new prop or inject from parent).
- The current `form.disposition` value changes from a bare column key to the `type:target` format. Existing saved values ("review", "done") are migrated on load.
- Exclude the current worker from the workers list in the dropdown (can't hand off to self).

### Issues to Resolve Before Planning
- **Worker identification stability**: Using `slot_index` as the worker identifier in the disposition value is fragile — slot indices change if the grid is resized or workers are reordered. Consider using the worker name or a stable worker ID instead. If workers don't have stable IDs, this needs to be added first.
- **Circular handoff detection**: Worker A → Worker B → Worker A creates an infinite loop. Should the system detect and prevent this at configuration time, or at runtime (with a max-depth limit)?
- **Props for worker list**: The `WorkerConfigModal` currently receives `columns` but not the worker list. The parent (`app.js`) needs to pass the full worker list (or at minimum names and identifiers) as a new prop.

---

## 7. Terminal Tab [DEFERRED]

> **Deferred**: Needs a prototype spike to validate eventlet + PTY compatibility and xterm.js CDN/ESM strategy before planning.

### Summary
Add a Terminal tab to the Bullpen UI that provides one or more web-based terminal sessions connected to the project directory.

### Current State
No terminal integration exists. The app uses Vue 3 (CDN, no build step), Flask + Flask-SocketIO (eventlet) on the backend. All frontend libraries are loaded via CDN.

### Desired Behavior
- A new "Terminal" tab appears alongside Kanban, Bullpen, and Files.
- The terminal opens a shell session (user's default shell) with `cwd` set to the project directory.
- Multiple terminal sub-tabs are supported: a "+" button creates new sessions, each with an independent shell process. Tabs are closable.
- Terminal sessions persist across tab switches (switching to Kanban and back doesn't kill the shell).
- Terminal sessions are destroyed when the browser tab is closed or the server shuts down.

### Proposed Architecture

**Frontend — xterm.js:**
- [xterm.js](https://github.com/xtermjs/xterm.js) is the standard web terminal emulator. Load via CDN: `xterm.js` core + `xterm-addon-fit` (auto-resize) + `xterm-addon-web-links` (clickable URLs).
- Each terminal sub-tab creates an `xterm.Terminal` instance, connects it to a socket.io channel for I/O.
- The `fit` addon handles resize: on tab switch or window resize, call `fitAddon.fit()` and send new dimensions to the server.

**Backend — node-pty equivalent in Python:**
- Use the `pty` module (Python stdlib `pty.openpty()`) or the `pexpect` library for spawning a PTY subprocess.
- However, `pty.openpty()` is low-level. The recommended approach for Flask-SocketIO is:
  - On `terminal_create` event: spawn a shell process via `pty.fork()` or `subprocess.Popen` with a PTY (using `os.openpty()`). Store the file descriptor and PID per session.
  - On `terminal_input` event: write bytes to the PTY fd.
  - A background thread reads from the PTY fd and emits `terminal_output` events to the client.
  - On `terminal_resize` event: use `fcntl` + `termios` to set the PTY window size (`TIOCSWINSZ`).
  - On `terminal_destroy` or disconnect: kill the shell process and close the fd.

**Protocol (socket.io events):**
- `terminal_create { session_id }` → server spawns shell, confirms with `terminal_created { session_id }`
- `terminal_input { session_id, data }` → server writes data to PTY
- `terminal_output { session_id, data }` → server pushes output to client
- `terminal_resize { session_id, cols, rows }` → server resizes PTY
- `terminal_destroy { session_id }` → server kills shell process

**Component structure:**
- `TerminalTab.js`: Manages sub-tab list, creates/destroys sessions.
- Each sub-tab renders an `xterm.Terminal` instance in a container div.

### Security Considerations
- The terminal runs with the same permissions as the Bullpen server process. This is consistent with the existing file editing capability (which already allows arbitrary file writes via the API).
- Session IDs should be UUIDs to prevent guessing.
- If Bullpen is ever exposed beyond localhost, terminal access must be gated behind authentication. (Same applies to the existing file API.)

### Issues to Resolve Before Planning
- **eventlet compatibility**: eventlet monkey-patches I/O and may conflict with raw PTY fd reads in background threads. This needs a spike/prototype to confirm. Alternative: use `subprocess.Popen` with pipes and `TERM=dumb`, but this loses full terminal emulation (no colors, no cursor positioning). Another alternative: use a dedicated thread with `eventlet.tpool` to isolate the blocking PTY reads.
- **CDN availability of xterm.js**: Confirm xterm.js 5.x is available on unpkg/cdnjs and works without a bundler. The ESM-only distribution of xterm.js 5 may require an import map or a UMD fallback (xterm.js 4.x is UMD-compatible but older).
- **Python PTY on macOS vs Linux**: `pty.fork()` works on both, but behavior may differ. The project currently targets macOS (Darwin). Confirm `os.openpty()` + `pty.fork()` work correctly under eventlet on macOS.
- **Max sessions**: Should there be a limit on concurrent terminal sessions? Propose a default of 5 per project to bound resource usage.
- **Shell detection**: Use `os.environ.get('SHELL', '/bin/bash')` to pick the user's shell. Confirm this works in the eventlet context.

---

## Cross-Cutting Concerns

- **No new npm packages**: The project uses CDN-loaded frontend libraries. xterm.js (Feature 7) would be a new CDN dependency — this is a significant addition and should be reviewed. Python-side, no new pip packages are needed if stdlib `pty` is sufficient; if `pexpect` is needed, that's a new dependency.
- **Test coverage**: Features 1, 3, 6, and 7 require backend tests. Features 2, 4, and 5 are frontend-only. Feature 2 (textarea height bug) may benefit from a visual regression test or at minimum a manual test checklist.
- **Implementation ordering**: Features 4 and 5 are small, low-risk modal fixes. Feature 2 is a CSS bug fix. Feature 1 is a small event-handler change. Feature 3 (archive) is moderate scope. Feature 6 (disposition handoff) requires data model thought. Feature 7 (terminal) is the largest and needs a prototype spike. Suggested order: **4 → 5 → 2 → 1 → 3 → 6 → 7**.
- **Feature 6 depends on stable worker IDs**: If workers don't currently have stable identifiers (independent of grid position), that infrastructure needs to be added before the disposition handoff feature.
