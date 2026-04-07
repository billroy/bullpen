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
| `--no-browser` | off | Don't auto-open the browser |

## Features

- **Kanban board** -- drag-and-drop task management with customizable columns (Inbox, Assigned, In Progress, Review, Done)
- **Worker grid** -- configurable grid of AI agent slots; drag tasks onto workers to assign them
- **Agent execution** -- workers invoke Claude or Codex CLI tools in subprocesses with prompt assembly, retry on failure, and output capture
- **File browser** -- browse workspace files with syntax highlighting (Prism.js), markdown preview (markdown-it), image/PDF viewing, and HTML sandbox preview
- **Profiles** -- 24 built-in worker profiles (feature-architect, code-reviewer, test-writer, etc.) with customizable expertise prompts
- **Teams** -- save and restore grid configurations
- **Real-time sync** -- Socket.IO keeps all connected clients in sync
- **Persistence** -- tasks stored as frontmatter markdown files in `.bullpen/tasks/`, layout and config as JSON

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
  workers.py            # Worker state machine, subprocess execution
  persistence.py        # Atomic writes, custom frontmatter parser
  validation.py         # Input validation and sanitization
  profiles.py           # Profile management
  teams.py              # Team save/load
  agents/               # Agent adapter layer (Claude, Codex)
static/
  index.html            # CDN script tags (Vue 3, Socket.IO, Prism, markdown-it)
  app.js                # Vue app setup, state management
  style.css             # Dark theme
  components/           # Vue components (KanbanTab, BullpenTab, FilesTab, etc.)
profiles/               # 24 built-in worker profile JSON files
tests/                  # 147 tests (pytest)
```

## How It Works

1. **Create tasks** in the Inbox via the left pane or Kanban board
2. **Add workers** to the grid by clicking empty slots and selecting a profile
3. **Assign tasks** by dragging them from the Inbox onto a worker card
4. **Start the worker** -- it assembles a prompt (workspace context + expertise + task body), invokes the CLI agent, and streams output back
5. **On completion**, the worker routes the task based on its disposition setting (Review, Done, or next worker)
6. **On failure**, the worker retries with backoff, then moves the task to Blocked

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
