# Implementation Plan — Features-4 (Items 1–5)

**Created:** 2026-04-08
**Source:** features-4.md (items 1–5 in scope; items 6–7 deferred)

---

## Feature Analysis

### 1. Worker card double-click: open task detail instead of config modal
- **File:** `static/components/WorkerCard.js:11` — `@dblclick="$emit('configure', slotIndex)"` is on the root `.worker-card` div, so it fires for both header and body.
- The current task is derived as `worker.task_queue[0]` by the frontend (no `current_task` field from server). The `queuedTasks` computed at line 76 already resolves this.
- Move `@dblclick` to `.worker-card-header` only. Add a new `@dblclick.stop` on `.worker-card-body` that emits `select-task` with the first queued task's ID.
- No server changes needed.

### 2. Files tab: edit mode text disappearing (CSS bug)
- **File:** `static/style.css:866-870` — `.files-viewer-body` has `flex: 1; overflow: auto` but is NOT a flex container.
- **File:** `static/style.css:1008-1013` — `.file-edit-container` has `flex: 1; display: flex; overflow: hidden`.
- **File:** `static/style.css:1015-1028` — `.file-editor-textarea` has `width: 100%; height: 100%`.
- The chain is: `.files-viewer-pane` (flex column) → `.files-viewer-body` (flex: 1, overflow: auto, **not** flex) → `.file-edit-container` (flex: 1) → `textarea` (height: 100%).
- Since `.files-viewer-body` is not a flex container, its children can't use `flex: 1` to stretch. The `height: 100%` on the textarea resolves against an auto-height parent, collapsing.
- Fix: make `.files-viewer-body` a flex column container. Also need `min-height: 0` to prevent flex overflow.

### 3. Archive done tasks
- **File:** `server/tasks.py:194-199` — `delete_task` removes the file. Need a parallel `archive_task` that moves to `tasks/archive/`.
- **File:** `server/tasks.py:106-160` — `list_tasks` scans `_tasks_dir()`. Already skips subdirectories (uses `os.listdir` + `endswith('.md')` + `os.path.isfile`), so archive subdir is naturally excluded.
- **File:** `server/events.py:84-90` — `task:delete` handler pattern to follow for new `task:archive` and `task:archive-done` events.
- **File:** `static/components/KanbanTab.js:11-14` — column headers show label + count, no action buttons. Need to add "Archive All" button to the done column.
- **File:** `static/components/TaskDetailPanel.js:104` — already has a delete button in the footer. Archive button goes beside it.

### 4. Worker config modal: text selection dismisses modal
- **File:** `static/components/WorkerConfigModal.js:55` — `@click.self="$emit('close')"` on overlay.
- Classic mousedown-inside-mouseup-outside bug. Fix with a two-phase check: only close if mousedown also started on the overlay.
- Self-contained to one file.

### 5. Worker config modal height: save button below fold
- **File:** `static/style.css:1096-1108` — modal has `max-height: 85vh`, `overflow-y: auto`.
- **File:** `static/components/WorkerConfigModal.js:155` — expertise textarea has `rows="8"`.
- Best fix: make `.modal-footer` sticky so it's always visible. Optionally reduce textarea rows from 8 to 5.

---

## Tranches

### Tranche 1 — Modal fixes (Features 4, 5)

**Goal:** Fix the two WorkerConfigModal UX issues.

#### T1.1 Fix overlay click-to-dismiss on text selection drag
- **File:** `static/components/WorkerConfigModal.js`
  - Add `overlayMouseDown: false` to `data()` return (line 7)
  - On the overlay div (line 55), replace:
    ```
    @click.self="$emit('close')"
    ```
    with:
    ```
    @mousedown.self="overlayMouseDown = true" @click.self="onOverlayClick"
    ```
  - Add `@mouseup="overlayMouseDown = false"` on the inner `.modal.modal-wide` div (line 56)
  - Add method `onOverlayClick()`:
    ```javascript
    onOverlayClick() {
      if (this.overlayMouseDown) this.$emit('close');
      this.overlayMouseDown = false;
    }
    ```

