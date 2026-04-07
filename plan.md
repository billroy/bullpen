# Bullpen MVP Implementation Plan

## Guiding Principles

- **Vertical slices.** Each checkpoint delivers a working, testable increment.
- **Backend-first within each step.** Server logic lands before the UI that consumes it.
- **No build step.** The client is plain HTML + CDN-loaded Vue 3 + CDN libraries. No npm, no bundler, ever.
- **Test as you go.** Each step includes its test requirements.
- **Checkpoint commits every ~20 minutes.** Each numbered step below is one commit. Plan and spec updates are committed alongside code changes.

---

## File Structure

```
bullpen/
  bullpen.py               # Entry point (python bullpen.py)
  server/
    __init__.py
    app.py                 # Flask + socket.io app factory
    events.py              # Socket event handlers
    persistence.py         # File I/O (atomic writes, frontmatter, JSON)
    tasks.py               # Task ticket CRUD
    workers.py             # Worker state machine, queue management
    agents/
      __init__.py
      base.py              # AgentAdapter interface
      claude_adapter.py
      codex_adapter.py
    profiles.py            # Profile loading and management
    teams.py               # Team save/load
    validation.py          # Event schema validation, field constraints
    init.py                # First-time .bullpen/ initialization
  static/
    index.html             # Single-page app shell
    app.js                 # Vue 3 app (single file, CDN-loaded Vue)
    components/
      TopToolbar.js        # Top toolbar component
      LeftPane.js          # Inbox + Worker Roster
      KanbanTab.js         # Kanban board
      BullpenTab.js        # Worker card grid
      FilesTab.js          # Workspace file viewer
      WorkerCard.js        # Individual worker card
      TaskCard.js          # Kanban task card
      TaskDetailPanel.js   # Task detail slide-over
      TaskCreateModal.js   # Task creation modal
      WorkerConfigModal.js # Worker configuration overlay
      ToastContainer.js    # Toast notification stack
    style.css              # All styles (single file)
  tests/
    conftest.py            # Fixtures: temp workspace factory, mock adapters
    test_persistence.py
    test_tasks.py
    test_workers.py
    test_agents.py
    test_events.py
    test_validation.py
    test_e2e.py            # Playwright E2E (Phase 6)
  profiles/                # Default profile JSON files (copied to .bullpen/profiles/ on init)
    feature-architect.json
    ... (24 files)
```

---

## Phase 1: Server Foundation + App Shell

### Step 1.1 — Project skeleton + entry point
- `git init`, `.gitignore` (Python defaults + `.bullpen/`)
- Create directory structure (empty `__init__.py` files, placeholder modules)
- `bullpen.py` entry point: parse `--workspace`, `--port`, `--no-browser` with argparse
- `requirements.txt`: `flask`, `flask-socketio`, `eventlet`
- **Test:** `python bullpen.py --help` prints usage

### Step 1.2 — Persistence layer
- `server/persistence.py`:
  - `atomic_write(path, content)` — write to temp file + `os.rename`
  - `read_json(path)` / `write_json(path, data)` — with atomic write
  - `read_frontmatter(path)` / `write_frontmatter(path, meta, body)` — custom string parser: split on `---`, extract `# slug` comment, parse `key: value` lines (split on first `:`), preserve markdown body verbatim
  - `ensure_within(path, root)` — `realpath` boundary check
- `tests/conftest.py`: temp directory fixture
- `tests/test_persistence.py`: atomic write safety, frontmatter round-trip (preserves beans fields, `# slug` line, body), `ensure_within` rejects traversal
- **Test:** `pytest tests/test_persistence.py` passes

### Step 1.3 — Initialization + Flask app + socket.io
- `server/init.py`: create `.bullpen/` tree, `.gitignore` (logs/), `config.json` (defaults), empty `layout.json`, empty prompt files, `tasks/`, `teams/`, `logs/` dirs. Idempotent.
- `server/app.py`: Flask app factory, mount socket.io, serve `static/` at root. On socket connect, load state from `.bullpen/` files and emit `state:init`.
- Wire `bullpen.py` to call app factory and start server.
- `tests/test_init.py`: first-time init creates expected structure, re-run is idempotent, config.json matches defaults
- **Test:** `python bullpen.py` starts server on :5000, `state:init` emits on connect

