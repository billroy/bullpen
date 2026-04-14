# Bullpen

An AI agent team manager. Configure workers on a grid, create task tickets, assign work, and let CLI agents (Claude, Codex, Gemini) execute autonomously with retry logic and real-time output streaming. Includes an MCP server so supported agents can manage tickets directly from the conversation.

## Quick Start

```bash
pip install -r requirements.txt
python3 bullpen.py --workspace /path/to/your/project
```

This opens a browser at `http://localhost:5000`. The workspace directory is where your agents will operate.

### AI CLI Prerequisites

Bullpen runs provider CLIs locally. Install and authenticate each provider you want to use:

- **Claude Code CLI**
  - Install/setup: https://code.claude.com/docs/en/setup
  - Authentication: https://code.claude.com/docs/en/authentication
- **Codex CLI**
  - Installation: https://github.com/openai/codex/blob/main/docs/install.md
  - Authentication: https://github.com/openai/codex/blob/main/docs/authentication.md
- **Gemini CLI**
  - Installation: https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/index.md
  - Authentication: https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.md

Only authenticated providers are usable in Bullpen. If you plan to use all three agents, complete login/auth setup in all three CLIs first.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--workspace` | current directory | Project directory for agents to work in |
| `--port` | `$PORT` or `5000` | Server port (`PORT` env var is respected for Sprite/hosted deploys) |
| `--host` | 127.0.0.1 | Bind address (network-exposed binds require auth to be enabled) |
| `--no-browser` | off | Don't auto-open the browser |
| `--websocket-debug` / `--no-websocket-debug` | off | Enable/disable Socket.IO and Engine.IO packet/activity logging |
| `--set-password [USERNAME]` | — | Interactively set/update user passwords (repeatable for multiple users); can be combined with `--delete-user`; exits after applying changes |
| `--delete-user USERNAME` | — | Remove configured login users (repeatable); can be combined with `--set-password`; exits after applying changes |
| `--bootstrap-credentials` | off | Create initial credentials from `BULLPEN_BOOTSTRAP_USER` (default `admin`) and `BULLPEN_BOOTSTRAP_PASSWORD`, then exit (idempotent if users already exist) |

By default the server only accepts connections from localhost. Socket.IO accepts same-origin, localhost, and trusted tunnel origins (including `*.ngrok*` and `*.sprites.app`) so reverse proxies and tunneled URLs work without wildcard CORS; authentication remains the primary access control.
If you bind to a non-loopback host (for example `0.0.0.0`), Bullpen requires authentication credentials to be configured first.
For production/TLS deployments (including Sprites), set `BULLPEN_PRODUCTION=1` so secure cookies and forwarded-proxy headers are handled correctly.

## Features

- **Kanban board** -- drag-and-drop ticket management with user-configurable columns (add, remove, rename, reorder); drag tickets between columns or onto workers
- **List view** -- switchable list view for the Tickets tab with sortable columns, full-text search, priority/status/type filters, timestamped Created column, and token-consumption display
- **Worker grid** -- configurable grid of AI agent slots; drag tickets onto workers to assign them
- **Agent execution** -- workers invoke Claude, Codex, or Gemini CLI tools in subprocesses with prompt assembly, retry on failure, and real-time output streaming (structured stream parsing for Claude/Codex)
- **Worker Focus Mode** -- click a running worker to see live agent output streamed in real time
- **Live Agent Chat** -- interactive chat tabs for Claude, Codex, and Gemini with provider/model selectors, streaming responses, add/close chat sessions, stop button, and automatic chat logging to tickets
- **File browser & editor** -- browse workspace files (including `.bullpen/`) with syntax highlighting, markdown preview with source-mode syntax highlighting, image/PDF viewing, HTML sandbox preview, and an in-browser editor with find/replace; clicking `.html` files opens them in the default browser
- **Commits tab** -- browse the git commit log for the workspace with full commit descriptions
- **Commit diff viewer** -- click a commit row to open its full patch in a modal
- **Multi-project** -- register multiple project directories, switch between them, with per-workspace state and activity badges; clone new projects directly from a Git URL via the Projects menu
- **Inter-project worker transfer** -- copy or move workers (optionally with profile copy) between registered workspaces
- **Scheduling** -- workers can activate on a time schedule (at a specific time, or on an interval) or on queue events; pause/unpause individual workers
- **Auto-commit & auto-PR** -- optionally commit agent output on success and open a pull request automatically
- **Worktrees** -- agents can work in isolated git worktrees per task to avoid conflicts
- **Worker handoff** -- chain workers by setting disposition to route completed tasks to the next worker
- **Profiles** -- 24 built-in worker profiles (feature-architect, code-reviewer, test-writer, etc.) with customizable expertise prompts; create custom profiles
- **Teams** -- save and restore grid configurations
- **Ticket editing** -- edit ticket title, tags, and description inline; Cmd+Enter to save
- **Token tracking** -- per-ticket token consumption tracking plus provider/model usage metadata, displayed in list view and ticket details
- **Worker roster queue count** -- left-pane worker roster shows queued workload while workers are in `WORKING` state
- **Ambient sounds** -- 18 synthesized ambient soundscapes (Server Room, Forest Rain, Deep Space, War Room, etc.) generated via the Web Audio API with per-workspace volume control
- **Light/dark theme** -- toggle between dark and light themes
- **Context menu** -- right-click worker cards for actions (configure, start, stop, duplicate, remove)
- **Real-time sync** -- Socket.IO keeps all connected clients in sync, scoped per workspace, with origin checks that allow localhost/same-origin and trusted tunnel domains (including `.sprites.app`)
- **Persistence** -- tickets stored as frontmatter markdown files in `.bullpen/tasks/`, layout and config as JSON
- **Ticket archiving** -- archive completed tickets to keep the board clean
- **Authentication** -- optional local username/password login (supports multiple users; see [Authentication](#authentication) below)
- **MCP server** -- expose ticket management tools to supported agents via JSON-RPC stdio (see [MCP Integration](#mcp-integration) below)
- **Cross-platform** -- runs on macOS, Linux, and Windows

## Deployment Notes

- **Sprite/tunnel origin trust** -- Socket.IO origin checks include trusted tunnel suffixes including `.sprites.app` for Fly.io Sprite URLs.
- **Sprite service port compatibility** -- Bullpen supports `PORT` env var fallback so hosted runtimes that expect port `8080` work without custom patching.
- **Production TLS mode** -- setting `BULLPEN_PRODUCTION=1` enables secure session cookies and proxy header handling for HTTPS deployments.
- **One-command Sprite install** -- `deploy-sprite.sh` automates Sprite provisioning, auth bootstrap, service creation, and URL publication.

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
  auth.py               # Optional multi-user authentication
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
  agents/               # Agent adapter layer (Claude, Codex, Gemini)
static/
  index.html            # CDN script tags with SRI (Vue 3, Socket.IO, Prism, markdown-it)
  login.html            # Login page (served publicly when auth is enabled)
  app.js                # Vue app setup, state management
  style.css             # Light/dark theme
  components/           # Vue components (KanbanTab, WorkerCard, FilesTab, LiveAgentChatTab, etc.)
profiles/               # 24 built-in worker profile JSON files
tests/                  # 465 tests passing (pytest)
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
9. **Chat directly** with Claude, Codex, or Gemini via the Live Agent Chat tab, with conversations logged to tickets
10. **Open additional chat tabs** as needed to run parallel conversations with separate session histories

## Supported Agents

| Agent | CLI Tool | Notes |
|-------|----------|-------|
| Claude | `claude` | Real-time streaming via stream-json |
| Codex | `codex` | GPT-5 family models, stderr streaming |
| Gemini | `gemini` | Gemini CLI prompt execution with stdout streaming |

Each agent CLI must be installed, available on your PATH, and authenticated with its provider before Bullpen can use it.

## Authentication

Bullpen supports optional local username/password authentication. Multiple users can be configured in the global `.env` file. When no credentials are configured, Bullpen runs wide-open with no login screen — ideal for localhost development.

### Enabling auth

```bash
python3 bullpen.py --set-password admin
python3 bullpen.py --set-password alice --set-password bob
```

You will be prompted for a password (and username if omitted). Credentials are written as password hashes to `~/.bullpen/.env` (mode 600). Restart the server to apply. On startup Bullpen prints:

```
Bullpen auth: ENABLED (2 user(s), primary=admin)

