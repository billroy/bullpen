# Bullpen MVP Functional Specification

## Overview

Bullpen is an agent orchestration framework for software development. An Operator (human user) dispatches tasks to specialized AI Workers organized into a visual bullpen grid. Workers package task context with their expertise prompts and ship them to local CLI-based AI agents (Claude, Codex) for processing.

**MVP scope:** Single user, single workspace, local execution only.

---

## Core Concepts

### Operator
The human user running the bullpen. The Operator:
- Configures the bullpen layout and worker slots
- Creates and manages task tickets on the kanban
- Assigns tasks to workers (drag-drop or manual)
- Reviews completed work and handles exceptions
- Defines workspace-level context (workspace prompt)

### Worker
An AI-powered agent slot in the bullpen grid. Each worker has:
- **Profile**: A named expertise (e.g., "Feature Architect") with a system prompt
- **Agent binding**: Which CLI agent to use (Claude, Codex)
- **Model binding**: Which model to use (agent-specific options)
- **Activation mode**: How the worker picks up tasks
- **Disposition**: Where completed tasks go next
- **Task queue**: An ordered list of assigned task ticket references

### Task Ticket
A markdown file in `.bullpen/tasks/` representing a unit of work. Tickets flow through kanban columns and can be assigned to workers.

### Workspace
The project directory the bullpen is operating on. The `.bullpen/` folder within it holds all bullpen state.

---

## Application Layout

The app is a two-pane layout with a fixed top toolbar.

```
+----------------------------------------------+
|  Top Toolbar                                  |
+-------------+--------------------------------+
|             |                                |
|  Left Pane  |         Right Pane             |
|  (Nav/Tree) |     (Tabbed Content Area)      |
|             |                                |
|             |                                |
+-------------+--------------------------------+
```

### Top Toolbar
- **Workspace indicator**: Shows current workspace path. Click to select/change workspace root directory.
- **Bullpen name**: Editable name for this bullpen instance (stored in `.bullpen/config.json`).
- **Connection status**: Socket.io connection indicator (green dot = connected).
- **Workspace prompt button**: Opens a modal editor for the workspace-level prompt. This text is prepended to every agent invocation to provide project context (e.g., "This is a Python 3.12 project using Flask..."). Stored in `.bullpen/workspace_prompt.md`.

### UI Conventions

- **Toast notifications**: Appear bottom-right, stacked upward. Auto-dismiss after 5 seconds for info/success; error toasts persist until manually dismissed (click "x"). Maximum 5 visible; older toasts are dismissed to make room.
- **Left pane**: Fixed width, approximately 280px. Collapsible via a toggle icon in the top toolbar. When collapsed, the left pane is fully hidden and the right pane expands to fill the window.
- **Confirmation dialogs**: Used for destructive operations (delete task, remove worker, load team, clear output). Centered modal with description of consequences, Cancel (default focus) and Confirm buttons.

---

## Left Pane

The left pane serves as a navigation and quick-access panel. It has two collapsible sections:

### Task Inbox (top section)
- Flat list of all task tickets in the **Inbox** kanban column, sorted newest-first.
- Each entry shows: ticket title, creation date, priority badge (if set).
- Click a ticket to open the task detail panel.
- Drag a ticket from here onto a worker card in the Bullpen tab to assign it.
- **"+ New Task" button** at the top: creates a new ticket in Inbox state via the task creation modal.

### Worker Roster (bottom section)
- Flat list of all currently hired (placed) workers, grouped by status: WORKING, QUEUED, IDLE.
- Each entry shows: worker name, status pill, current task title (if any).
- Click a worker to scroll to and highlight their card in the Bullpen tab.

> **Design rationale:** The left pane gives the Operator persistent visibility into what needs attention (inbox) and who is doing what (roster) regardless of which right-pane tab is active.

---

## Right Pane Tabs

The right pane has a tab bar with three tabs: **Kanban**, **Bullpen**, **Files**.

---

## Kanban Tab

### Columns
The kanban displays task tickets organized into columns. Default columns for MVP:

| Column | Meaning |
|--------|---------|
| **Inbox** | New tasks awaiting triage/assignment |
| **Assigned** | Tasks assigned to a worker but not yet started |
| **In Progress** | Tasks currently being processed by an agent |
| **Review** | Completed tasks awaiting Operator review |
| **Done** | Accepted/closed tasks |
| **Blocked** | Tasks that encountered errors or need Operator intervention |

Columns are defined in `.bullpen/config.json` and can be customized. The above are the defaults created on workspace initialization.

### Kanban Interactions
- **Drag tickets** between columns to change status. The ticket file is updated on drop.
- **Click a ticket** to open the task detail panel (see Task Detail Panel below).
- **Right-click a ticket** for context menu: "Assign to..." (submenu listing workers by name), "Delete" (with confirmation).
- **Filter bar** at top of kanban: text search across ticket titles and tags.
- **"+ New Task" button**: Creates a new ticket in Inbox via the task creation modal (see Task Creation Modal below).

> **Note:** Cross-tab drag from Kanban to Bullpen is not supported because tabs are mutually exclusive views. Task assignment to workers is done via: (1) dragging from the left-pane inbox onto a worker card in the Bullpen tab, or (2) right-click -> "Assign to..." on any kanban card.

### Task Creation Modal

Triggered by the "+ New Task" button in the kanban header or left-pane inbox. A centered modal with fields:

| Field | Type | Required | Default |
|-------|------|----------|---------|
| **Title** | Text input | Yes | — |
| **Type** | Dropdown (`task`, `bug`, `feature`, `chore`) | No | `task` |
| **Priority** | Dropdown (`low`, `normal`, `high`, `urgent`) | No | `normal` |
| **Tags** | Comma-separated text input | No | empty |
| **Description** | Markdown textarea (4-6 lines visible) | No | empty |

**Create** button generates a slug, creates the ticket file in `.bullpen/tasks/`, and closes the modal. The new ticket appears in the Inbox column. **Cancel** discards.

### Task Detail Panel