### Step 1.4 — Frontend app shell
- `static/index.html`: CDN script tags (Vue 3, socket.io-client, markdown-it, Prism.js). Mount `#app`.
- `static/app.js`: Vue app, reactive `state` object, socket.io connect, receive `state:init`. Render: top toolbar (workspace path, bullpen name, connection dot), left pane (placeholder), right pane with tab bar (Kanban / Bullpen / Files), tab content placeholders.
- `static/style.css`: CSS grid two-pane layout, tab bar, base card styles, color variables.
- **Test:** Browser shows connected app shell with three tabs, green connection dot. Visual check.

**Phase 1 milestone:** `python bullpen.py` starts server, browser opens, connected app shell with empty tabs.

---

## Phase 2: Task System + Kanban

### Step 2.1 — Task CRUD backend
- `server/tasks.py`:
  - `create_task(title, description, type, priority, tags)` → generate slug, write `.md` file
  - `read_task(id)` → parse frontmatter + body
  - `update_task(id, fields)` → merge fields, update `updated_at`, atomic write
  - `delete_task(id)` → remove file
  - `clear_task_output(id)` → strip content under `## Agent Output`
  - `list_tasks()` → scan `.bullpen/tasks/`, return all sorted by `order`
  - Slug generation: slugify title + 4-char base62 random suffix
  - Fractional indexing: `generate_order_key()`, `midpoint_key(a, b)`
- `tests/test_tasks.py`: all CRUD ops, slug uniqueness, order key generation + midpoint, clear output preserves body, beans round-trip
- **Test:** `pytest tests/test_tasks.py` passes

### Step 2.2 — Task socket events
- `server/events.py`: handlers for `task:create`, `task:update`, `task:delete`, `task:clear_output`. Each validates payload, calls tasks.py, broadcasts `task:updated` / `task:deleted` to all clients.
- Write serialization: implement single-writer queue in app.py, route mutating events through it.
- `tests/test_events.py`: create/update/delete via Flask-SocketIO test client, verify file written, verify broadcast
- **Test:** `pytest tests/test_events.py` passes

### Step 2.3 — Kanban UI (columns + cards + drag)
- `static/components/KanbanTab.js`: render columns from `state.config.columns`, task cards per column sorted by `order`. HTML5 drag-and-drop between columns. On drop: emit `task:update` with new status + recomputed `order`.
- `static/components/TaskCard.js`: compact card (title, priority badge, type icon). Draggable. Click emits event for detail panel (wired in next step).
- `static/style.css`: kanban column layout, card styling, drag hover states.
- **Test:** Create tasks via socket event from console, see them on kanban, drag between columns.

### Step 2.4 — Task creation modal + detail panel
- `static/components/TaskCreateModal.js`: modal with title, type, priority, tags, description fields. Emit `task:create`.
- `static/components/TaskDetailPanel.js`: slide-over panel. Editable frontmatter fields (title, status, type, priority, tags, assigned_to). Markdown body with view/edit toggle (markdown-it rendering). Agent output section (read-only). Clear output button. Delete button with confirmation. Emit `task:update`.
- Wire "+" button in kanban header and click-on-card to open these.
- Right-click context menu on TaskCard: "Delete" (with confirmation).
- **Test:** Full task lifecycle in browser: create → view → edit → drag → delete.

### Step 2.5 — Left pane inbox
- `static/components/LeftPane.js`: Task Inbox section — flat list of `status=inbox` tasks, newest first. Click opens detail panel. Each entry: title, creation date, priority badge. Make entries draggable (drag data = task ID, drop target wired in Phase 4).
- "+" New Task button in left pane triggers creation modal.
- `static/style.css`: left pane styling, inbox list items.
- **Test:** Inbox populates, clicks work, new task button works.