#### T1.2 Sticky modal footer + reduce textarea rows
- **File:** `static/style.css`
  - Add to `.modal-footer` (line 1131):
    ```css
    position: sticky;
    bottom: 0;
    background: var(--bg-secondary);
    ```
- **File:** `static/components/WorkerConfigModal.js:155`
  - Change `rows="8"` to `rows="5"`

**Checkpoint:** Run full test suite, commit.

---

### Tranche 2 — Files tab edit bug (Feature 2)

**Goal:** Fix the textarea height collapse in the Files tab editor.

#### T2.1 Make files-viewer-body a flex column
- **File:** `static/style.css:866-870`
  - Change `.files-viewer-body` from:
    ```css
    .files-viewer-body {
      flex: 1;
      overflow: auto;
      padding: 0;
    }
    ```
    to:
    ```css
    .files-viewer-body {
      flex: 1;
      overflow: auto;
      padding: 0;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    ```

#### T2.2 Ensure child containers stretch correctly
- **File:** `static/style.css:1008-1013`
  - Add `flex-direction: column` to `.file-edit-container` (it already has `display: flex` but no direction, so the textarea is a row child — should be column for `height: 100%` to work):
    ```css
    .file-edit-container {
      flex: 1;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      position: relative;
      min-height: 0;
    }
    ```
- Verify that non-edit views (source, markdown, image, HTML) still render correctly inside the now-flex `.files-viewer-body`. The existing `.file-view-source`, `.file-view-markdown` etc. should work since they have their own `height`/`overflow` rules.

**Checkpoint:** Manual test: open a 50+ line file, click Edit, verify all content visible. Run full test suite, commit.

---

### Tranche 3 — Worker card double-click behavior (Feature 1)

**Goal:** Double-click card body opens task detail; double-click header opens config.

#### T3.1 Split double-click handlers
- **File:** `static/components/WorkerCard.js`
  - Remove `@dblclick="$emit('configure', slotIndex)"` from root `.worker-card` div (line 11)
  - Add `@dblclick="$emit('configure', slotIndex)"` to `.worker-card-header` div (line 12)
  - Add `@dblclick.stop="onBodyDblClick"` to `.worker-card-body` div (line 27)
  - Add method:
    ```javascript
    onBodyDblClick() {
      const taskId = this.queuedTasks.length ? this.queuedTasks[0].id : null;
      if (taskId) this.$emit('select-task', taskId);
    }
    ```

**Checkpoint:** Run full test suite, commit.

---

### Tranche 4 — Archive done tasks (Feature 3)

**Goal:** Move done tasks to archive subdirectory, with UI triggers.

#### T4.1 Server: archive_task and archive_done functions
- **File:** `server/tasks.py`
  - Add `archive_task(bp_dir, task_id)`:
    ```python
    def archive_task(bp_dir, task_id):
        """Move a task to the archive subdirectory."""
        tasks_dir = _tasks_dir(bp_dir)
        archive_dir = os.path.join(tasks_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        src = os.path.join(tasks_dir, f"{task_id}.md")
        ensure_within(src, tasks_dir)
        dst = os.path.join(archive_dir, f"{task_id}.md")
        if os.path.exists(src):
            os.rename(src, dst)
    ```
  - Add `archive_done_tasks(bp_dir)`:
    ```python
    def archive_done_tasks(bp_dir):
        """Archive all tasks with status 'done'. Returns list of archived IDs."""
        tasks = list_tasks(bp_dir)
        archived = []
        for t in tasks:
            if t.get("status") == "done":
                archive_task(bp_dir, t["id"])
                archived.append(t["id"])
        return archived
    ```

