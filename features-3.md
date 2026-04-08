
# Features-3 Specification

Status: Review

---

## 1. Multi-Project Support

### Summary
Allow the user to work across multiple projects (directories/repos) from a single Bullpen instance. All registered projects are kept active simultaneously — agents, scheduled tasks, and event-driven processes continue running in every project regardless of which project is currently visible in the UI. The LeftPane provides a project selector that changes *what is displayed*, not what is running.

### Current State
Bullpen is single-workspace: one directory per process, set at startup via `--workspace` flag. All state lives under that directory's `.bullpen/` subdirectory.

### Desired Behavior
- A **Projects** section appears at the top of the LeftPane, listing all registered projects.
- Each project is shown by name (basename of its path) with a visual indicator for the active (viewed) project.
- Clicking a project changes the active view: the task, worker, and kanban panes render that project's state. No server-side "switch" occurs — the server is already maintaining all projects concurrently.
- An **Add Project** button opens a prompt (text input for path) to register a new project directory. On registration the server initializes that workspace immediately and begins maintaining it.
- Removing a project from the list stops the server from maintaining it (frees resources) but does not delete its `.bullpen/` data.
- The startup `--workspace` flag still works and auto-registers that path into the global registry on first run if not already present.

### Always-Active Architecture

All registered projects are live simultaneously. This requires replacing the single-workspace server model with a multi-workspace manager.

**Server (`WorkspaceManager`):**
- Maintains a `Map<workspaceId, WorkspaceState>` where `WorkspaceState` contains the task list, worker pool, config, and file-watcher for one project.
- On startup, loads `~/.bullpen/projects.json` and initializes a `WorkspaceState` for each entry.
- On `add_project` event, initializes a new `WorkspaceState` immediately; on `remove_project`, tears it down gracefully (waits for in-flight agent tasks to finish or reach a checkpoint before releasing resources).
- All existing server event handlers are refactored to be workspace-scoped: they look up the correct `WorkspaceState` by `workspaceId` rather than referencing a single global state.

**WebSocket protocol:**
- Every event sent from server → client includes a `workspaceId` field. Existing events that lack it are treated as belonging to the startup workspace (backward compat shim, removable later).
- Every event sent from client → server that targets a specific workspace includes a `workspaceId` field. Events without it default to the currently active workspace — but agent/task mutations should always include an explicit ID.

**Frontend state:**
- `state.workspaces` — a map of `workspaceId → { tasks, workers, config, workspace }` for all known projects.
- `state.activeWorkspaceId` — the project currently displayed in the UI.
- Switching the active project is a local state change only; the server is not notified.
- The existing `state.tasks`, `state.workers`, `state.config`, `state.workspace` accessors become computed getters that delegate to `state.workspaces[state.activeWorkspaceId]` for backward compatibility within components.

**Background workspace event surfacing:**
- When an event arrives for a non-active workspace (e.g., task completes, agent errors), the server emits it with the full `workspaceId` context.
- The frontend updates the background workspace's state silently (no pane re-render).
- The project entry in the Projects list shows a badge or highlight when a background workspace has activity since it was last viewed (e.g., a task moved to done, an agent errored). Badge clears when the user switches to that project.
- The exact badge treatment (dot, count, color) is a design decision for implementation.

### Data Model
- Global registry: `~/.bullpen/projects.json` — a list of `{ "id": "uuid", "path": "/abs/path", "name": "display name" }` entries.
- `id` is a stable UUID assigned at registration time; used as the `workspaceId` key throughout.
- Per-project state lives in `<path>/.bullpen/` as before (tasks, config, worker definitions).
- The server never stores cross-project state in a single project's `.bullpen/` directory.

### Scope Boundaries
- Workers are per-project (agents are bound to a workspace directory). A project being "not active in the UI" does not affect its workers.
- Removing a project from the registry triggers graceful shutdown of its `WorkspaceState`: in-flight agent tasks are allowed to reach a natural pause point (or a configurable timeout), then the workspace is released.
- The Bullpen process is started once; it manages all projects from that single process.
- No upper bound on registered projects is enforced by the spec, but the implementation should document resource implications (one file-watcher and one worker pool per project).