**Phase 2 milestone:** Full task CRUD + kanban drag-drop + detail panel + inbox. Backend tested.

---

## Phase 3: Worker System + Bullpen Grid

### Step 3.1 — Default profile JSON files
- Write all 24 profile JSON files in `profiles/` directory. Each with: `id`, `name`, `default_agent`, `default_model`, `color_hint`, `expertise_prompt` (substantial 3-10 line prompts with real role instructions).
- `server/profiles.py`: `list_profiles()`, `get_profile(id)`, `create_profile(data)`. Load from `.bullpen/profiles/`.
- Add profiles to `state:init` payload.
- `tests/test_profiles.py`: load defaults (all 24), create custom, verify file.
- **Test:** `pytest tests/test_profiles.py` passes

### Step 3.2 — Worker socket events + layout persistence
- `server/events.py`: handlers for `worker:add`, `worker:remove`, `worker:move`, `worker:configure`, `profile:create`. Each updates `layout.json` and broadcasts `layout:updated`.
- Handlers for `layout:update` (grid resize), `config:update`, `prompt:update`.
- `tests/test_events.py` (additions): add/remove/move/configure via socket client, verify layout.json.
- **Test:** `pytest` passes

### Step 3.3 — Bullpen grid UI + worker cards
- `static/components/BullpenTab.js`: header (grid size dropdown, worker library dropdown + "+" button, bullpen prompt button, clear all button). CSS grid of WorkerCard components and empty "+" slots.
- `static/components/WorkerCard.js`: Monopoly-deed style — colored header band (by agent), worker name (truncated), status pill (IDLE), pencil icon. Card body: empty state placeholder text. Drag-reorderable within grid (swap on drop).
- `static/style.css`: card styling (rounded corners, header band colors, status pill, grid layout).
- **Test:** Add workers from library, see cards on grid, drag to rearrange.

### Step 3.4 — Worker config modal + teams + toolbar
- `static/components/WorkerConfigModal.js`: all config fields (agent, model, activation, watch column, disposition, expertise prompt, max retries). Save / Cancel / Remove / Save as Profile.
- `server/teams.py`: `save_team(name, layout)`, `load_team(name)`, `list_teams()`. Wire events.
- Team library dropdown in BullpenTab header: load and save teams.
- Configuration target validation: on config/layout change, validate `watch_column` and `disposition` refs, reset to defaults + toast if invalid.
- `static/components/TopToolbar.js`: workspace prompt modal, bullpen name inline edit, left pane collapse toggle.
- `static/components/LeftPane.js`: add Worker Roster section (workers grouped by status: WORKING, QUEUED, IDLE).
- `tests/test_teams.py`: save/load, task_queue excluded.
- `tests/test_validation.py`: invalid targets reset correctly.
- **Test:** Configure workers, save/load teams, prompt editing, validation warnings.

**Phase 3 milestone:** Workers on grid, configurable, teams save/load, profiles work. No execution yet.

---

## Phase 4: Agent Execution

### Step 4.1 — Agent adapter layer
- `server/agents/base.py`: `AgentAdapter` ABC with `name`, `available()`, `list_models()`, `build_argv(prompt, model)`, `parse_output(stdout, stderr)`.
- `server/agents/claude_adapter.py`: `shutil.which("claude")` availability check, model list (sensible defaults), argv construction, stdin pipe for prompt.
- `server/agents/codex_adapter.py`: same, with startup capability probe for stdin vs temp-file.
- Mock adapter in `tests/conftest.py`: configurable delay, exit code, stdout/stderr output.
- `tests/test_agents.py`: mock adapter returns expected output, stdin delivery, build_argv correctness.
- **Test:** `pytest tests/test_agents.py` passes

### Step 4.2 — Worker state machine + task assignment
- `server/workers.py`:
  - `assign_task(slot, task_id)` — add to queue, update ticket `assigned_to` + `status=assigned`, trigger activation check
  - `start_worker(slot)` — dequeue task, assemble prompt (workspace + bullpen + expertise + task body + prior output), truncate to 100K chars, invoke adapter, set state=working
  - `stop_worker(slot)` — SIGTERM, 5s wait, SIGKILL. Task to Assigned.
  - `evaluate_queue(slot)` — per activation mode: `on_drop`/`on_queue` auto-advance, `manual` stay idle
