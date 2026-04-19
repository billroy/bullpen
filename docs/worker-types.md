# Worker Types

Today Bullpen has a single worker type: an **AI worker** that spawns an agent
subprocess (`claude`, `codex`, `gemini`) against a ticket. This spec expands
the worker framework to a small number of first-class worker types that share
one lifecycle and one disposition pipeline.

Worker types covered by this spec:

1. **AI** - the existing agent worker, preserved for backward compatibility.
2. **Shell** - runs a configured shell command in the project workspace against
   a queued ticket.
3. **Eval** - reserved as a disabled/stub type only; implementation deferred.

Goal: every runnable worker type consumes a ticket from its queue and produces
exactly one of three outcomes:

- **success** - the ticket moves to this worker's configured `disposition`
  (`review`, `done`, `worker:NAME`, `pass:DIRECTION`, `random:PATTERN`, or a
  custom column key).
- **reroute** - the worker overrides its default disposition for this ticket
  and sends it to a specific destination.
- **error** - the ticket moves through the same retry/backoff policy as the AI
  worker (`max_retries`), then goes to **Blocked** with a captured reason.

The existing AI behavior in `server/workers.py` is the compatibility baseline.
Shell and future types plug into the same queue, retry, cancellation,
disposition, and Socket.IO update flow.

---

## 1. Shared Worker Lifecycle

Worker execution is split into shared lifecycle code plus type-specific runner
adapters. The shared lifecycle owns queue mutation, task status transitions,
retry/backoff, disposition dispatch, live process registration, focus output,
stop/yank behavior, timeout handling, and Socket.IO emits.

Type-specific code owns payload construction, subprocess argv/env/cwd, output
parsing, and config validation.

### 1.1 Ticket Acquisition

All runnable worker types consume **queued tickets only**.

This is a deliberate v1 rule. AI workers currently auto-create a synthetic
self-directed task when manually started with an empty queue. That behavior is
AI-specific and remains for `type: "ai"` for backward compatibility. It does
not apply to Shell or Eval.

For Shell and Eval:

- `on_drop` starts the worker only after a ticket is dropped onto the worker
  and queued.
- `on_queue` claims tickets from its watched column, queues them, then starts.
- `manual` starts the next queued ticket. The Run action is disabled when the
  queue is empty; the server also rejects an empty-queue start with a user
  visible error.
- `at_time` and `on_interval` start the next queued ticket when the schedule
  fires. If the queue is empty, no task is created, no command is run, and a
  short scheduler event is logged server-side.

Non-AI workers never run against the "currently selected" browser ticket. That
would make scheduled runs ambiguous and would couple server execution to a
client-only selection state.

Tests required:

- Shell manual start with empty queue is rejected and does not create a ticket.
- Shell `at_time` / `on_interval` with empty queue do not create tickets.
- Shell `on_drop`, `on_queue`, and manual-with-queued-ticket all consume the
  queued ticket and enter the shared lifecycle.

### 1.2 Shared Interfaces

Introduce a registry in `server/workers.py` keyed by slot `type`.

Each worker type implements:

```python
class WorkerType:
    type_id: str

    def validate_config(self, slot: dict) -> list[str]:
        """Return user-facing config errors. Empty list means runnable."""

    def prepare_run(self, *, task: dict, slot: dict, workspace: str, bp_dir: str) -> "PreparedRun":
        """Build cwd/env/argv/stdin metadata without mutating task or layout."""

    def parse_result(self, *, task: dict, slot: dict, completed: "CompletedProcessCapture") -> "WorkerResult":
        """Map captured process output to success/reroute/error."""

    def default_icon(self) -> str:
        """Lucide icon name."""

    def default_color(self) -> str:
        """Card color token."""
```

Shared helpers:

- `WorkerResult` describes `outcome`, optional disposition override, reason,
  whitelisted ticket updates, captured output references, and usage metadata.
- `PreparedRun` describes argv, cwd, env, stdin payload, delivery mode, timeout,
  and redacted command label.
- `SubprocessRunner` launches, streams, captures, kills, and finalizes local
  subprocesses for both AI and Shell workers.

The existing AI code should be migrated behind `AIWorkerType` without changing
observable behavior. Do this incrementally: first introduce the shared runner
for Shell, then move AI onto it once tests prove process-group cancellation and
focus output remain compatible.

