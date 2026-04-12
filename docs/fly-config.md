# Deploying Bullpen on a Fly.io Sprite

Status: **DRAFT** | Last verified: 2026-04-12

## What's a Sprite?

A Sprite is a persistent Linux microVM on Fly.io's Firecracker infrastructure.
It is not a container. There is no Dockerfile, no `fly.toml`, no image build
step. You get a real Ubuntu box with 100 GB persistent storage, preinstalled
Python/Git/Node/Go, root access, and a public HTTPS URL. When idle it
hibernates (no compute charges); when hit with a request or CLI command it wakes
in under a second.

This is the correct deployment target for Bullpen. The previous draft of this
document proposed a Fly Machine with Docker, gunicorn, and a browser-only
subset of the app. That was wrong on every count. A Sprite runs the full
application -- agents, UI, git operations, file browser, everything -- because
it's a real Linux computer, not a locked-down container.

## Why the Full App Works on a Sprite

The old doc claimed agents couldn't run remotely because "the MCP stdio server
can't reach a remote Fly Machine." On a Sprite this is irrelevant:

- Claude Code CLI can be installed on the Sprite (Node.js is preinstalled,
  `npm install -g @anthropic-ai/claude-code` works).
- The MCP stdio server communicates over stdin/stdout with the Claude process.
  Both run on the same machine. There is no network hop.
- Git is preinstalled. Repos can be cloned, edited, committed, and pushed
  directly from the Sprite filesystem.
- The Bullpen server binds to port 8080, which the Sprite exposes at
  `https://<name>.sprites.app` with automatic TLS.

The only thing that does NOT survive hibernation is in-memory state (running
processes, open WebSocket connections). Services (see below) handle process
restart. Clients reconnect automatically via Socket.IO.

## What Actually Needs to Change in the Code

Surprisingly little. Most of the 11-step plan in the old doc was solving
problems that don't exist on a Sprite (Dockerfile, fly.toml, gunicorn, pip
pinning, entrypoint.sh). Here's what's real:

### 1. `PORT` env var support

The Sprite URL routes to port 8080. Bullpen currently hardcodes `--port 5000`.
Add a fallback in `bullpen.py`:

```python
default=int(os.environ.get("PORT", 5000))
```

One line. Not a PR.

### 2. Bind to `0.0.0.0`

Bullpen defaults to `127.0.0.1`. The Sprite's HTTPS proxy connects to the
process from outside the loopback. The server must bind `0.0.0.0`. This means
`require_auth_for_network_bind` will fire, which is correct -- auth must be
enabled on a public-facing instance.

### 3. `SESSION_COOKIE_SECURE=True` when behind TLS

The Sprite URL is HTTPS. Session cookies need the `Secure` flag or browsers
will refuse to send them. Check for an env var:

```python
SESSION_COOKIE_SECURE=os.environ.get("BULLPEN_PRODUCTION") == "1",
```

### 4. Trusted origin for `.sprites.app`

Add `".sprites.app"` to `_TRUSTED_TUNNEL_SUFFIXES` in `server/app.py` so
Socket.IO CORS checks pass for the Sprite's public URL.

### 5. Non-interactive credential bootstrap

`--set-password` uses `getpass`, which requires a TTY. For headless setup via
`sprite exec`, support env-var-based bootstrap:

```
BULLPEN_BOOTSTRAP_USER=admin
BULLPEN_BOOTSTRAP_PASSWORD=<password>
```

On startup, if both are set and no credentials exist, hash the password and
write it. This lets you do:

```
sprite exec --env BULLPEN_BOOTSTRAP_USER=admin \
            --env BULLPEN_BOOTSTRAP_PASSWORD=hunter2 \
            -- python bullpen.py --setup-and-exit
```

Or just `sprite console` and run `--set-password` interactively (you have a
TTY in the console).

### 6. `/healthz` endpoint (optional)

Not strictly required -- Sprites don't have Fly-style health checks that gate
traffic. But it's useful for uptime monitoring. Low priority.

## Deployment Procedure

### One-time setup

```bash
# Install the Sprite CLI
curl https://sprites.dev/install.sh | bash
sprite login

# Create the Sprite
sprite create bullpen
sprite use bullpen

# Shell in
sprite console
```

Inside the Sprite console:

```bash
# Clone the repo
cd ~
git clone https://github.com/<you>/bullpen.git
cd bullpen

# Install Python deps
pip install -r requirements.txt

# Set up auth (interactive -- you have a TTY here)
python bullpen.py --set-password admin

# Test it
PORT=8080 python bullpen.py --host 0.0.0.0 --no-browser
# Ctrl+C when satisfied
```

### Create a persistent service

Still inside the Sprite console:

```bash
sprite-env services create bullpen \
  --cmd python \
  --args "bullpen.py --host 0.0.0.0 --port 8080 --no-browser"
```

This service auto-restarts when the Sprite wakes from hibernation.

### Make it public

```bash
sprite url update --auth public
```

The app is now live at `https://bullpen.sprites.app`.

To restrict access to org members only:

```bash
sprite url update --auth sprite
```

### Install Claude Code (for agents)

```bash
npm install -g @anthropic-ai/claude-code
```

Claude Code persists across hibernation because npm global installs go to the
persistent filesystem. The Bullpen agent adapter (`server/agents/claude_adapter.py`)
will find it via `shutil.which("claude")`.

You'll need to set `ANTHROPIC_API_KEY` in the environment. Do this inside the
Sprite so it persists:

```bash
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc
```

### Checkpoint after setup

```bash
sprite checkpoint create --comment "bullpen fully configured"
```

If anything goes sideways later: `sprite restore <version>`.

## What Hibernation Means for Bullpen

When the Sprite goes idle (no HTTP requests, no active CLI sessions), it
hibernates. This means:

- **The Flask process stops.** The service definition ensures it restarts on
  wake.
- **WebSocket connections drop.** Socket.IO clients reconnect automatically.
  The frontend already handles this.
- **In-flight agent runs are killed.** Any Claude Code process running a task
  will be terminated. On restart, Bullpen's `reconcile()` function
  (`server/app.py`) resets workers from "working" to "idle" and moves their
  tasks back to "blocked." This is the existing crash-recovery path and it
  works correctly here.
- **The filesystem is intact.** All repos, tickets, config, agent output,
  credentials -- everything under `/home/sprite/bullpen/.bullpen/` and the
  workspace -- survives.
- **Wake takes <1 second.** The first HTTP request or `sprite exec` triggers
  it.

For a team dashboard that's checked a few times a day, hibernation is ideal.
For long-running agent tasks, you'd want to keep the Sprite awake by ensuring
there's activity (or just accept that interrupted tasks resume on wake).

## Updating the App

```bash
sprite console
cd ~/bullpen
git pull
sprite-env services restart bullpen
```

Or from your local machine:

```bash
sprite exec -- bash -c "cd ~/bullpen && git pull"
sprite exec -- sprite-env services restart bullpen
```

## Cost

- Compute: billed per CPU-second and memory-second while awake. A 1-CPU /
  512 MB Sprite running 8 hours/day costs roughly $3-5/month.
- Storage: billed per GB-month for the persistent volume. 100 GB included.
- Hibernated Sprites cost only storage (pennies).

## What This Does NOT Cover

- Multi-user with separate Sprites per user
- CI/CD auto-deploy (could be a GitHub Action that runs `sprite exec`)
- Custom domain (Sprites support this but it's not documented here)
- Running multiple Bullpen workspaces on one Sprite (works fine, just
  `--workspace /path/to/other/repo`)
- SQLite migration (separate ticket)