- `server/events.py`: wire `task:assign`, `worker:start`, `worker:stop`.
- `tests/test_workers.py`: assign updates ticket, start transitions to WORKING, stop transitions to IDLE + task to Assigned, prompt assembly + truncation.
- **Test:** `pytest tests/test_workers.py` passes

### Step 4.3 — Agent completion + output streaming + disposition
- `server/workers.py`:
  - `on_agent_complete(slot, stdout, stderr, exit_code)` — apply task outcome rules: success → disposition, error → retry or Blocked, timeout → Blocked
  - Output streaming: read stdout in chunks, emit `worker:output` events via socket.io
  - Timeout enforcement: asyncio timer, kill on expiry
  - Append agent output to ticket under `## Agent Output` (50KB cap)
- Retry policy: backoff (5s * attempt), history entries, final failure to Blocked (clear `assigned_to`)
- `worker:reorder` event: update `task_queue` + rewrite ticket `order` fields
- Watch column claim: on `task:updated` with status matching a watch column, auto-assign to idle `on_queue` worker
- `tests/test_workers.py` (additions): full lifecycle with mock adapter (success, error+retry, timeout, stop), disposition routing, watch column auto-claim, reorder durability
- **Test:** `pytest tests/test_workers.py` passes

### Step 4.4 — Worker card live UI + task assignment UX
- `static/components/WorkerCard.js` updates:
  - Status pill transitions (IDLE gray, WORKING blue+pulse, QUEUED purple)
  - Start button (green triangle, QUEUED state), Stop button (red square, WORKING state)
  - Task list in card body showing queued ticket titles
  - Live output area below task list (monospace, last ~20 lines, auto-scroll, visible only when WORKING)
  - Drop target: accept task drag from left-pane inbox, emit `task:assign`
  - Task list drag-reorder within card body, emit `worker:reorder`
- `static/components/TaskCard.js`: right-click "Assign to..." context menu populated from worker roster.
- `static/components/KanbanTab.js`: automatic column transitions in real time.
- **Test:** Full flow in browser: create task → assign → agent runs (mock) → output streams → task disposed. Stop, retry, queue progression.

**Phase 4 milestone:** Core product works end-to-end. This is where it becomes useful.

---

## Phase 5: Files Tab + Lifecycle Polish

### Step 5.1 — File serving backend + startup reconciliation
- File tree endpoint: return workspace directory tree, excluding `.bullpen/`, `.git/`, `node_modules/`, gitignored paths. Enforce `realpath` boundary.
- File content endpoint: read file by path, enforce boundary. Return content + MIME type.
- Startup reconciliation in `server/app.py`: scan tickets → rebuild queues (sort by `order` → `created_at` → slug) → reset WORKING to IDLE → interrupted tasks to Blocked → validate JSON + config targets.
- `tests/test_persistence.py` (additions): reconciliation from dirty state, queue rebuild ordering, orphaned refs, malformed files.
- **Test:** `pytest` passes. Kill server, restart, state is correct.

### Step 5.2 — Files tab frontend
- `static/components/FilesTab.js`: split layout — tree view (left) + file viewer (right).
  - Tree: expandable/collapsible directory nodes, click to open.
  - Tab bar: multiple open files, close button.
  - View modes: `.md` (markdown-it rendered, edit toggle), `.txt` (textarea), source code (Prism.js read-only), `.html` (sandboxed iframe, bare `sandbox`), `.pdf` (`<embed>`), images (`<img>`), other (plain text fallback).
- **Test:** Browse workspace files, open multiple, switch between view modes.