### 1.3 Process Ownership, Cancellation, and Timeouts

All worker subprocesses run through a shared subprocess runner.

Requirements:

- One in-flight subprocess per slot.
- Register each live process by `(workspace_id, slot_index)` with the active
  task id so `stop_worker()` and `yank_from_worker()` can kill by task as well
  as by queue position.
- On POSIX, launch with `start_new_session=True` and terminate the whole process
  group on stop/yank/timeout.
- On Windows, launch with `CREATE_NEW_PROCESS_GROUP`; use the existing
  `taskkill /T /F /PID` behavior for tree cleanup.
- Timeout handling must use the same process-tree kill path as explicit stop.
- Server shutdown should attempt best-effort cleanup of registered subprocesses.

This is a shared correctness fix, not Shell-only. Shell commands are more
likely to spawn children, but AI CLIs can do it too.

---

## 2. Worker-Type Registry and Slot Storage

Reserve a `type` field on each worker slot in `layout.json`.

Valid built-in values:

```text
ai | shell | eval
```

The registry is **soft-open**. Unknown type strings are accepted on load and
preserved on save. Unknown workers render as disabled cards with a "Worker type
not installed" badge. They count as occupied cells for layout, minimap,
keyboard navigation, export/import, transfer, and team save/load.

Backward compatibility:

- Older slots with no `type` load as `type: "ai"`.
- AI slots continue to use existing `agent`, `model`, `expertise_prompt`,
  `use_worktree`, `auto_commit`, and `auto_pr` fields.
- New saves always write `type`.

### 2.1 Canonical Slot Normalization

Introduce a single normalization layer used by every layout mutation path:

```python
normalize_worker_slot(raw: dict | None, *, index: int, config: dict) -> dict | None
serialize_worker_slot(slot: dict, *, viewer: ViewerContext) -> dict
copy_worker_slot(slot: dict, *, reset_runtime: bool) -> dict
```

All code paths must use it:

- worker add
- worker configure
- worker duplicate
- worker paste
- worker remove/move
- save/load team
- transfer
- import/export
- startup reconcile
- app `load_state()`
- `layout:updated` emits
- worker module helper loads/saves

`normalize_worker_slot()` must preserve unknown type-specific fields. It may
fill missing shared defaults, but it must not drop fields it does not
understand. `validate_worker_configure()` must admit type-specific fields by
delegating to the worker-type registry instead of whitelisting AI-only fields.

Tests required:

- Unknown worker type with unknown fields round-trips through configure,
  duplicate, team save/load, transfer copy, export/import, and app restart.
- Shell worker fields round-trip through those same paths.
- Older AI slots without `type` load as AI and save back with `type: "ai"`.

### 2.2 Server-Side Serialization and Redaction

Shell command strings and configured env values are sensitive because they may
contain inline secrets. Redaction must be enforced before payloads leave the
server, not by frontend convention.

`serialize_worker_slot()` takes a viewer context and returns either:

- **editable view** - includes shell `command`, `env`, and all type config.
- **read-only view** - replaces shell `command` with `"<redacted>"`, removes
  env values, and includes only env key names.

Every server response or event that ships layout data must use the serializer:

- initial `state:init`
- `layout:updated`
- team load result
- transfer responses
- import/export previews
- any future REST layout endpoint

Current Bullpen auth does not yet model per-workspace read-only users. Until it
does, all authenticated workspace users are treated as editors. The serializer
is still required now so future read-only access does not need to audit every
layout emit path later.

The serialized read-only shape for shell env:

```json
{
  "env": [
    {"key": "FOO", "value": "<redacted>"}
  ]
}
```

Raw `layout.json`, workspace export archives, saved teams, and worker transfer
payloads contain plaintext shell config in v1. The UI must warn users before
creating or exporting Shell workers.

---

## 3. Shell Worker

Icon: `terminal` (lucide).
Color: the existing neutral/tool gray.

### 3.1 Config

Shell workers share the common fields:

- `name`
- `type: "shell"`
- `activation`
- `disposition`
- `watch_column`
- `max_retries`
- `paused`
- schedule fields (`trigger_time`, `trigger_interval_minutes`,
  `trigger_every_day`)

Shell-specific fields:

