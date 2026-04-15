# Bullpen MCP Access Plan

Bullpen's MCP server has two audiences:

- Live agents launched inside Bullpen.
- External MCP clients launched from a separate terminal, editor, or agent session.

Those audiences need the same ticket tools, but they do not start with the same
context. Inside Bullpen, the agent adapter knows the active workspace and can
generate a complete MCP config. Outside Bullpen, the client has to discover the
workspace, import path, server address, and current auth token.

## Current Architecture

The MCP stdio server lives in `server/mcp_tools.py`. It exposes ticket tools over
JSON-RPC/MCP and supports both Content-Length framing and newline-delimited JSON.

Ticket reads are local. `list_tickets`, `list_tasks`, and
`list_tickets_by_title` read from the selected `.bullpen/tasks` directory.

Ticket writes are server-backed. `create_ticket` and `update_ticket` connect
back to the running Bullpen Flask/Socket.IO process so writes go through the
same validation, locking, workspace routing, and UI update path as browser
actions. This is deliberate: direct file writes can leave the UI stale, skip
validation, or write to the wrong project.

The stdio server therefore needs:

- a `.bullpen` directory for the intended project
- the running Bullpen server host and port
- the current per-run `mcp_token`
- a Python import path that can import the `server` package
- a running Bullpen server for write tools

Inside Bullpen, Claude and Codex adapters generate these settings per run. They
pass the correct `--bp-dir`, host, port, working directory, and `PYTHONPATH`.

Outside Bullpen, those details were previously implicit. A caller running
`server/mcp_tools.py` directly had to reconstruct them manually, which made
external use brittle and made failures collapse into vague socket errors.

## Recent Bug

Live agent chats were not fully project-isolated. Two related issues caused MCP
access to behave correctly in the Bullpen project while failing or crossing
state in other projects:

- Projects activated after server startup were not guaranteed to have the
  current MCP runtime metadata written to `.bullpen/config.json`.
- Live chat history and transcript-ticket ownership were keyed only by
  `sessionId`, not by workspace plus session.

The fix writes current `server_host`, `server_port`, and `mcp_token` whenever a
project is activated through add/new/clone, and scopes live chat state by
`(workspaceId, sessionId)`.

## Implemented Improvements

### `bullpen mcp`

External MCP clients now have a first-class launcher:

```bash
python3 bullpen.py mcp --workspace /path/to/project
```

The launcher resolves `/path/to/project/.bullpen`, reads server host and port
from `.bullpen/config.json`, and then starts the existing MCP stdio server. This
removes the need for callers to know the internal `server/mcp_tools.py` path or
set `PYTHONPATH` by hand.

Optional overrides are available:

```bash
python3 bullpen.py mcp --workspace /path/to/project --host 127.0.0.1 --port 5000
python3 bullpen.py mcp --bp-dir /path/to/project/.bullpen
```

This does not change inside-Bullpen access. Existing agent adapters may continue
to generate direct per-run MCP configs.

### Runtime Argument Resolution

`server/mcp_tools.py` can now resolve runtime settings from either a workspace or
a `.bullpen` directory. Direct use remains possible:

```bash
python3 server/mcp_tools.py --workspace /path/to/project
python3 server/mcp_tools.py --bp-dir /path/to/project/.bullpen
```

The `bullpen mcp` launcher is still preferred for external clients because it
runs from the Bullpen checkout and avoids import-path surprises.

### Better Diagnostics

Write-tool connection failures now include:

- workspace path
- MCP config path
- server host and port
- whether the MCP token is missing
- the most recent Socket.IO connection errors
- the recommended external launcher command

This should distinguish common failure modes:

- Bullpen is not running.
- Bullpen was restarted and the external client has stale config.
- The wrong workspace or `.bullpen` directory was selected.
- The local server cannot be reached from the caller's sandbox.
- Socket.IO authentication rejected the MCP token.

## Compatibility Rules

Inside-Bullpen access must remain strict and project-scoped:

- Generated MCP config should always use the active workspace's `.bullpen`.
- Writes should continue to go through Socket.IO.
- The per-run token should remain enforced.
- Live chat state should remain keyed by workspace and session.

External access should become easier without weakening those guarantees:

- Prefer `bullpen mcp --workspace`.
- Keep write tools server-backed by default.
- Provide explicit diagnostics instead of silent fallback behavior.
- Do not perform implicit direct task-file writes when the server is unavailable.

## Future Work

### Generated External Config

Add a command or UI action that prints a ready-to-use MCP client config for a
project, for example:

```bash
python3 bullpen.py mcp-config --workspace /path/to/project
```

The output should include command, args, cwd, and environment suitable for
Claude, Codex, or another MCP host.

### Explicit Offline Mode

Consider a deliberate offline mode for external clients:

```bash
python3 bullpen.py mcp --workspace /path/to/project --offline-readonly
python3 bullpen.py mcp --workspace /path/to/project --offline-write
```

Readonly mode is already effectively safe for listing. Offline write mode should
not be implicit. If implemented, it must clearly document that UI synchronization,
Socket.IO validation, and active worker coordination are unavailable.

### Stronger Workspace Handshake

The MCP helper currently matches its `.bullpen` directory to a workspace by
watching `state:init` events from the server. A stronger handshake could let the
MCP helper request a workspace path or id explicitly and receive a direct accept
or reject response.

### Installed Module Entrypoint

If Bullpen becomes an installable package, add a stable executable such as:

```bash
bullpen-mcp --workspace /path/to/project
```

or:

```bash
python3 -m bullpen.mcp --workspace /path/to/project
```

That would decouple external MCP configs from the source tree layout.