Triggered by clicking a ticket on the kanban or in the left-pane inbox. Opens as a slide-over panel on the right side of the kanban (or as a modal if the Bullpen/Files tab is active).

**Header area:** Editable form controls for frontmatter fields:
- Title (inline-editable text)
- Status (dropdown — effectively moves the ticket between columns)
- Type, Priority (dropdowns)
- Tags (comma-separated text input)
- Assigned to (dropdown listing workers, or "Unassigned")

**Body area:** The markdown body of the ticket (everything below `---`), shown as rendered markdown with a toggle to raw edit mode. In edit mode, a simple markdown textarea.

**Agent Output area:** Read-only section below the body showing all agent output entries, each with timestamp and worker/agent label. **"Clear Output"** button removes all entries under `## Agent Output` (with confirmation).

**Footer:** **Save** (persists changes, emits `task:update`), **Delete** (trash icon, with confirmation dialog, emits `task:delete`), **Close** (discards unsaved changes).

### Automatic Column Transitions
Workers automatically move tickets between columns:
- Worker picks up task: Inbox/Assigned -> **In Progress**
- Agent completes successfully: In Progress -> **Review** (or to disposition target)
- Agent errors/times out: In Progress -> **Blocked**

---

## Task Ticket Format

Tickets are stored as `.md` files in `.bullpen/tasks/`. The format is compatible with [beans](https://github.com/hmans/beans), a lightweight YAML-frontmatter task tracker.

### Beans Format Compatibility

Beans files use **YAML front matter** — the `---` delimiters are standard YAML document boundary markers adopted by static site generators (Jekyll, Hugo) and many markdown tools. The opening `---` starts the YAML block; the closing `---` ends it. Everything between is parsed as YAML. Everything after the closing `---` is free-form markdown body content. This is a widely supported convention, not beans-specific.

Beans uses a comment line (`# slug`) as the first line inside the front matter to embed a human-readable unique ID. We adopt this convention, using the pattern `{project}-{short-description}-{4char-id}` for the slug.

**Filename format:** `{slug}.md` (e.g., `bullpen-add-auth-middleware-8k2f.md`). The slug matches the `#` line inside the file.

```markdown
---
# bullpen-add-auth-middleware-8k2f
title: Add auth middleware
status: inbox
type: task
priority: normal
assigned_to:
created_at: 2026-04-07T14:30:22Z
updated_at: 2026-04-07T14:30:22Z
order: V
tags: [backend, auth]
---

## Description

Add JWT-based authentication middleware to the Flask API routes.

## Acceptance Criteria

- All /api/ routes require a valid JWT
- Returns 401 with clear error message on failure

## Agent Output

<!-- Worker appends agent responses below this line -->
```

### Frontmatter Fields

**Beans-compatible fields** (present in standard beans files):
- `# {slug}`: Comment line with unique ID slug (first line after opening `---`)
- `title`: Short human-readable title
- `status`: Current kanban column key (`inbox`, `assigned`, `in_progress`, `review`, `done`, `blocked`)
- `type`: Task type — `task`, `bug`, `feature`, `chore` (default: `task`)
- `priority`: `low`, `normal`, `high`, `urgent`
- `created_at` / `updated_at`: ISO 8601 timestamps with `Z` suffix (UTC)
- `order`: Sort-order key for position within a column (beans uses base-62 string; we adopt the same)

**Bullpen extensions** (additional fields we add):
- `assigned_to`: Worker slot ID or empty
- `tags`: Freeform string tags for filtering
- `history`: Array of `{timestamp, event, detail}` objects tracking state transitions

Beans files that lack our extension fields are treated as valid — missing fields get defaults. This means `.bullpen/tasks/` can contain beans files created by other tools and they will appear correctly on the kanban.

### Agent Output Section

When a worker's agent completes, the output is appended under the `## Agent Output` heading in the markdown body (below the closing `---`). Each entry is timestamped:

```markdown
### 2026-04-07T15:02:33Z — Feature Architect (claude/sonnet)

Agent response text here...
```

This creates a running log of all agent interactions for a task. Output is capped at 50KB per agent run (truncated with notice) to prevent unbounded ticket growth.


## Bullpen Tab

### Bullpen Tab Header
Controls above the worker card grid:

- **Rows x Columns dropdown**: Default 4x6, options from 2x2 up to 7x10. Changes grid layout immediately.
- **Worker Library selector**: Dropdown listing all available worker profiles (the built-in defaults plus any user-created). Click the **"+"** button next to it to add the selected profile to the next empty slot. If the grid is full, the add is rejected with a toast notification.
- **Team Library selector**: Dropdown listing saved team configurations. Selecting one replaces the current bullpen layout with the saved team. **"Save Team"** button saves the current layout as a named team.
- **Bullpen prompt button**: Opens a modal editor for the bullpen-level prompt. This text is included in every agent invocation from this bullpen, between the workspace prompt and the worker's expertise prompt. Stored in `.bullpen/bullpen_prompt.md`. Use case: "Focus on test coverage" or "Use TypeScript strict mode."
- **"Clear All" button**: Removes all workers from the grid. See Lifecycle Edge Cases for task handling and confirmation.

### Worker Card Grid
A CSS grid of worker cards. Empty slots show a dashed border with a "+" button to add a worker from the library.

Cards can be **drag-reordered** within the grid. Dragging a card to an empty slot moves it; dragging to an occupied slot swaps the two cards.

---

## Worker Card

Visual design: Monopoly deed-card style with rounded corners, colored header band, white body.

### Card Header
- **Background color**: Determined by the bound agent (e.g., Claude = warm orange, Codex = green). Shown as a color band across the top of the card.
- **Worker name**: Bold text (e.g., "Feature Architect"). Truncated with ellipsis if too long.
- **Pencil icon**: Click to expand the card into edit/configuration mode (see Worker Card Configuration below).
- **Status pill**: Small badge showing the worker's display status. The state machine has two states (`idle`, `working`); the UI derives a third display status for clarity:
  - `IDLE` (gray) - No active task, queue empty
  - `WORKING` (blue, with pulse animation) - Agent is processing
  - `QUEUED` (purple) - Derived: worker state is `idle`, queue is non-empty, activation is `manual`. Indicates the Operator needs to click Start.
- **Start button** (green triangle icon): Visible only when status is QUEUED. Triggers the worker to pick up and process the next task in its queue. Emits `worker:start`.
- **Stop button** (red square icon): Visible only when status is WORKING. Sends kill signal to the running agent process.

### Card Body
- **Task list**: Shows the worker's task queue (0-N tickets). Each entry shows the ticket title, truncated. The currently active task (if any) is highlighted with a bold label.
- **Live output area**: When the worker is WORKING, a monospace output area appears below the task list showing the last ~20 lines of streaming agent output (fed by `worker:output` events). Auto-scrolls to bottom. Collapses when the worker returns to IDLE.
- **Drop target**: The entire card body is a drop target for task tickets dragged from the kanban or left pane inbox.
- When a task is dropped:
  - The ticket's `assigned_to` is set to this worker's slot ID.
  - The ticket's `status` changes to `assigned`.
  - The task appears in the worker's queue.
  - If activation mode is `on_drop`, the worker begins processing immediately (if idle).

### Card Body — Empty State
When a worker has no tasks, the body shows italicized placeholder text: *"Drop a task here or configure a watch column."*

---

## Worker Card Configuration

Clicking the pencil icon expands the card into a configuration overlay (or modal). Fields:

| Field | Type | Description |
|-------|------|-------------|
| **Worker name** | Text input | Display name for this worker |
| **Worker type** | Dropdown | Select from worker library profiles, or "Custom" |
| **Agent** | Dropdown | `claude`, `codex` |
| **Model** | Dropdown | Agent-specific. Claude: `sonnet`, `opus`, `haiku`. Codex: `o3-mini`, `o4-mini`. Populated dynamically based on agent selection. |
| **Activation** | Dropdown | `on_drop` (start when task is assigned), `on_queue` (watch a kanban column and auto-pick-up), `manual` (Operator must click "Start") |
| **Watch column** | Dropdown | Only visible when activation = `on_queue`. Selects which kanban column to watch. See Watch Column Claim Mechanism. |
| **Disposition** | Dropdown | Where to send completed tasks: `review` (move to Review column), `worker:{slot_id}` (hand off to another worker's queue), `done` (move to Done column) |
| **Expertise prompt** | Textarea | The worker's system prompt. Pre-filled from the worker profile but fully editable. This defines what the worker does and how. |
| **Max retries** | Number (0-3) | How many times to retry on agent error before moving task to Blocked. Default: 1. See Retry Policy below. |

**Save** button persists the config; **Cancel** discards changes; **Remove** button removes the worker from the grid (returns slot to empty). **Save as Profile** button saves the current worker configuration as a new reusable profile in `.bullpen/profiles/` — prompts for a profile name, generates an ID slug, and the new profile appears in the Worker Library selector immediately.

---

## Worker Profiles (Default Library)

24 built-in profiles ship with the product. Each profile defines a name, default agent, default model, a color hint, and an expertise prompt.

### Proposed Default Profiles

**Architecture & Design (4)**
1. Feature Architect — Designs feature implementations given requirements
2. API Designer — Designs API contracts and endpoint specifications
3. Database Architect — Designs schemas, migrations, and data models
4. System Architect — Evaluates cross-cutting concerns, integration patterns

**Implementation (6)**
5. Frontend Developer — Implements UI components and client-side logic
6. Backend Developer — Implements server-side logic and API endpoints
7. Full-Stack Developer — Implements features across the entire stack
8. DevOps Engineer — Writes CI/CD pipelines, Dockerfiles, infrastructure config
9. Test Writer — Writes unit tests, integration tests, and test fixtures
10. Migration Writer — Writes database migrations and data transformation scripts

**Review & Quality (5)**
11. Code Reviewer — Reviews code for bugs, style, security, and best practices
12. Plan Reviewer — Reviews implementation plans for completeness and feasibility
13. Security Reviewer — Audits code for vulnerabilities and security best practices
14. Performance Reviewer — Analyzes code for performance bottlenecks
15. Accessibility Reviewer — Reviews UI code for accessibility compliance

**Operations (4)**
16. Code Merger — Resolves merge conflicts and integrates branches
17. Deployer — Manages deployment steps and verifies deployment health
18. Release Manager — Prepares changelogs, version bumps, release notes
19. Dependency Manager — Audits and updates project dependencies

**Documentation & Support (3)**
20. Technical Writer — Writes and updates documentation
21. API Documenter — Generates and maintains API reference documentation
22. Onboarding Guide — Creates developer onboarding materials and READMEs

**Specialized (2)**
23. Bug Triager — Analyzes bug reports, reproduces issues, suggests root causes
24. Refactoring Specialist — Identifies and executes safe refactoring operations

> Profiles are stored in `.bullpen/profiles/` as individual JSON files. Users can create custom profiles or modify the defaults.

---

## Worker State Machine

Workers follow a deterministic state machine. The current state is displayed on the worker card status pill.

```
    ┌──────┐  pick up   ┌─────────┐  success/error/stop/timeout   ┌──────┐
    │ IDLE │──────────►│ WORKING │──────────────────────────────►│ IDLE │
    └──────┘            └─────────┘                                └──────┘
       ▲                                                             │
       │              (evaluate queue per activation mode)           │
       └─────────────────────────────────────────────────────────────┘
```

The worker has only two states. Task outcomes determine what happens to the **task** (disposition, Blocked column, etc.) but the **worker** always returns to IDLE.

### State Definitions

| State | Meaning | Transitions Out |
|-------|---------|-----------------|
| **IDLE** | No active task. If queue is non-empty, behavior depends on activation mode (see below). | -> WORKING (pick up next task) |
| **WORKING** | Agent process is running for the current task. | -> IDLE (on any outcome: success, error after max retries, stop, or timeout) |

Note: there is no BLOCKED worker state. **BLOCKED is a task status (kanban column), not a worker state.** When a task fails terminally, the task moves to the Blocked column, but the worker always returns to IDLE and evaluates its queue per activation mode. This keeps workers productive — a single bad task does not stall the queue.

### Task Outcome Rules

When an agent process finishes, the outcome determines what happens to the **task**:

| Outcome | Task Disposition |
|---------|-----------------|
| **Success** (exit 0) | Task is routed per the worker's disposition setting: move to Review, Done, or hand off to another worker. |
| **Error** (non-zero exit, retries exhausted) | Task moves to **Blocked** column. See Retry Policy. |
| **Timeout** | Task moves to **Blocked** column. Timeout notice appended to ticket. Not subject to retry. |
| **Stop** (Operator clicked Stop) | Task moves to **Assigned** column (preserving `assigned_to`). Treated as a pause, not a failure — no error logged, no retry consumed. |
| **Cancelled** (Operator dragged task away during WORKING) | Task moves to its new column/assignment. No error, no retry. |

In all cases the **worker** returns to IDLE after the outcome is applied, then evaluates its queue:

### Queue Progression Rules by Activation Mode

| Activation Mode | Auto-advance to next queued task? | Notes |
|-----------------|-----------------------------------|-------|
| `on_drop` | **Yes.** Immediately picks up next task if queue is non-empty. | Tasks are processed in queue order as fast as they arrive. |
| `on_queue` | **Yes.** If queue is empty, also claims from the watch column (see below). | Continuous processing mode. |
| `manual` | **No.** Worker goes to QUEUED (if tasks remain) or IDLE (if empty). Operator must click "Start" to process the next task. | Operator retains explicit control over each invocation. |

### Watch Column Claim Mechanism (`on_queue`)

Workers with `activation: on_queue` do not poll. The server maintains a registry of watch-column bindings. Whenever a task enters a watched column — via creation, manual drag, or another worker's disposition — the server evaluates all idle `on_queue` workers watching that column and assigns the oldest unclaimed task (by `order`, then `created_at`, then slug) to the first idle watcher. If multiple idle workers watch the same column, assignment round-robins by least-recently-active.

This is event-driven: the check triggers on any `task:updated` event where the new status matches a watched column.

### Configuration Target Validation

Worker config fields that reference other entities (`watch_column`, `disposition`) are validated whenever the referenced entity changes:

| Event | Validation Rule | Fallback |
|-------|----------------|----------|
| **Column deleted/renamed** | Workers with `watch_column` referencing the removed column are invalidated. | `activation` resets to `manual`. Toast warning: "{worker} watch column no longer exists." |
| **Worker slot removed** | Workers with `disposition: worker:{slot}` referencing the removed slot are invalidated. | `disposition` resets to `review`. Toast warning: "{worker} handoff target removed." |
| **Team loaded** | All worker configs in the new team are validated against current columns. | Invalid references reset to defaults as above. |
| **Grid resized** | Covered by Lifecycle Edge Cases — resize is blocked if it would displace workers. | N/A |

Validation also runs at startup reconciliation. Invalid targets are reset and logged.

### Queue-to-Kanban Consistency

**Invariant: The task ticket file is the single source of truth.** Worker queues in `layout.json` are derived references.

- The `assigned_to` and `status` fields in the ticket frontmatter are canonical.
- Worker `task_queue` arrays in `layout.json` are convenience indexes, rebuilt on server startup by scanning all ticket files.
- If the Operator drags a ticket to a different column or reassigns it while it's queued on a worker, the server:
  1. Updates the ticket file (canonical).
  2. Removes the stale reference from the old worker's queue.
  3. Adds the reference to the new worker's queue (if reassigned).
  4. If the ticket was the worker's **active** task (WORKING state), the agent process is stopped, and the task is treated as a cancellation (no error, no retry).

This means the Operator can always override worker state by manipulating tickets on the kanban, and the system will reconcile.

---

## Agent Invocation

When a worker processes a task, it constructs a prompt and invokes a CLI agent.

### Prompt Assembly Order
The prompt sent to the agent is assembled from these parts, in order:

1. **Workspace prompt** (`.bullpen/workspace_prompt.md`) — project-level context
2. **Bullpen prompt** (`.bullpen/bullpen_prompt.md`) — session/focus-level context
3. **Worker expertise prompt** — the worker's system prompt defining its role
4. **Task content** — the full markdown body of the task ticket (below the frontmatter)
5. **Previous agent output** (if any, from prior attempts or earlier workers in a chain)

These are concatenated with clear section delimiters.

### Agent Adapter Layer

Each supported agent is wrapped in an **adapter** — a Python module that encapsulates CLI discovery, argument construction, model enumeration, and output parsing. This isolates the rest of the system from CLI flag churn.

```python
# Adapter interface (conceptual)
class AgentAdapter:
    name: str                              # "claude", "codex"
    def available() -> bool                # Is the CLI on PATH?
    def list_models() -> list[str]         # Query available models
    def build_argv(prompt, model) -> list  # Return subprocess argv list
    def parse_output(stdout, stderr) -> AgentResult
```

The model selector dropdown in worker configuration is populated by calling `adapter.list_models()` at startup (and refreshable). This avoids hardcoded model lists that break when CLIs add or rename models. If a previously-configured model is no longer available, the worker shows a validation warning on its card and refuses to start until reconfigured.

### CLI Invocation

**Security requirement:** All agent processes MUST be launched via `subprocess.Popen` (or `asyncio.create_subprocess_exec`) with an **argv list** and `shell=False`. Prompt content is passed via stdin pipe or temporary file — **never interpolated into a shell command string**. The executable path is resolved against an explicit allowlist (`claude`, `codex`), not arbitrary PATH lookup.

**Claude adapter:**
```python
subprocess.Popen(
    ["claude", "-p", "-", "--model", model, "--output-format", "text"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=workspace_root,
    shell=False
)
# Prompt written to stdin, then stdin closed
```

**Codex adapter:**
Each adapter probes its CLI's capabilities at startup. For prompt delivery, the adapter tests whether the CLI accepts stdin (e.g., `--prompt -`) and falls back to writing a temp file if not. This is a required adapter behavior, not an open issue.

```python
# Preferred: stdin pipe
subprocess.Popen(
    ["codex", "--model", model, "--prompt", "-", "--auto-edit"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    cwd=workspace_root, shell=False
)

# Fallback: temp file (if stdin not supported)
subprocess.Popen(
    ["codex", "--model", model, "--prompt-file", prompt_tmpfile, "--auto-edit"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    cwd=workspace_root, shell=False
)
# Temp file is deleted after process exits.
```

### Invocation Policies

- **Prompt length limits:** Truncate the assembled prompt to a configured max character limit (default 100,000 chars), preferring to truncate earlier agent output over the current task or expertise prompt. Log a warning on the task when truncation occurs.
- **Output capture:** Capture stdout as the agent's response. Capture stderr for error detection. Stream stdout to the worker card in real-time via socket.io so the Operator can watch progress.
- **Timeouts:** Agent processes run asynchronously on the server. The worker's status is WORKING until the process exits. The Stop button sends SIGTERM then SIGKILL after 5 seconds. A configurable timeout (default: 10 minutes) kills the process and moves the task to Blocked.
- **File mutations:** Agent output (stdout) is captured and appended to the task ticket. File modifications by agents that support them (like Codex with `--auto-edit`) are permitted since the agent runs in the workspace directory. These are agent-driven changes only — the Files tab does not provide source-code editing. The Operator reviews all agent-driven file changes via their normal git workflow (diff, commit, revert).

### Agent Trust Model

Agents run as local processes with the Operator's full user permissions. This is the same trust level as running `claude` or `codex` from the terminal directly — bullpen does not elevate or restrict agent capabilities.

**Bullpen does not sandbox agent processes.** Sandboxing local CLI tools that are designed to read and write the filesystem would break their core functionality and provide false security. The Operator is responsible for:
- Choosing which agents and models to deploy
- Reviewing agent-driven file changes before committing (standard git workflow)
- Not running bullpen on directories containing sensitive files that agents should not access

This trust model is appropriate for MVP (single user, local machine). Multi-user or remote-agent scenarios (future) would require revisiting with proper sandboxing and access controls.

---

## Persistence and File Structure

All state lives in the `.bullpen/` directory at the workspace root. No database. Everything is human-readable and git-committable.

```
.bullpen/
  .gitignore               # Ignores logs/ by default
  config.json              # Bullpen configuration (grid size, column definitions, name)
  workspace_prompt.md      # Workspace-level context prompt
  bullpen_prompt.md        # Bullpen-level context prompt
  tasks/                   # Task ticket markdown files (beans-compatible)
    bullpen-add-auth-middleware-8k2f.md
    bullpen-fix-login-bug-3np1.md
    ...
  profiles/                # Worker profile definitions
    feature-architect.json
    code-reviewer.json
    ...  (24 defaults + user-created)
  teams/                   # Saved team configurations
    default.json
    frontend-team.json
    ...
  layout.json              # Current bullpen grid state (which worker in which slot, config overrides)
  logs/                    # Agent invocation logs
    {worker-slot}-{timestamp}.log
```

### config.json
```json
{
  "name": "My Bullpen",
  "grid": { "rows": 4, "cols": 6 },
  "columns": [
    { "key": "inbox", "label": "Inbox", "color": "#6B7280" },
    { "key": "assigned", "label": "Assigned", "color": "#3B82F6" },
    { "key": "in_progress", "label": "In Progress", "color": "#8B5CF6" },
    { "key": "review", "label": "Review", "color": "#F59E0B" },
    { "key": "done", "label": "Done", "color": "#10B981" },
    { "key": "blocked", "label": "Blocked", "color": "#EF4444" }
  ],
  "agent_timeout_seconds": 600,
  "max_prompt_chars": 100000
}
```

### layout.json

**Slot ID convention:** Slots are identified by their array index in the `slots` array, which maps to grid position as `row * cols + col`. Slot IDs are positional and not stable across grid resizes or team loads — this is why bulk operations (team load, clear all) first unassign all tasks (clearing `assigned_to`) before replacing the grid. After a layout change, tasks are unowned and must be reassigned.

```json
{
  "slots": [
    {
      "row": 0, "col": 0,
      "profile": "feature-architect",
      "agent": "claude",
      "model": "sonnet",
      "activation": "on_drop",
      "disposition": "review",
      "watch_column": null,
      "expertise_prompt": "You are a Feature Architect...",
      "max_retries": 1,
      "task_queue": ["bullpen-add-auth-middleware-8k2f"]
    },
    null,
    ...
  ]
}
```

### Team JSON

Teams are layout templates — they capture worker placement and configuration but not in-progress task queues. Stored in `.bullpen/teams/`.

```json
{
  "name": "Frontend Team",
  "grid": { "rows": 2, "cols": 3 },
  "slots": [
    {
      "row": 0, "col": 0,
      "profile": "frontend-developer",
      "agent": "claude",
      "model": "sonnet",
      "activation": "on_drop",
      "disposition": "review",
      "watch_column": null,
      "expertise_prompt": "You are a Frontend Developer...",
      "max_retries": 1
    },
    null
  ]
}
```

Note: `task_queue` is deliberately excluded. Loading a team populates worker slots but does not assign any tasks — those remain in whatever kanban column they were in.

### Worker Profile JSON
```json
{
  "id": "feature-architect",
  "name": "Feature Architect",
  "default_agent": "claude",
  "default_model": "sonnet",
  "color_hint": "orange",
  "expertise_prompt": "You are a Feature Architect. Given a feature request or requirement, you produce a detailed implementation plan including:\n- Component breakdown\n- File changes needed\n- Data model changes\n- API changes\n- Migration steps\n- Risk areas and edge cases\n\nBe specific about file paths and function signatures. Reference existing code patterns in the project."
}
```

---

## Socket.io Events

All client-server communication uses socket.io. No REST endpoints for core functionality.

### Server -> Client Events

| Event | Payload | Purpose |
|-------|---------|---------|
| `state:init` | Full app state (config, layout, tasks) | Sent on client connect |
| `task:updated` | Task ticket object | Task was created, modified, or moved |
| `task:deleted` | Task ID | Task was deleted |
| `worker:status` | `{slot, status, task_id, queue_length}` | Worker status changed. `status` is a state machine value (`idle` or `working`). Clients derive the `QUEUED` display status locally from `status=idle` + `queue_length>0` + `activation=manual`. |
| `worker:output` | `{slot, chunk}` | Real-time streaming output from agent |
| `worker:completed` | `{slot, task_id, output}` | Agent finished successfully |
| `worker:error` | `{slot, task_id, error}` | Agent errored |
| `layout:updated` | Layout object | Grid layout changed |
| `config:updated` | Config object | Configuration changed |
| `toast` | `{level, message}` | Notification for the Operator |

### Client -> Server Events

| Event | Payload | Purpose |
|-------|---------|---------|
| `task:create` | `{title, description, type, priority, tags}` | Create a new task ticket. `type` defaults to `task` if omitted. |
| `task:update` | `{id, fields...}` | Update task fields (including status) |
| `task:delete` | `{id}` | Delete a task (with lifecycle checks — see Lifecycle Edge Cases) |
| `task:clear_output` | `{id}` | Remove all content under `## Agent Output` in the ticket |
| `task:assign` | `{task_id, slot}` | Assign task to worker slot |
| `worker:start` | `{slot}` | Manually start a worker |
| `worker:stop` | `{slot}` | Stop a running agent |
| `worker:configure` | `{slot, config...}` | Update worker slot configuration |
| `worker:add` | `{slot, profile_id}` | Add a worker from library to a slot |
| `worker:remove` | `{slot}` | Remove a worker from a slot |
| `worker:move` | `{from_slot, to_slot}` | Move/swap workers between slots |
| `worker:reorder` | `{slot, task_ids: [...]}` | Reorder a worker's task queue (full ordered list) |
| `layout:update` | `{rows, cols}` | Change grid dimensions |
| `config:update` | `{fields...}` | Update bullpen configuration |
| `profile:create` | `{name, agent, model, expertise_prompt}` | Save current worker config as a reusable profile |
| `prompt:update` | `{type, content}` | Update workspace or bullpen prompt (`type`: `workspace` or `bullpen`) |

---

## Files Tab (Workspace File Viewer)

### Tree View (left side of tab)
- Shows the workspace directory tree, excluding `.bullpen/`, `.git/`, `node_modules/`, and other common ignore patterns (respects `.gitignore`).
- Folders are expandable/collapsible.
- Click a file to open it in the viewer area.

### File Viewer (right side of tab)
- **Tab bar** at top: Multiple files can be open. Click tab to switch, "x" to close.
- **View modes by file type:**
  - `.md` files: Rendered markdown preview with toggle to raw edit mode
  - `.txt` files: Plain text editor
  - Source code (`.py`, `.js`, `.ts`, `.css`, `.json`, `.yaml`, etc.): Syntax-highlighted **read-only** view. Use a lightweight library like CodeMirror (available via CDN, no build step) or Prism.js for highlighting. Source editing is intentionally out of scope — agents like Codex may modify workspace files directly, but the Operator reviews and commits those changes via their normal git tools (IDE, `git diff`, etc.).
  - `.html` files: Rendered preview in a **sandboxed iframe** (no script execution) with toggle to syntax-highlighted source view
  - `.pdf` files: Embedded PDF viewer (`<iframe>` or `<embed>`)
  - Images (`.png`, `.jpg`, `.gif`, `.svg`): Inline display
  - Other files: Plain text fallback or "unsupported format" message

> **No-build-step constraint:** Use CDN-hosted libraries (CodeMirror, Prism.js, or Monaco) loaded via `<script>` tags. No npm/webpack/vite.

---

## Initialization and Startup

### Server Startup (`python bullpen.py` or `python -m bullpen`)

1. Accept optional `--workspace` argument (default: current working directory).
2. Check for `.bullpen/` directory in the workspace.
   - If missing: run first-time initialization (create directory structure, copy default profiles, create default config).
   - If present: load existing state.
3. Start Flask + socket.io server on `localhost:5000` (configurable via `--port`).
4. Open default browser to the app URL (optional, `--no-browser` flag to suppress).

### First-Time Initialization
- Create `.bullpen/` directory structure.
- Copy 24 default worker profiles into `.bullpen/profiles/`.
- Create `config.json` with defaults.
- Create empty `layout.json` (no workers placed yet).
- Create empty `workspace_prompt.md` and `bullpen_prompt.md`.
- Create `tasks/`, `teams/`, `logs/` directories.
- Create `.bullpen/.gitignore` containing `logs/` to prevent accidental commit of agent logs.

### Client Startup
1. Connect socket.io to server.
2. Receive `state:init` with full state.
3. Render UI from state.
4. All subsequent changes are event-driven (no polling).

---

## Multi-Client Behavior

Multiple browser tabs/windows can connect simultaneously (single user, multiple views). All clients receive the same socket.io events and stay in sync. Consistency is maintained by the server-side write serialization described below.

---

## Persistence Consistency Rules

### Atomic Writes

All file writes use atomic write-and-rename: write to a temporary file in the same directory, then `os.rename()` to the target path. This prevents partial/corrupt files on crash or concurrent access.

### Server-Side Write Serialization

The server processes all state-mutating socket events through a single-writer queue (Python `asyncio.Queue` or equivalent). Events are applied serially to prevent race conditions between concurrent clients or between Operator actions and agent completions. Read operations are not queued.

This replaces the previous "last-write-wins" strategy. For single-user MVP the performance cost is negligible, and it eliminates an entire class of corruption bugs.

### Startup Reconciliation

On server startup, the system rebuilds derived state from canonical sources:

1. Scan all ticket files in `.bullpen/tasks/` — these are the source of truth for task state.
2. Rebuild worker `task_queue` arrays in `layout.json` by matching `assigned_to` fields. **Queue order is determined by:** ticket `order` field (lexicographic), then `created_at` ascending, then slug alphabetically. This matches the Task Ordering algorithm and produces a deterministic rebuild even if the prior `task_queue` array order is lost.
3. Any worker that was in WORKING state at shutdown is reset to IDLE (the agent process is gone). Its active task is moved to **Blocked** with a "server restart — agent interrupted" notice.
4. Validate all JSON files (`config.json`, `layout.json`, profiles). Log warnings for parse errors and fall back to defaults.

---

## Retry Policy

When an agent process fails (non-zero exit, timeout, or crash), the worker's retry policy governs next steps:

| Step | Behavior |
|------|----------|
| **Record attempt** | Append a history entry to the ticket: `{timestamp, event: "agent_error", detail: {attempt: N, error: stderr_snippet, exit_code}}` |
| **Check retry budget** | If `attempt < max_retries`, proceed to retry. Otherwise, proceed to final failure. |
| **Backoff** | Wait `5 * attempt` seconds before retrying (5s, 10s, 15s). No jitter needed for single-user MVP. |
| **Retry invocation** | Re-invoke with the same prompt. The previous error output is **not** appended to the prompt (to avoid confusing the agent with its own failure). |
| **Final failure** | Append all error details to the ticket's Agent Output section. Move task to **Blocked** column (clear `assigned_to`). Worker returns to IDLE and evaluates queue per activation mode. |

---

## Task Ordering

### Algorithm

Task ordering within kanban columns and worker queues uses **fractional indexing** with base-62 strings, compatible with beans' `order` field.

- Characters: `0-9A-Za-z` (62 values), lexicographically sortable.
- New task at end of column: generate a key after the current last key (e.g., last is `V`, new is `W`).
- Insert between two tasks: generate a midpoint key (e.g., between `V` and `X`, use `W`; between `Va` and `Vb`, use `VaV`).
- Tie-breaker when `order` values collide: sort by `created_at` ascending, then by slug alphabetically.

### Worker Queue Ordering

Tasks in a worker's queue are processed in the order they appear in the `task_queue` array. New tasks assigned via drag-drop are appended to the end. The Operator can reorder by dragging within the worker's task list on the card.

**Reorder durability:** When the server processes a `worker:reorder` event, it updates the `task_queue` array in `layout.json` *and* rewrites the `order` field in each affected ticket file to reflect the new sequence. This ensures startup reconciliation (which rebuilds queues from ticket `order` fields) preserves the Operator's explicit ordering. Order keys are regenerated using fractional indexing between the queue's positional neighbors.

---

## Lifecycle Edge Cases

### Removing a Worker with Active/Queued Tasks
- **Confirmation required:** "This worker has N task(s). Remove worker and return tasks to Assigned column?"
- On confirm: Stop any running agent process. Move all queued tasks back to **Assigned** column (clear `assigned_to`). Remove the worker slot.

### Resizing Grid Smaller than Occupied Slots
- **Blocked if workers would be displaced.** The grid resize dropdown disables options that would eliminate occupied slots. Toast: "Remove workers from slots beyond the new grid size first."

### Loading a Team While Workers Are Active
- **Confirmation required:** "Loading a team will replace all current workers. N worker(s) have active or queued tasks. Stop them and proceed?"
- On confirm: Apply the standard worker-removal rule to every occupied slot: stop any running agent processes, move all queued/assigned/in-progress tasks back to **Assigned** column (clear `assigned_to`). Then clear the grid and load the new team configuration. This is an Operator-initiated layout change, not an error — tasks are paused, not failed.

### Clearing All Workers
- **Confirmation required:** "Remove all workers? N worker(s) have active or queued tasks."
- On confirm: Same as team load — apply worker-removal rule to every occupied slot (stop agents, unassign all tasks), then clear the grid.

### Deleting a Task That Is Assigned or In Progress
- **Confirmation required:** "This task is currently [assigned to / being processed by] {worker name}. Delete it?"
- On confirm: If in progress, stop the agent. Remove from worker queue. Delete the ticket file.

### Server Restart with In-Progress Work
- See Startup Reconciliation above. All WORKING states reset to IDLE; interrupted tasks go to Blocked.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Agent CLI not found on PATH | Toast error on worker start. Worker goes to IDLE. Task stays in Assigned. |
| Agent process exits non-zero | Capture stderr. If retries remain, retry per Retry Policy. Otherwise, move task to Blocked column. Worker returns to IDLE and evaluates queue. |
| Agent process times out | Kill process. Move task to Blocked column (no retry). Append timeout notice to ticket. Worker returns to IDLE and evaluates queue. |
| Socket.io disconnect | Client shows reconnecting indicator. Auto-reconnects. On reconnect, server sends `state:init` to resync. |
| Malformed task ticket file | Log warning. Show ticket in kanban with error badge. Allow Operator to edit/fix. |
| File system errors | Toast error with detail. Log to server console. |

---

## Event Validation and Security

### Socket Event Schema Validation

Every client->server socket event is validated on the server before processing:

- **Schema check:** Each event type has a JSON schema defining required fields, types, and allowed values. Invalid payloads are rejected with a `toast` error event and logged.
- **Payload size limit:** Maximum 1MB per event. Reject and log oversized payloads.
- **Field allowlists:** `task:update` only accepts known frontmatter fields. `worker:configure` only accepts known config keys. Unknown fields are silently stripped (not rejected — this provides forward compatibility when client and server versions are briefly mismatched during updates).
- **Per-field constraints:** `title` max 200 chars, `description` max 50,000 chars, `tags` max 20 items of 50 chars each, `expertise_prompt` max 100,000 chars, `slug` max 80 chars. Enum fields (`status`, `type`, `priority`, `activation`, `agent`) reject values outside their defined sets. Violations are rejected with a `toast` error.
- **Slot bounds checking:** All `slot` references are validated against the current grid dimensions.
- **ID validation:** Task IDs and profile IDs are validated against allowed characters (alphanumeric, hyphens) and checked for existence before mutation.

### Filesystem Boundary Enforcement

- All file operations resolve paths via `os.path.realpath()` and verify the result is within the workspace root or `.bullpen/` directory.
- Symlinks pointing outside the workspace are not followed in the Files tab.
- Task ticket IDs/slugs are validated against a strict regex (`[a-z0-9-]+`) to prevent path traversal via crafted slugs.

### Content Sanitization

- **Markdown rendering:** Use a sanitizing renderer (e.g., `markdown-it` with default escaping, no `html` option). Strip all raw HTML tags, `<script>`, event handlers (`onclick`, etc.), and `javascript:` URLs from rendered output. This applies to task ticket rendering, markdown preview in the Files tab, and agent output display on worker cards.
- **HTML file preview:** Render inside a fully sandboxed iframe: `<iframe sandbox srcdoc="...">`. No sandbox exceptions (`allow-same-origin`, `allow-scripts`, etc.) are granted. This is a passive preview — CSS and static content render, but scripts, forms, and origin access are all blocked.
- **Agent output display:** Agent output on worker cards is rendered as preformatted text (`<pre>`), not as HTML or markdown, to eliminate injection risk from agent responses.

### Log Sensitivity

- The `.bullpen/logs/` directory is included in the default `.bullpen/.gitignore` to prevent accidental commit of agent logs that may contain source code or secrets.
- Log files are rotated: retain only the last 100 log files per worker slot. Older logs are deleted on server startup.
- Prompts logged to disk are truncated to the first 500 characters to reduce secret exposure surface.

---

## MVP Scope Boundaries

### In Scope
- Single workspace, single bullpen instance
- Full kanban with drag-and-drop
- Worker card grid with configuration
- Agent invocation for Claude and Codex via CLI
- Real-time output streaming to worker cards
- File-based persistence in `.bullpen/`
- Basic file viewer with syntax highlighting
- Socket.io for all client-server communication
- 24 default worker profiles
- Team save/load

### Explicitly Out of Scope (Future)
- **Operator Inbox**: A dedicated view for tasks routed back to the Operator for decisions. (For MVP, tasks go to Review column instead.)
- **Workflow routing**: Complex multi-step pipelines where workers chain automatically beyond simple disposition. (MVP supports single-hop disposition only.)
- **Team In A Can**: One-click deployment of pre-configured teams with kanban columns and prompts tuned for specific workflows (e.g., "PR Review Team", "Feature Development Team").
- **Select/copy/paste in the bullpen**: Multi-select worker cards and duplicate or move them as a group.
- **Multi-user / authentication**: No login, no user identity, no permissions.
- **Remote agents / API-based agents**: All agents are local CLI processes.
- **Undo/redo**: No undo for kanban or bullpen actions.
- **Advanced file editing**: The file viewer is primarily for viewing. Editing is limited to markdown and plain text. Source code modifications happen through agents (e.g., Codex `--auto-edit`) and are reviewed via external git tools, not in the bullpen UI.

---

## Test Strategy and Acceptance Gates

### Test Stack
- **Backend unit/integration:** `pytest` + `pytest-asyncio` + Flask-SocketIO test client.
- **Contract tests:** JSON schema validation tests for every socket event payload (both directions).
- **E2E/UI:** Playwright driving browser against a running server with a mock agent adapter (returns canned output after a short delay).
- **Fixtures:** Temp workspace factory that creates `.bullpen/` directory trees with sample task/profile/layout files for each test.

### Minimum Test Matrix

| Area | What to Test |
|------|-------------|
| **State transitions** | All worker state machine paths: IDLE->WORKING->IDLE, retry loops, stop/timeout, manual vs auto-advance, QUEUED->WORKING on manual start. Task outcomes: success->disposition, error->Blocked column, timeout->Blocked column, stop->Assigned column. |
| **Queue-kanban consistency** | Reassign during WORKING, delete during WORKING, drag to different column while queued, startup reconciliation from dirty state. |
| **Concurrency** | Dual-client conflicting edits, rapid drag-drop, simultaneous worker completions writing to same ticket, event serialization correctness. |
| **Persistence** | Atomic write correctness (kill server mid-write, verify no corruption), startup recovery, malformed file handling. |
| **Security** | XSS payloads in ticket title/body/agent output, HTML file preview sandboxing, event payload fuzzing (oversized, missing fields, path traversal slugs), symlink escape in Files tab. |
| **Agent adapter** | stdout/stderr capture, timeout behavior, non-zero exit handling, truncation, stdin pipe delivery, stop signal handling (SIGTERM then SIGKILL). |
| **Beans compatibility** | Ingest beans-format tickets missing bullpen extension fields, verify defaults applied, verify round-trip (read-write-read preserves beans fields). |
| **Schema compatibility** | Load `.bullpen/` directories with missing optional fields, extra unknown fields, and older config shapes. Verify graceful defaults and no data loss. Maintain a fixture set of "v1" file shapes to catch regressions as schemas evolve. |

### Release Gates
- All tests pass. No skipped security or state-transition tests.
- E2E happy path: create task -> assign to worker -> agent runs -> output captured -> review -> done.
- E2E error path: agent fails -> retry -> blocked -> operator reassigns.
- Deterministic replay of recorded event traces in CI.

---

## Open Issues for Discussion

*Previously resolved: CLI stability (Agent Adapter Layer), ticket size growth (50KB cap), git integration (Operator workflow), concurrent workers (no artificial limit), Codex stdin (adapter capability probing).*

1. **Prompt file format**: Workspace and bullpen prompts are plain markdown. Should they support template variables (e.g., `{{project_name}}`, `{{file_list}}`)? **Decision:** Plain text for MVP. Template expansion is a natural v2 feature.

2. **Git integration**: Leave committing `.bullpen/` state to the Operator's normal git workflow. `.bullpen/logs/` is gitignored by default (via `.bullpen/.gitignore`). Other `.bullpen/` contents (tasks, config, layout) are committable.

3. **Concurrent worker limit**: No artificial limit for MVP. Each agent is a separate OS process. The Operator manages their own machine capacity. Consider adding a configurable max-concurrent-agents setting in v2.

4. **Agent adapter discovery**: Should adapters auto-detect which CLIs are installed at startup and disable unavailable agents in the UI? **Recommendation:** Yes — call `which claude` / `which codex` at startup and gray out unavailable agents in the model selector.
