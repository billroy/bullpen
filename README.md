# Bullpen

An AI agent team manager. Configure workers on a grid, create task tickets, assign work, and let CLI agents (Claude, Codex) execute autonomously with retry logic and output streaming.

## Quick Start

```bash
pip install flask flask-socketio simple-websocket
python3 bullpen.py --workspace /path/to/your/project
```

This opens a browser at `http://localhost:5000`. The workspace directory is where your agents will operate.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--workspace` | current directory | Project directory for agents to work in |
| `--port` | 5000 | Server port |
| `--host` | 127.0.0.1 | Bind address (use `0.0.0.0` to expose on LAN) |
| `--no-browser` | off | Don't auto-open the browser |

By default the server only accepts connections from localhost. CORS is restricted to the same origin.

## Features

- **Kanban board** -- drag-and-drop task management with customizable columns (Inbox, Assigned, In Progress, Review, Done)
- **Worker grid** -- configurable grid of AI agent slots; drag tasks onto workers to assign them
- **Agent execution** -- workers invoke Claude or Codex CLI tools in subprocesses with prompt assembly, retry on failure, and output capture
- **File browser & editor** -- browse workspace files with syntax highlighting, markdown preview, image/PDF viewing, HTML sandbox preview, and an in-browser editor with find/replace
- **Multi-project** -- register multiple project directories, switch between them, with per-workspace state and activity badges
- **Scheduling** -- workers can activate on a time schedule (at a specific time, or on an interval) or on queue events; pause/unpause individual workers
- **Auto-commit & auto-PR** -- optionally commit agent output on success and open a pull request automatically
- **Worktrees** -- agents can work in isolated git worktrees per task to avoid conflicts
- **Worker handoff** -- chain workers by setting disposition to route completed tasks to the next worker
- **Profiles** -- 24 built-in worker profiles (feature-architect, code-reviewer, test-writer, etc.) with customizable expertise prompts; create custom profiles
- **Teams** -- save and restore grid configurations
- **Light/dark theme** -- toggle between dark and light themes
- **Context menu** -- right-click worker cards for actions (configure, start, stop, duplicate, remove)
- **Real-time sync** -- Socket.IO keeps all connected clients in sync, scoped per workspace
- **Persistence** -- tasks stored as frontmatter markdown files in `.bullpen/tasks/`, layout and config as JSON
- **Task archiving** -- archive completed tasks to keep the board clean

## Architecture

- **Backend**: Flask + Flask-SocketIO (threading async mode)
- **Frontend**: Vue 3 via CDN (no build step, no npm)
- **Transport**: Socket.IO for real-time events, REST for file serving
- **Storage**: flat files in `.bullpen/` under the workspace

```
bullpen.py              # Entry point
server/
  app.py                # Flask app factory, routes, startup reconciliation
  events.py             # Socket.IO event handlers (write-locked)
  tasks.py              # Task CRUD, slug generation, fractional indexing
  workers.py            # Worker state machine, subprocess execution, auto-commit/PR
  persistence.py        # Atomic writes, custom frontmatter parser
  validation.py         # Input validation and sanitization
  profiles.py           # Profile management
  teams.py              # Team save/load
  scheduler.py          # Time-based and interval-based worker activation
  workspace_manager.py  # Multi-project registry and workspace state
  agents/               # Agent adapter layer (Claude, Codex)
static/
  index.html            # CDN script tags with SRI (Vue 3, Socket.IO, Prism, markdown-it)
  app.js                # Vue app setup, state management
  style.css             # Light/dark theme
  components/           # Vue components (KanbanTab, BullpenTab, FilesTab, etc.)
profiles/               # 24 built-in worker profile JSON files
tests/                  # 198 tests (pytest)
```

## How It Works

1. **Create tasks** in the Inbox via the left pane or Kanban board
2. **Add workers** to the grid by clicking empty slots and selecting a profile
3. **Assign tasks** by dragging them from the Inbox onto a worker card, or queue multiple tasks
4. **Start the worker** -- it assembles a prompt (workspace context + expertise + task body), invokes the CLI agent, and streams output back
5. **On completion**, the worker optionally auto-commits, opens a PR, and routes the task based on its disposition (Review, Done, or hand off to another worker)
6. **On failure**, the worker retries with backoff, then moves the task to Blocked
7. **Scheduled workers** can activate on a timer (specific time or interval) to process queued tasks or create their own ephemeral tasks

## Supported Agents

| Agent | CLI Tool | Notes |
|-------|----------|-------|
| Claude | `claude` | Uses `--print --dangerously-skip-permissions` |
| Codex | `codex` | Uses `--approval-mode full-auto --quiet` |

The agent must be installed and available on your PATH.

## Running Tests

```bash
pip install pytest
python3 -m pytest tests/
```