### Step 5.3 — Lifecycle edge cases + toasts + polish
- Confirmation dialogs: remove worker with tasks, team load with active workers, clear all with active workers, delete assigned/in-progress task. Grid resize disabled when it would displace workers.
- `static/components/ToastContainer.js`: bottom-right stack, auto-dismiss 5s (errors persist), max 5.
- Left pane collapse toggle with CSS transition.
- Wire all toast emissions from server events.
- **Test:** All edge cases manually verified. Toast stacking works.

**Phase 5 milestone:** Feature-complete application.

---

## Phase 6: Security Hardening + E2E Tests

### Step 6.1 — Event validation + content sanitization + log management
- `server/validation.py`: JSON schema per event, per-field constraints (title ≤200, description ≤50K, tags ≤20×50, expertise_prompt ≤100K, slug ≤80, enums enforced), unknown fields stripped, payload ≤1MB, slot bounds, ID regex.
- Verify markdown-it HTML disabled, agent output renders as `<pre>`, HTML preview uses bare `sandbox`.
- Log rotation: 100 files per worker slot, prompt truncation to 500 chars in logs.
- `tests/test_validation.py` (additions): oversized payloads rejected, invalid enums rejected, unknown fields stripped, path traversal slugs rejected.
- **Test:** `pytest` passes.

### Step 6.2 — E2E tests
- `tests/test_e2e.py` (Playwright):
  - Happy path: create → assign → run (mock adapter) → output streams → Review → Done
  - Error path: agent fail → retry → Blocked → reassign
  - Stop path: start → Stop → Assigned → restart
  - Team workflow: load team → assign → save new team
  - Security: XSS in title/body, path traversal slug, oversized payload
  - Schema compat: fixtures with missing/extra fields
  - Dual-client: two tabs, create in one, appears in other
- **Test:** `pytest tests/test_e2e.py` passes.

**Phase 6 milestone:** Ship-ready MVP. All tests pass. Release gates met.

---

## Phase Dependencies

```
Phase 1 (Foundation)
  └─► Phase 2 (Tasks + Kanban)
        └─► Phase 3 (Workers + Bullpen Grid)
              └─► Phase 4 (Agent Execution)  ← core value delivered here
                    └─► Phase 5 (Files + Lifecycle Polish)
                          └─► Phase 6 (Security + E2E Tests)
```

Phases are strictly sequential. Each builds on the prior phase's backend and frontend infrastructure. Phase 4 is the critical milestone where the product becomes useful.

---

## Tech Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Async framework | Flask-SocketIO with `eventlet` or `gevent` | Required for socket.io. Agent subprocesses run in green threads. |
| Frontmatter parsing | Custom string parser (no YAML library) | Frontmatter is flat key-value pairs — split on `---`, extract `# slug` line, split remaining lines on first `:`. No library needed, no risk of silent reformatting. |
| Slug generation | `secrets.token_hex(2)` → base62 encode | 4 chars of base-62 = ~14M combinations, sufficient for single-workspace uniqueness. |
| Frontend state | Vue 3 reactive object, single global store | No Vuex/Pinia needed — state is small and fully synced via socket events. |
| Drag-and-drop | HTML5 Drag and Drop API | No library needed. Kanban column drops, card-to-worker drops, card grid reorder. |
| Syntax highlighting | Prism.js (CDN) | Lighter than CodeMirror/Monaco, sufficient for read-only view. |
| Markdown rendering | markdown-it (CDN) | Fast, extensible, HTML disabled by default (sanitization). |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Claude/Codex CLI flags change | High | Medium | Adapter layer isolates changes to one file per agent. |
| HTML5 DnD cross-browser quirks | Medium | Medium | Keep drag logic simple (dataTransfer with task/card IDs). Test Chrome + Safari. |
| Agent output too large for socket streaming | Low | Medium | 50KB cap per run. Stream in chunks, don't buffer entire output. |
| Custom frontmatter parser edge cases | Low | Low | Simple format, but test round-trip extensively: multiline values, special characters in titles, empty fields, beans files from other tools. |
| Green thread + subprocess interaction | Medium | Medium | Test early in Phase 4. Fall back to threading if eventlet/gevent subprocess support is problematic. |
