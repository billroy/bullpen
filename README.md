# Bullpen

An AI agent team manager. Configure workers on a grid, create task tickets, assign work, and let CLI agents (Claude, Codex) execute autonomously with retry logic and real-time output streaming. Includes an MCP server so supported agents can manage tickets directly from the conversation.

## Quick Start

```bash
pip install -r requirements.txt
python3 bullpen.py --workspace /path/to/your/project
```

This opens a browser at `http://localhost:5000`. The workspace directory is where your agents will operate.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--workspace` | current directory | Project directory for agents to work in |
| `--port` | 5000 | Server port |
| `--host` | 127.0.0.1 | Bind address (network-exposed binds require auth to be enabled) |
| `--no-browser` | off | Don't auto-open the browser |
| `--set-password` | — | Interactively set login credentials and exit |

By default the server only accepts connections from localhost. CORS is restricted to the same origin.
If you bind to a non-loopback host (for example `0.0.0.0`), Bullpen requires authentication credentials to be configured first.

## Features

- **Kanban board** -- drag-and-drop ticket management with user-configurable columns (add, remove, rename, reorder); drag tickets between columns or onto workers
- **List view** -- switchable list view for the Tickets tab with sortable columns and token-consumption display
- **Worker grid** -- configurable grid of AI agent slots; drag tickets onto workers to assign them
- **Agent execution** -- workers invoke Claude or Codex CLI tools in subprocesses with prompt assembly, retry on failure, and real-time output streaming (stream-json for Claude)
- **Worker Focus Mode** -- click a running worker to see live agent output streamed in real time
- **Live Agent Chat** -- interactive chat tab for Claude and Codex with provider/model selectors, streaming responses, conversation persistence across tab switches, stop button, and automatic chat logging to tickets
- **File browser & editor** -- browse workspace files (including `.bullpen/`) with syntax highlighting, markdown preview with source-mode syntax highlighting, image/PDF viewing, HTML sandbox preview, and an in-browser editor with find/replace
- **Commits tab** -- browse the git commit log for the workspace with full commit descriptions
- **Multi-project** -- register multiple project directories, switch between them, with per-workspace state and activity badges
- **Scheduling** -- workers can activate on a time schedule (at a specific time, or on an interval) or on queue events; pause/unpause individual workers
- **Auto-commit & auto-PR** -- optionally commit agent output on success and open a pull request automatically
- **Worktrees** -- agents can work in isolated git worktrees per task to avoid conflicts
- **Worker handoff** -- chain workers by setting disposition to route completed tasks to the next worker
- **Profiles** -- 24 built-in worker profiles (feature-architect, code-reviewer, test-writer, etc.) with customizable expertise prompts; create custom profiles
- **Teams** -- save and restore grid configurations
- **Ticket editing** -- edit ticket title, tags, and description inline; Cmd+Enter to save
- **Token tracking** -- per-ticket token consumption tracking displayed in list view and ticket details
- **Light/dark theme** -- toggle between dark and light themes
- **Context menu** -- right-click worker cards for actions (configure, start, stop, duplicate, remove)
- **Real-time sync** -- Socket.IO keeps all connected clients in sync, scoped per workspace
- **Persistence** -- tickets stored as frontmatter markdown files in `.bullpen/tasks/`, layout and config as JSON
- **Ticket archiving** -- archive completed tickets to keep the board clean
- **Authentication** -- optional single-user login (see [Authentication](#authentication) below)
- **MCP server** -- expose ticket management tools to supported agents via JSON-RPC stdio (see [MCP Integration](#mcp-integration) below)
- **Cross-platform** -- runs on macOS, Linux, and Windows

## Architecture

- **Backend**: Flask + Flask-SocketIO (threading async mode)
- **Frontend**: Vue 3 via CDN (no build step, no npm)
- **Transport**: Socket.IO for real-time events, REST for file serving
- **Storage**: flat files in `.bullpen/` under the workspace
- **MCP**: stdio JSON-RPC server for agent ticket-tool integration

```
bullpen.py              # Entry point
server/
  app.py                # Flask app factory, routes, startup reconciliation
  auth.py               # Optional single-user authentication
  events.py             # Socket.IO event handlers (write-locked)
  tasks.py              # Task CRUD, slug generation, fractional indexing
  workers.py            # Worker state machine, subprocess execution, auto-commit/PR
  persistence.py        # Atomic writes, custom frontmatter parser
  validation.py         # Input validation and sanitization
  profiles.py           # Profile management
  teams.py              # Team save/load
  scheduler.py          # Time-based and interval-based worker activation
  workspace_manager.py  # Multi-project registry and workspace state
  mcp_tools.py          # MCP stdio server (JSON-RPC ticket tools)
  agents/               # Agent adapter layer (Claude, Codex)