### Issues to Resolve Before Planning
- **WorkspaceManager refactor scope**: The existing server code likely assumes a single global workspace. Confirm the full extent of the refactor needed — specifically which modules hold global workspace references (`state.js`, event handlers, file-watchers, adapter initializers).
- **Workspace ID generation**: Confirm UUID v4 (no external lib needed — Node's `crypto.randomUUID()` is available since Node 14.17). UUIDs are assigned at registration and persisted in `projects.json`; they must not be regenerated on re-add of the same path (detect by path match).
- **Per-project config vs. shared config**: Confirm that columns, colors, and settings are per-project (stored in `.bullpen/config.json`) and not shared globally. The `WorkspaceState` must load its own config independently.
- **Event routing on re-connection**: When the client reconnects (page reload), the server must re-send current state for all active workspaces, not just the startup workspace.
- **Security**: The project registry path (`~/.bullpen/projects.json`) must not be writable via the API in a way that allows directory traversal. The server must validate that registered paths exist and are directories (and are not symlinks to unexpected locations) before accepting them. Never allow `path` values containing `..` sequences or non-absolute paths.
- **Testability**: Tests needed for: add project while another workspace has a running agent (both continue); remove project while agent is running (graceful shutdown); client reconnect receives all workspace states; background-workspace badge increments and clears; re-adding a previously removed project reuses its existing `id` if present in the registry.

---

## 2. Agent Icon Colors

### Summary
Update the Codex agent color from its current green (#10a37f) to indigo (#5b6fd6) everywhere it is used.

### Current State
`agentColor()` in `LeftPane.js:72` and `WorkerCard.js:74` returns `{ claude: '#da7756', codex: '#10a37f' }`.

### Changes Required
- Replace `#10a37f` → `#5b6fd6` in all locations that reference the codex agent color:
  - `static/components/LeftPane.js` — `agentColor()` method
  - `static/components/WorkerCard.js` — `agentColor()` computed property
- If `agentColor()` is defined in both files independently, consolidate it into a shared utility (e.g., `static/utils.js`) to avoid future drift. **Only do this if both files define it independently** — do not create a new abstraction if one already delegates to the other.
- No backend changes required.

### Issues to Resolve Before Planning
- None. Grep confirmed `#10a37f` appears only in `static/components/LeftPane.js` and `static/components/WorkerCard.js` — no CSS or other files hardcode this value.

---

## 3. LeftPane: Kanban Column Selector

### Summary
Replace the fixed "Inbox" heading in the LeftPane task section with a dropdown that lets the user filter the task list to any kanban column. New tasks still always default to `status: "inbox"` regardless of the selected column.

### Current State
The LeftPane task section is hardcoded to show tasks with `status === "inbox"` under an "Inbox" label (`LeftPane.js:8-9`, `LeftPane.js:48`).

### Desired Behavior
- A `<select>` (or styled dropdown) replaces the "Inbox" text label.
- Options are populated from `state.config.columns` (the same list used by KanbanTab), preserving their defined order.
- The default selected option is `inbox`.
- The task list below filters to tasks matching the selected column's `key`.
- The "+ New Task" button always creates tasks with `status: "inbox"` regardless of the selected column view.
- The selected column is **local UI state only** — it is not persisted to the server or to disk. On reload it resets to "inbox".

### Edge Cases
- If the active column is deleted from config (columns are configurable), fall back to "inbox".
- Columns with zero tasks still appear in the dropdown.

### Issues to Resolve Before Planning
- None blocking. Implementation is self-contained to `LeftPane.js`.

---

## 4. LeftPane: Worker Items Styled as Card Headers

### Summary
The worker roster items in the LeftPane currently show a status dot, worker name, and an agent-type badge with text. Replace this with a compact display that mirrors the `worker-card-header` style — colored background from agent color, worker name in white — but without the `...` context menu.

### Current State
Each `.roster-item` (`LeftPane.js:29-39`) shows:
- 6px status dot colored by worker state (idle/working/queued)
- Worker name text
- Agent badge (text label: "claude" or "codex")
- Left border in agent color

Worker card headers (`WorkerCard.js:12-26`, `style.css:503-543`) show:
- Full-width colored background (agent color)
- Worker name in white, 12px, 600 weight, ellipsis overflow
- `...` menu button on the right

### Desired Behavior
Each roster item in the LeftPane becomes a compact bar styled like the worker card header:
- Background: agent color (same `agentColor()` function)
- Text: worker name in white, same typography as card header (12px, 600 weight, ellipsis overflow)
- No agent badge / provider name text
- No `...` menu
- Worker state (idle/working/queued) is communicated via bar opacity: idle → 50% opacity, working/queued → 100% opacity. This works on any agent color without additional color choices.
- The drag-over highlight state should still work: the existing `dragOver` class should add a white semi-transparent inset border or `filter: brightness(1.2)` rather than replacing the background color.

### Issues to Resolve Before Planning
- None. State indicator resolved: opacity treatment (idle → 50%, active → 100%). Drag-over resolved: `filter: brightness(1.2)` or white inset border on the colored bar.

---

## Cross-Cutting Concerns

- **No new external libraries**: Consistent with project convention — no YAML libs, no new npm packages without explicit approval. UUID generation uses Node's built-in `crypto.randomUUID()`.
- **Test coverage**: All four features need corresponding tests. Feature 1 requires the most new test surface (WorkspaceManager unit tests, WebSocket event routing integration tests, background-event badge tests). Features 2, 3, and 4 are UI-only and testable via component/snapshot tests.
- **Feature 1 refactor risk**: The WorkspaceManager refactor touches the server's core event-handling path. It should be developed behind a feature flag or in a separate branch with full regression coverage against existing single-workspace behavior before merging.
- **Ordering**: Features 2 and 4 are independent and low-risk; feature 3 is self-contained; feature 1 is a significant server refactor. Suggested implementation order: 2 → 4 → 3 → 1.