Network-exposed binds (for example `--host 0.0.0.0`) are only allowed when auth is enabled.
```

To delete users:

```bash
python3 bullpen.py --delete-user alice
python3 bullpen.py --delete-user alice --delete-user bob
python3 bullpen.py --set-password admin --delete-user old-admin
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
| `list_tickets_by_title` | List tickets by approximate title match |
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

## License

This project is licensed under the MIT License. See `LICENSE.md`.

## Fly.io Sprite Deployment (Experimental)

Use the one-command deploy script:

```bash
curl -sL https://raw.githubusercontent.com/billroy/bullpen/main/deploy-sprite.sh | bash
```

The script prompts for Sprite name, admin username/password, then:
- Creates (or reuses) the Sprite
- Clones/updates Bullpen and installs requirements
- Ensures `node` and `rg` (ripgrep) are installed on the Sprite
- Bootstraps Bullpen credentials non-interactively
- Configures production mode (`BULLPEN_PRODUCTION=1`)
- Creates a background service on port `8080`
- Makes the Sprite URL public and prints the actual HTTPS URL
- Performs a short health check before exiting

See detailed deployment docs:
- `docs/sprite.md` (one-command deploy flow and implementation notes)
- `docs/fly-config.md` (Sprite architecture, hibernation behavior, production details)
