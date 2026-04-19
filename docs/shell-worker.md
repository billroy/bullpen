# Shell Workers

Shell workers run a configured shell command against a Bullpen ticket. They
share the same lifecycle as AI workers: one ticket at a time, the same
disposition grammar, the same retry/blocked pipeline, the same focus view.

This document covers how to configure a Shell worker, what the command
receives, what output is persisted, and the security model. For the
implementation plan and the full specification, see
[worker-types.md](worker-types.md).

---

## Creating a Shell worker

1. Click an empty grid cell → **Add Worker**.
2. Pick the **Shell** tab (AI is the default).
3. Read the plaintext-storage warning, then click **Create Shell worker**.
4. The config modal opens. Set:
   - **Command** (required) — a single command line executed via `/bin/sh -c`
     on POSIX or `cmd.exe /c` on Windows.
   - **Pass ticket as** — how the ticket reaches your command:
     - `stdin-json` (default): JSON blob written to stdin.
     - `env-vars`: `BULLPEN_TICKET_*` variables + a tempfile for the body.
     - `argv-json`: JSON blob as a single positional arg. Falls back to
       `stdin-json` when it would exceed the platform's argv limit.
   - **Timeout seconds** — hard kill after this many seconds. Defaults to 60,
     max 600.
   - **Working directory** — relative to the workspace root. Must stay inside
     the workspace; symlink escapes are rejected.
   - **Environment** — extra key/value pairs merged on top of a minimal
     inherited env.
   - **Start from example** — optional dropdown that seeds Command, delivery
     mode, and disposition from `static/shell_worker_examples.json`.
5. Pick an **Input Trigger** and **Output disposition** (same options as AI
   workers).

### Disposition grammar

The disposition field accepts the same tokens as AI workers:

- `review`, `done`, `blocked`, or any custom column key.
- `worker:NAME` — case-insensitive name match after trimming.
- `pass:LEFT|RIGHT|UP|DOWN|RANDOM` — hand off to the adjacent grid cell.
- `random:PATTERN` — pick a non-self worker whose name matches `PATTERN`.
  Blank pattern matches any other worker.