static/
  index.html            # CDN script tags with SRI (Vue 3, Socket.IO, Prism, markdown-it)
  login.html            # Login page (served publicly when auth is enabled)
  app.js                # Vue app setup, state management
  style.css             # Light/dark theme
  components/           # Vue components (KanbanTab, WorkerCard, FilesTab, LiveAgentChatTab, etc.)
profiles/               # 24 built-in worker profile JSON files
tests/                  # 288 tests (pytest)
```

## How It Works

1. **Create tickets** in the Inbox via the left pane quick-create input or the Kanban board
2. **Add workers** to the grid by clicking empty slots and selecting a profile
3. **Assign tickets** by dragging them from the Inbox onto a worker card, or queue multiple tickets
4. **Start the worker** -- it assembles a prompt (workspace context + expertise + ticket body), invokes the CLI agent, and streams output in real time
5. **Monitor progress** -- click a running worker to open the Focus View with live agent output
6. **On completion**, the worker optionally auto-commits, opens a PR, and routes the ticket based on its disposition (Review, Done, or hand off to another worker)
7. **On failure**, the worker retries with backoff, then moves the ticket to Blocked
8. **Scheduled workers** can activate on a timer (specific time or interval) to process queued tickets or create their own ephemeral tickets
9. **Chat directly** with Claude or Codex via the Live Agent Chat tab, with conversations logged to tickets

## Supported Agents

| Agent | CLI Tool | Notes |
|-------|----------|-------|
| Claude | `claude` | Real-time streaming via stream-json |
| Codex | `codex` | GPT-5 family models, stderr streaming |

The agent must be installed and available on your PATH.

## Authentication

Bullpen supports optional single-user username/password authentication. When no credentials are configured, Bullpen runs wide-open with no login screen — ideal for localhost development.

### Enabling auth

```bash
python3 bullpen.py --set-password
```

You will be prompted for a username and password. The hashed credential is written to `~/.bullpen/.env` (mode 600). Restart the server to apply. On startup Bullpen prints:

```
Bullpen auth: ENABLED (user=admin)

Network-exposed binds (for example `--host 0.0.0.0`) are only allowed when auth is enabled.
```

When auth is enabled, unauthenticated browser requests are redirected to `/login`, XHR requests receive a 401, and Socket.IO connections without a valid session are rejected. Static assets needed by the login page (`login.html`, `style.css`, `favicon.ico`) remain public.

### Disabling auth

Delete `~/.bullpen/.env` and restart. Bullpen will report auth disabled and all routes become open again.

### Deploying remotely

When exposing Bullpen outside localhost, put TLS in front (nginx, Caddy, Cloudflare Tunnel, etc.) so the session cookie is never transmitted in plaintext. See [docs/login.md](docs/login.md) for full details on CSRF protection, cookie settings, and the env file format.

## MCP Integration

Bullpen ships an MCP (Model Context Protocol) stdio server that lets supported agent sessions manage tickets directly from the conversation. The server exposes tools for creating, listing, and updating tickets.

### Available MCP tools

| Tool | Description |
|------|-------------|
| `create_ticket` | Create a new ticket with title, description, tags, and status |
| `list_tickets` | List tickets, optionally filtered by status |
| `list_tasks` | Alias for `list_tickets` |
| `update_ticket` | Update a ticket's status, title, or description |

### How it works

Claude and Codex adapters spawn `server/mcp_tools.py` as a child process and communicate via stdin/stdout JSON-RPC 2.0 with `Content-Length` framing. The MCP server connects to the running Bullpen instance via Socket.IO to perform ticket operations.

When auth is enabled, the MCP server authenticates using a shared token that Bullpen writes to each workspace's `.bullpen/config.json` on startup — no manual configuration needed.

### Caveats

The MCP server communicates exclusively over stdout. Any stray `print()` call or stdout write from a dependency will corrupt the JSON-RPC framing. Debug output must go to `sys.stderr`.

## Running Tests

```bash
pip install -r requirements.txt
python3 -m pytest tests/
```
