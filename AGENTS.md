# Bullpen Agent Notes

## Ticket Writes

Bullpen tickets are live application state. Do not create or update tickets by
writing files under `.bullpen/tasks` directly. Direct writes bypass the running
Flask/Socket.IO server, so browser boards do not receive `task:created` or
`task:updated` events.

Use the best available server-backed path:

1. If Bullpen MCP tools are exposed in the session, use them directly:
   `mcp__bullpen__create_ticket`, `mcp__bullpen__update_ticket`, and related
   list tools.
2. If MCP tools are not exposed but shell commands are available, use the
   server-backed ticket CLI:

```bash
python3 bullpen.py ticket --workspace /path/to/project create \
  --title "Ticket title" \
  --status review \
  --description "Markdown body"
```

```bash
python3 bullpen.py ticket --workspace /path/to/project update \
  --id ticket-id \
  --status review
```

For longer text, write it outside `.bullpen/tasks` and pass it with
`--description-file` or `--body-file`.

If neither MCP tools nor the ticket CLI can reach the running Bullpen server,
stop and report that ticket writes are unavailable. Do not fall back to direct
`.bullpen/tasks` filesystem writes.