#### T4.2 Server: socket events for archive
- **File:** `server/events.py`
  - Add `task:archive` handler (mirrors `task:delete`):
    ```python
    @socketio.on("task:archive")
    @with_lock
    def on_task_archive(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data)
        task_mod.archive_task(bp_dir, task_id)
        _emit("task:deleted", {"id": task_id}, ws_id)
    ```
    (Reuse `task:deleted` event so the frontend removes it from state — archived tasks behave like deleted from the UI perspective.)
  - Add `task:archive-done` handler:
    ```python
    @socketio.on("task:archive-done")
    @with_lock
    def on_task_archive_done(data):
        ws_id, bp_dir = _resolve(data)
        archived = task_mod.archive_done_tasks(bp_dir)
        for task_id in archived:
            _emit("task:deleted", {"id": task_id}, ws_id)
    ```

#### T4.3 Frontend: Archive All button on done column
- **File:** `static/components/KanbanTab.js`
  - Add `emits: [..., 'archive-done']` to the component
  - In the column header template (lines 11-14), for the done column only, add an "Archive All" button:
    ```html
    <button v-if="col.key === 'done' && columnTasks(col.key).length"
            class="btn btn-sm column-archive-btn"
            @click="$emit('archive-done')"
            title="Archive all done tasks">
      Archive
    </button>
    ```
  - Place it next to the `.column-count` span inside `.kanban-column-header`
- **File:** `static/app.js`
  - On `<KanbanTab>`, add `@archive-done="archiveDone"` handler
  - Add method `archiveDone()`:
    ```javascript
    archiveDone() {
      const count = state.tasks.filter(t => t.status === 'done').length;
      if (count && confirm(`Archive ${count} done task(s)?`)) {
        socket.emit('task:archive-done', { workspaceId: state.activeWorkspaceId });
      }
    }
    ```

#### T4.4 Frontend: Archive button on task detail panel
- **File:** `static/components/TaskDetailPanel.js`
  - Add `'archive'` to emits
  - In the footer (line 104 area), next to the delete button, add:
    ```html
    <button v-if="task.status === 'done'" class="btn btn-sm"
            @click="$emit('archive', task.id)">Archive</button>
    ```
- **File:** `static/app.js`
  - On `<TaskDetailPanel>`, add `@archive="archiveTask"` handler
  - Add method `archiveTask(id)`:
    ```javascript
    archiveTask(id) {
      socket.emit('task:archive', { id, workspaceId: state.activeWorkspaceId });
    }
    ```

#### T4.5 Styling
- **File:** `static/style.css`
  - Add `.column-archive-btn` styling: small, muted, doesn't compete with column label:
    ```css
    .column-archive-btn {
      font-size: 10px;
      opacity: 0.6;
      margin-left: auto;
    }
    .column-archive-btn:hover {
      opacity: 1;
    }
    ```

#### T4.6 Tests
- **File:** `tests/test_tasks.py`:
  - Test `archive_task`: file moves from `tasks/` to `tasks/archive/`, source no longer exists
  - Test `archive_task` on nonexistent task: no error
  - Test `archive_done_tasks`: only done tasks archived, others untouched
  - Test `list_tasks` after archive: archived tasks don't appear
- **File:** `tests/test_events.py`:
  - Test `task:archive` event: emits `task:deleted`
  - Test `task:archive-done` event: archives only done tasks

**Checkpoint:** Run full test suite, commit.

---

## Summary

| Tranche | Feature | Key Files |
|---------|---------|-----------|
| T1 | Modal dismiss bug + sticky footer (4, 5) | WorkerConfigModal.js, style.css |
| T2 | Files tab edit height bug (2) | style.css |
| T3 | Worker card dblclick → task detail (1) | WorkerCard.js |
| T4 | Archive done tasks (3) | tasks.py, events.py, KanbanTab.js, TaskDetailPanel.js, app.js, style.css, tests |

Tranches 1–3 are independent. Tranche 4 is independent but larger, with both server and frontend changes.
