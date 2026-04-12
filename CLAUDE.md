# Bullpen — Developer Notes

## Using the Bullpen MCP tools

The Bullpen MCP tools (`mcp__bullpen__*`) are available in this project. When the
user asks you to create tickets, list tickets, or update tickets, **use these
tools directly** — do not claim they are unavailable. They may appear in the
deferred tools list rather than the primary tool list; they are still usable.

### Ticket writes must go through MCP

When creating or updating Bullpen tickets during an interactive session, use the
Bullpen MCP tools rather than writing files under `.bullpen/tasks` directly.
Direct filesystem writes bypass the running Flask/Socket.IO server, so the
browser will not receive `task:created` or `task:updated` events and the user
will not see the ticket until they refresh the page.

Only fall back to direct `.bullpen/tasks` writes if MCP is genuinely unavailable
and the user has agreed to that tradeoff. If you must fall back, explicitly warn
that the page may need to be refreshed.

## MCP Stdio Server (`server/mcp_tools.py`)

The Bullpen MCP is a **stdio** server — Claude Code spawns it as a child process
and communicates via stdin/stdout JSON-RPC.  This has a critical implication:

**Any stray byte on stdout kills the MCP connection.**  If the `socketio` library
(or any dependency) calls `print()`, emits a log message, or writes a warning to
`sys.stdout`, it corrupts the MCP framing and Claude Code terminates the process.
The agent then reports "MCP not found" until the next session restarts it.

### Safeguards (do not remove)
- `main()` captures `sys.stdout.buffer` as `_mcp_out`, then redirects `sys.stdout`
  to `sys.stderr`.  All MCP writes go through `_mcp_out`.
- The main read loop catches exceptions per-message so one bad request cannot
  crash the process.
- `BullpenClient._connect_best_effort` retries up to `MAX_CONNECT_ATTEMPTS`
  times with a 5-second timeout per attempt.

### Auth and the MCP client
When auth is enabled, the Bullpen server rejects unauthenticated Socket.IO
connections.  The MCP stdio server has no browser session, so it authenticates
via a shared token:

1. `create_app()` generates a random `mcp_token` and writes it to each
   workspace's `.bullpen/config.json`.
2. `BullpenClient._connect_best_effort()` reads that token and passes it as
   `auth={"mcp_token": ...}` during the Socket.IO handshake.
3. `on_connect(auth_data)` in `app.py` accepts connections that carry the
   correct token, even without a session cookie.

If you change auth handling, make sure this path still works — it is the only
way the MCP can reach the server when auth is on.

### When editing this file
- Never add `print()` calls in `mcp_tools.py` — use `sys.stderr` explicitly if
  you need debug output.
- Never import modules that write to stdout at import time.
- Keep the stdout redirect as early as possible in `main()`.

## Running Tests

```
python3 -m pytest tests/ -x -q
```

## Stack
- Backend: Flask + Flask-SocketIO (threading mode)
- Frontend: Vue 3 via CDN (no build step)
- Storage: flat files in `.bullpen/`