- **Command** (`command`, string, required). A single command line executed via
  the platform shell: `/bin/sh -c` on Unix and `cmd.exe /c` on Windows. Bullpen
  stores it verbatim and never interpolates ticket fields into it.
- **Working directory** (`cwd`, string, optional). Defaults to the workspace
  root. Relative paths resolve against the workspace root. Real path must stay
  within the workspace root.
- **Timeout seconds** (`timeout_seconds`, int, default 60, max 600).
- **Environment** (`env`, key/value list, optional). Merged on top of a minimal
  inherited env. Stored plaintext in `layout.json`; the modal must warn:
  "Values are stored in plaintext alongside the layout. Do not commit real
  secrets here. Prefer referencing variables already present in the server
  environment."
- **Pass ticket as** (`ticket_delivery`, enum): `stdin-json` (default),
  `env-vars`, or `argv-json`.

Shell workers do not have `agent`, `model`, `expertise_prompt`, `use_worktree`,
`auto_commit`, or `auto_pr` fields in v1. Worktree, auto-commit, and auto-PR
support are deferred.

### 3.2 Create and Edit UX

The Create Worker flow must let the user choose the worker type before the
worker is created.

Server payload:

```json
{
  "type": "shell",
  "coord": {"col": 2, "row": 0},
  "fields": {
    "name": "Shell gate",
    "command": "python3 scripts/check_ticket.py",
    "ticket_delivery": "stdin-json",
    "disposition": "review",
    "activation": "manual"
  }
}
```

Rules:

- AI creation can remain profile-driven.
- Shell creation may start from either a blank Shell worker or an example
  template. Shell examples are modal templates, not reusable profiles in v1.
- Eval appears disabled with "Reserved for a future release."
- Unknown worker types cannot be created by the UI, but imported/transferred
  unknown workers still render as disabled cards.
- The config modal hides AI-only fields for Shell and Shell-only fields for AI.
- Saving a Shell worker with an empty command is rejected server-side and
  displayed inline in the modal.

### 3.3 Input Contract

The ticket payload is serialized as JSON:

```json
{
  "id": "review-and-fluff-7dhd",
  "title": "Review and fluff",
  "filename": "review-and-fluff-7dhd.md",
  "project": "/abs/path/to/workspace",
  "status": "assigned",
  "type": "task",
  "priority": "normal",
  "tags": [],
  "body": "<free-text portion of the ticket>",
  "history": [],
  "handoff_depth": 2,
  "worker": {
    "name": "my-shell-worker",
    "slot": {"row": 1, "col": 3}
  }
}
```

Delivery modes:

- `stdin-json` - write the JSON blob to subprocess stdin, then close stdin.
  Recommended default.
- `env-vars` - scalar fields become environment variables:
  `BULLPEN_TICKET_ID`, `BULLPEN_TICKET_TITLE`, `BULLPEN_TICKET_FILENAME`,
  `BULLPEN_PROJECT`, `BULLPEN_TICKET_STATUS`, `BULLPEN_TICKET_PRIORITY`.
  The ticket body is written to a tempfile and exposed as
  `BULLPEN_TICKET_BODY_FILE`.
- `argv-json` - pass the JSON blob as one positional argument.

`argv-json` length check:

- POSIX: use `os.sysconf("SC_ARG_MAX")` when available, subtracting at least
  4096 bytes for command/env headroom.
- Windows: use a conservative 24 KiB maximum for the JSON argument because
  `CreateProcess` has a smaller command-line limit than typical POSIX systems.
- If the payload exceeds the limit, fall back to `stdin-json`. The run record
  must include `delivery: "stdin-json"` and
  `delivery_fallback_from: "argv-json"` so the fallback is visible in the UI.

Body tempfile lifecycle:

- Create with `tempfile.mkstemp()` mode `0600`.
- Delete in a `finally` block tied to subprocess lifetime.
- A child process that backgrounds work may outlive the parent and find the
  file gone. Shell workers that detach must copy the body first.

### 3.4 Output Contract

Exit code is the primary signal; stdout optionally refines it.

| Exit code | stdout                  | Outcome |
|-----------|-------------------------|---------|
| 0         | empty / non-JSON        | success using configured disposition |
| 0         | JSON object             | success/reroute/error as directed by JSON |
| 2         | any                     | reroute to Blocked, no retry |
| non-0     | any                     | error, retry per `max_retries`, then Blocked |
| timeout   | n/a                     | error with reason `timeout` |