A Shell command can override the configured disposition for a single run by
printing a JSON object to stdout (see the [output contract](#output-contract)).

---

## Input contract

The ticket is serialized as JSON. In `stdin-json` and `argv-json` modes the
command sees the whole payload:

```json
{
  "id": "task-id",
  "title": "Ticket title",
  "filename": "task-id.md",
  "project": "/abs/path/to/workspace",
  "status": "in_progress",
  "type": "task",
  "priority": "normal",
  "tags": ["..."],
  "body": "...",
  "history": [],
  "worker": {
    "name": "Shell Gate",
    "slot_index": 3,
    "coord": {"row": 0, "col": 2}
  }
}
```

In `env-vars` mode the scalar fields become environment variables:
`BULLPEN_TICKET_ID`, `BULLPEN_TICKET_TITLE`, `BULLPEN_TICKET_FILENAME`,
`BULLPEN_PROJECT`, `BULLPEN_TICKET_STATUS`, `BULLPEN_TICKET_PRIORITY`, and
`BULLPEN_TICKET_TAGS` (JSON array string). The ticket body is written to a
tempfile exposed via `BULLPEN_TICKET_BODY_FILE`.

**Bullpen never interpolates ticket fields into the command string.** The
command is run verbatim. Ticket data reaches the process only through the
selected delivery mode.

---

## Output contract

The exit code decides the outcome; JSON stdout can refine a successful run but
cannot override a failure.

| Exit code | Outcome |
|-----------|---------|
| `0` with empty or non-JSON stdout | success, configured disposition |
| `0` with JSON object stdout       | success, JSON may override disposition and update whitelisted fields |
| `78`                              | reroute to **Blocked**, no retry (traditional `EX_CONFIG`) |
| any other non-zero                | error, retried per `max_retries`, then **Blocked** |
| timeout                           | error with canonical reason `timeout`, retried, then **Blocked** |

Recognized keys in the JSON stdout object:

```json
{
  "disposition": "review|done|blocked|worker:NAME|pass:LEFT|pass:RIGHT|pass:UP|pass:DOWN|pass:RANDOM|random:PATTERN",
  "reason": "free text shown on the ticket",
  "ticket_updates": {
    "title": "...",
    "priority": "low|normal|high|urgent",
    "tags": ["..."],
    "body_append": "text appended to the ticket body"
  }
}
```

Rules:

- Unknown top-level keys are ignored.
- Known keys with invalid values fail the run (fail-closed — no partial
  updates).
- `ticket_updates.status` and `ticket_updates.assigned_to` are **not
  allowed**. Status changes go through disposition dispatch only.
- For non-zero exits, `disposition` and `ticket_updates` are ignored. Only
  `reason` (if valid) is used to annotate the failure.

---

## Run records

Each Shell run produces three artifacts:

1. A **frontmatter history row** on the ticket (`event: worker_run`) with
   outcome, disposition, exit code, duration, delivery mode, stdout/stderr
   byte counts, truncation flags, and paths to the sidecar logs.
2. A **Markdown block** appended to the ticket body under `## Worker Output`.
   When the body would exceed 1 MiB, the block is first excerpted
   (head/tail 64 KiB per stream); older output blocks are compacted to
   summary stubs if still needed.
3. **Plaintext sidecar logs** under
   `.bullpen/logs/worker-runs/<task_id>/shell-run-<timestamp>-slot<n>.{stdout,stderr}.log`,
   capped at 1 MiB each.

`.bullpen/logs/` is covered by the default `.bullpen/.gitignore` so these
artifacts are not accidentally committed.

---

## Security model

Shell workers execute arbitrary commands configured by the workspace owner.
**They are not a sandbox.** The defaults are:

- **No interpolation.** Ticket fields never make it into the command string.
- **Working-directory confinement.** Real paths are resolved with
  `os.path.realpath()` and must stay inside the workspace root.
- **Minimal inherited env.** Start from a small allowlist
  (POSIX: `PATH`, `HOME`, `LANG`, `LC_*`, `TZ`; Windows: `PATH`, `SYSTEMROOT`,
  `COMSPEC`, `PATHEXT`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`,
  `TMP`), then merge configured env on top.
- **Secret env filtering.** Inherited variables whose names (case-insensitive)
  contain `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`, or `PASSPHRASE`
  are dropped by default. This catches names like `AWS_ACCESS_KEY_ID`,
  `DATABASE_PASSWORD`, `GITHUB_TOKEN`, `SERVICE_CREDENTIAL_FILE`, and their
  lowercase variants. You can re-add any such variable explicitly in the
  config modal's Environment section if it is non-sensitive.
- **`BULLPEN_MCP_TOKEN` is always rejected.** It is neither inherited nor
  accepted as configured env, so Shell workers cannot reach Bullpen's MCP
  tools by impersonating the host session. Opt-in MCP access is a deferred
  feature.
- **Output caps.** stdout and stderr are each capped at 1 MiB per run; the
  ticket body is kept under 1 MiB via excerpts and older-block compaction.
- **Plaintext storage.** Command and env values live in `layout.json`;
  captured stdout/stderr live in task history and under
  `.bullpen/logs/worker-runs/`. **Do not put real secrets in a Shell worker.**
  Reference variables already present in the server environment instead.
- **Process-tree kill.** Timeouts and explicit stops terminate the whole
  process group (POSIX) or process tree (Windows).

### Secondary exposure surfaces

The following carry Shell config in plaintext in v1. The UI warns before
creating, transferring, or saving teams that contain Shell workers:

- Workspace export archives.
- Saved teams (`team:save`, `team:load`).
- Worker transfer between workspaces (copy or move).
- Backups.

A read-only viewer context in the server-side serializer redacts Shell
`command` values and env values (keeping key names). Today every
authenticated workspace user is treated as an editor, so redaction is not yet
user-visible — but every layout-emitting path already runs through the
serializer so real read-only roles can be added later without auditing each
emit site.

---

## Example library

`static/shell_worker_examples.json` ships with nine starters:

1. **Tag router** — pass bug tickets forward; others exit 78 (block).
2. **Title length gate** — reject titles shorter than 10 chars.
3. **Body contains filter** — route security-tagged bodies to a review
   worker.
4. **Priority auto-bumper** — bump priority when the body contains "urgent".
5. **External webhook notifier** — POST the ticket JSON to a webhook with
   `max_retries: 0` to avoid duplicates.
6. **Manual ls -als** — run `ls -als` in the workspace and capture the
   listing under Worker Output (pair with Input Trigger = Manual).
7. **Echo ticket title** — parse the ticket JSON from stdin and print its
   title to stdout.
8. **Create ticket with random number** — shell out to `bullpen ticket
   create` to spawn a new ticket whose description is a random 1..10.
9. **Ticket-to-file archiver** — append the ticket body to a workspace log.

Pick one from the config modal's "Start from example" dropdown and click
**Apply**. It overwrites Command, delivery mode, disposition defaults, and
`max_retries`. There is no preview pane; use browser undo if you change your
mind.

Examples are filtered by platform. POSIX-only entries (those that rely on
shell builtins or POSIX utilities) are hidden on Windows.

---

## Feature flag

Shell workers are on by default. If they misbehave they can be disabled
without touching code:

- Environment variable: `BULLPEN_ENABLE_SHELL_WORKERS=0`.
- Workspace config: `features.shell_workers_enabled: false` in
  `.bullpen/config.json`.

The environment variable takes precedence, so automated tests can force the
feature on or off without mutating workspace files.

---

## Deferred

See [worker-types.md](worker-types.md#7-deferred-features) for the full list.
Notably, Shell workers do **not** yet support Git worktrees, auto-commit,
auto-PR, or Bullpen MCP access. A future Eval worker type is reserved in the
registry but not runnable.