When stdout is a JSON object, recognized keys are:

```json
{
  "status": "success|blocked|error",
  "disposition": "review|done|worker:NAME|pass:LEFT|pass:RIGHT|pass:UP|pass:DOWN|random:PATTERN",
  "reason": "free text shown on the ticket",
  "ticket_updates": {
    "title": "...",
    "priority": "low|normal|high|urgent",
    "tags": ["..."],
    "body_append": "text appended to the ticket body"
  }
}
```

Validation policy:

- Unknown top-level keys are ignored.
- Known top-level keys with invalid values fail the run.
- `ticket_updates` is fail-closed: any disallowed field or invalid value fails
  the run and applies no updates.
- `ticket_updates.status` is not allowed. Status changes go through
  disposition dispatch only.
- `ticket_updates.assigned_to` is not allowed.
- `priority` supports the existing full priority set, including `urgent`.
- `tags` must be a list of strings and use the same validation limits as task
  update events.
- Partial update application is forbidden. Validate the entire JSON result
  before mutating the ticket.

stderr is always captured, capped, and persisted with the run record regardless
of outcome.

### 3.5 Run Record Storage

Shell runs produce both a structured frontmatter history row and a Markdown
output block in the ticket body.

Structured frontmatter history entry:

```yaml
history:
  - timestamp: "2026-04-18T15:30:00Z"
    event: "worker_run"
    worker_type: "shell"
    worker_name: "Shell gate"
    worker_slot: 3
    task_id: "review-and-fluff-7dhd"
    outcome: "success|reroute|error"
    disposition: "review"
    exit_code: 0
    duration_ms: 1234
    delivery: "stdin-json"
    delivery_fallback_from: null
    stdout_bytes: 120
    stderr_bytes: 44
    stdout_truncated: false
    stderr_truncated: false
    command: "<redacted>"
    output_block_id: "shell-run-20260418T153000Z-slot3"
```

The structured row is intentionally metadata only. Full stdout/stderr belongs
in the Markdown body to avoid very large YAML frontmatter and to match the
current AI output convention.

Markdown body block:

````markdown
## Worker Output

### 2026-04-18T15:30:00Z - Shell gate (shell)

Outcome: success
Disposition: review
Exit code: 0
Duration: 1.234s
Delivery: stdin-json
Command: <redacted>

#### stdout

```text
...
```

#### stderr

```text
...
```
````

The frontend renders history rows from frontmatter and links each row to the
corresponding body block. Command text is never persisted in history or output
blocks. Viewers with edit permission may see the current command from the
serialized layout on the worker card/config modal, not from run history.

Retry entries remain in the same `history` list with their existing event names.
They are not merged into `worker_run` entries.

### 3.6 Security

The shell worker executes arbitrary commands configured by the workspace owner.
It is not a sandbox. Baseline guardrails:

- **No interpolation.** Bullpen never substitutes ticket fields into the
  command string. Ticket data reaches the subprocess only through the selected
  delivery mode. Cover this with a test.
- **Working directory confinement.** Resolve with `os.path.realpath()` and
  reject paths outside the workspace root, including symlink escapes.
- **Minimal inherited env.** Start with an allowlist and then apply configured
  env values.
- **Secret env filtering.** Never inherit `BULLPEN_MCP_TOKEN`,
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or anything matching
  `*_TOKEN`, `*_SECRET`, or `*_KEY` unless the user explicitly re-adds it in
  the Shell worker env.
- **Output caps.** Capture at most 256 KiB each for stdout and stderr. Truncate
  with visible markers and set the `*_truncated` flags in history.
- **Plaintext warnings.** The config modal must warn that command/env are
  stored in plaintext in workspace data and stdout/stderr are stored in task
  history in plaintext. No automatic secret scrubbing in v1.
- **Permission checks.** Creating or editing Shell workers requires workspace
  write access. Until Bullpen has read-only roles, all authenticated users are
  treated as workspace editors; when read-only roles arrive, server-side
  serialization must hide command/env values.

Env allowlist:

- POSIX: `PATH`, `HOME`, `LANG`, `LC_*`, `TZ`.
- Windows: `PATH`, `SYSTEMROOT`, `COMSPEC`, `PATHEXT`, `USERPROFILE`,
  `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP`.

Secondary feature exposure:

- Workspace export includes raw Shell config in v1. Show a warning before
  export if any Shell worker has command/env values.
- Saved teams include raw Shell config in v1. Show a warning when saving or
  loading teams that contain Shell workers.
- Worker transfer includes raw Shell config in v1. The transfer modal must
  warn when copying/moving a Shell worker to another workspace.
- Logs and ticket bodies include captured stdout/stderr. They are not scrubbed.
- Backups contain both raw Shell config and captured output.

### 3.7 Testability

Add `tests/test_shell_worker.py` covering:

- exit code to outcome mapping
- JSON stdout parsing and validation
- unknown top-level JSON keys ignored
- disallowed `ticket_updates` keys fail closed with no partial updates
- timeout path
- process group cancellation
- output truncation
- env allowlist and explicit env overrides
- cwd confinement and symlink escape rejection
- argv length fallback on POSIX and Windows
- no command interpolation
- structured history row plus Markdown output block
- command/env redaction in serialized layout for read-only viewer contexts

Use real small commands where possible (`python3 -c ...`, `/bin/true`,
`/bin/false`) rather than mocking `subprocess`, because quoting and shell
semantics are part of the feature. POSIX-only command tests must be skipped on
Windows.

E2E coverage:

- create a Shell worker via Socket.IO
- configure command and delivery mode
- assign a ticket
- assert final ticket status/disposition
- assert captured stderr appears in the output block
- assert history command is redacted
- assert read-only layout serialization hides command/env values

### 3.8 Example Shell Workers

The Create Worker modal offers a "Start from example" picker when `type=shell`.
It appears above the Command field as a dropdown plus **Apply** button. Apply
overwrites Command, disposition, delivery mode, and relevant env defaults in
place. There is no preview pane; browser undo is sufficient for v1.

Examples live in `static/shell_worker_examples.json`.

Each example must include:

- `id`
- `name`
- one-line `description`
- `command`
- `ticket_delivery`
- default `disposition`
- optional `env`
- `platforms`: `["posix"]`, `["windows"]`, or `["posix", "windows"]`

Seed examples:

1. **Tag router** - POSIX/Windows, requires Python.

   Command:

   ```text
   python3 -c 'import json,sys; t=json.load(sys.stdin); sys.exit(0 if "bug" in t.get("tags", []) else 2)'
   ```

   Delivery: `stdin-json`. Disposition: `worker:triage-bugs`.

   Bug tickets continue; non-bug tickets exit 2 and move to Blocked without
   retry. Users can change disposition to a pass direction for a board flow.

2. **Title length gate** - POSIX.

   Command:

   ```text
   [ ${#BULLPEN_TICKET_TITLE} -ge 10 ] || { echo "title too short" >&2; exit 2; }
   ```

   Delivery: `env-vars`. Disposition: `pass:RIGHT`.

3. **Body contains filter** - POSIX.

   Command:

   ```text
   grep -q -i "security" "$BULLPEN_TICKET_BODY_FILE" || exit 2
   ```

   Delivery: `env-vars`. Disposition: `worker:security-review`.

   Non-match exits 2 so it blocks/reroutes without retry rather than using
   `grep`'s ordinary exit 1 error path.

4. **Priority auto-bumper** - POSIX/Windows, requires Python.

   Command:

   ```text
   python3 -c 'import json,sys; t=json.load(sys.stdin); print(json.dumps({"ticket_updates":{"priority":"high"}}) if "urgent" in t.get("body","").lower() else "")'
   ```

   Delivery: `stdin-json`. Disposition: `pass:RIGHT`.

5. **External webhook notifier** - POSIX.

   Command:

   ```text
   curl -fsS -X POST -H 'Content-Type: application/json' --data-binary @- https://example.com/hook
   ```

   Delivery: `stdin-json`. Disposition: `pass:RIGHT`. Env must include any
   auth token the user wants to send.

6. **Ticket-to-file archiver** - POSIX.

   Command:

   ```text
   printf "=== %s ===\n%s\n\n" "$BULLPEN_TICKET_ID" "$(cat "$BULLPEN_TICKET_BODY_FILE")" >> .bullpen/archive.log
   ```

   Delivery: `env-vars`. Disposition: `review`.

Examples that depend on POSIX utilities must be marked POSIX-only in the picker.

---

## 4. Eval Worker (Deferred)

Reserve `type: "eval"` in the registry with an `EvalWorkerType` stub whose
`validate_config()` returns "Eval workers are not yet implemented."

Eval workers must round-trip through layout save/load, import/export, transfer,
teams, and app restart, but the UI must not allow users to create runnable Eval
workers until the expression language is selected.

Open decision for a future spec:

- Expression language. Candidates: JMESPath, CEL, or a deliberately tiny safe
  evaluator over the ticket dict. The future spec must enumerate bindings such
  as `ticket`, `now()`, `tag("foo")`, and column counts.

Eval language selection does not block the Shell MVP.

---

## 5. Implementation Plan

### Phase 1 - Registry and Normalization

- Add `type` defaults for existing AI slots.
- Add worker type registry with AI, Shell, Eval, and Unknown adapters.
- Add canonical normalize/serialize/copy helpers.
- Route all layout mutation, import/export, transfer, team, and startup paths
  through the helpers.
- Add unknown-type round-trip tests.

### Phase 2 - Shared Subprocess Runner

- Extract process launch, stream capture, timeout, process-group kill, and live
  output buffering into a shared runner.
- Keep AI behavior stable.
- Add process-tree stop/yank/timeout tests.

### Phase 3 - Shell Worker Backend

- Implement Shell config validation.
- Implement ticket payload construction and delivery modes.
- Implement JSON stdout parser and validation.
- Implement run record metadata plus Markdown output blocks.
- Implement Shell result dispatch through existing disposition machinery.

### Phase 4 - Shell Worker Frontend

- Add worker type selection to Create Worker.
- Add Shell-specific config fields.
- Add Shell examples picker.
- Add plaintext and export/transfer warnings.
- Render Shell run history/output blocks.
- Render unknown types as disabled occupied cards.

### Phase 5 - Hardening and E2E

- Add full unit and E2E coverage from §3.7.
- Add Windows smoke tests where CI supports Windows; otherwise mark POSIX-only
  tests explicitly.
- Add documentation for Shell worker security and examples.

---

## 6. Open Issues

1. **Permission model readiness.** The serializer should support read-only
   redaction now, but Bullpen currently treats authenticated users as editors.
   Before introducing real read-only roles, audit every layout-bearing response
   and ensure viewer contexts are available outside request handlers, including
   Socket.IO background emits.

2. **AI migration timing.** The shared subprocess runner should eventually own
   AI process cancellation too. Decide whether Shell ships with the new runner
   first and AI migrates after, or whether process-group behavior changes for
   AI in the same release. Safer proposal: introduce shared runner for Shell,
   add equivalent tests for AI, then migrate AI in a follow-up patch before
   enabling Shell by default.

3. **Workspace export warning UX.** The spec requires warnings for Shell config
   exposure in export/team/transfer flows. The exact UI copy and confirmation
   mechanics need design, especially for bulk "export all" flows.

4. **History growth.** Capturing 256 KiB each for stdout and stderr per run can
   grow ticket files quickly. The cap is acceptable for v1, but implementation
   should add a future migration note for external log files or per-run log
   artifacts if ticket files become unwieldy.

5. **Column vs. Blocked semantics for exit 2.** This spec maps exit 2 to
   Blocked without retry. Some example "filter" workers might prefer "no match,
   pass along" rather than Blocked. Users can express that by outputting JSON
   with a disposition override, but the examples should be reviewed against
   real board workflows before seeding.

6. **Shell availability on minimal systems.** POSIX assumes `/bin/sh`; Windows
   assumes `cmd.exe`. If Bullpen later runs in restricted containers, expose a
   startup health check that marks Shell worker creation unavailable when no
   shell can be launched.

---

## 7. Deferred Features

- Worktree support for Shell workers.
- Auto-commit / auto-PR on Shell worker success.
- Per-workspace capability controls beyond the current auth/write model.
- Secret env vars backed by OS keychain or a server-side secret store.
- Long-lived Tool worker type that speaks MCP/JSON-RPC to a subprocess.
- Eval worker implementation.
