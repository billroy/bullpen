# Worker Types

Today Bullpen has a single worker type: an **AI worker** that spawns an agent
subprocess (`claude`, `codex`, `gemini`) against a ticket. This spec expands
the worker framework to a small number of first-class worker types that share
one lifecycle and one disposition pipeline.

Worker types covered by this spec:

1. **AI** - the existing agent worker, preserved for backward compatibility.
2. **Shell** - runs a configured shell command in the project workspace against
   either a queued ticket or a synthetic ticket created for manual/scheduled
   runs.
3. **Eval** - reserved as a disabled/stub type only; implementation deferred.

Goal: every runnable worker type runs against exactly one queued or synthetic
ticket and produces exactly one of three outcomes:

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

All runnable worker types run against a ticket. The ticket may already be queued
or may be synthesized by the server when a non-queue trigger needs a durable run
record.

Current AI workers already auto-create a self-directed ticket when manually
started with an empty queue. Generalize that behavior into the shared lifecycle
instead of keeping it AI-specific. Synthetic tickets are required for Shell
manual and scheduled runs so every run has an auditable ticket, captured output,
history, status transitions, and disposition.

Ticket sources:

- `on_drop` starts after a human drops a ticket onto the worker and queues it.
- `on_queue` claims a ticket from its watched column, queues it, then starts.
- `manual` starts the next queued ticket when one exists. If the queue is empty,
  the server synthesizes a ticket that explicitly records it was created for a
  manual worker run.
- `at_time` and `on_interval` start the next queued ticket when one exists. If
  the queue is empty, the scheduler synthesizes a ticket that records the
  schedule trigger name/time and then starts the run.

Synthetic ticket rules:

- Create through the same task creation path as AI auto-tasks so browser boards
  receive normal `task:created` events.
- Title format: `[Auto] {worker_name} - {trigger_label} - {timestamp}`.
- Type: `chore`.
- Priority: `normal`.
- Tags: `["synthetic", "worker-run"]`, plus `manual` or `scheduled`.
- Frontmatter includes `synthetic_run: true`, `trigger_kind`, and
  `synthetic_run_key`.
- Scheduled run key format:
  `{worker_slot}:{trigger_kind}:{scheduled_at}`. Before creating a scheduled
  synthetic ticket, the scheduler must check live and archived tickets for the
  same key and skip creation when one already exists.
- `scheduled_at` is the nominal trigger boundary, not the time the scheduler
  happens to wake up. `at_time` uses that day's configured wall-clock time in
  the workspace timezone. `on_interval` floors to the configured interval
  boundary from the worker's schedule anchor, so a late tick after restart
  produces the same key as the original intended run.
- Body includes the worker name, worker type, trigger kind, workspace path, and
  schedule details when applicable.
- Immediately assign the ticket to the worker, then move it through
  `Assigned -> In Progress` using the same lifecycle path as queued tickets.
- The normal disposition pipeline still decides where the completed ticket goes.

Non-AI workers never run against the "currently selected" browser ticket. That
would make scheduled runs ambiguous and would couple server execution to a
client-only selection state.

Tests required:

- Shell manual start with empty queue creates a synthetic ticket, assigns it,
  moves it to In Progress, captures output, and applies disposition.
- Shell `at_time` / `on_interval` with empty queue create synthetic tickets
  with scheduled-run metadata and enter the shared lifecycle.
- Re-running a scheduler tick after restart does not create duplicate
  synthetic tickets for the same scheduled run key, including when an
  `on_interval` tick fires late and must use the nominal interval boundary.
- Shell `on_drop`, `on_queue`, and manual-with-queued-ticket all consume the
  queued ticket without creating a synthetic ticket.
- AI empty-queue manual start remains behaviorally compatible after synthetic
  ticket creation moves into the shared lifecycle.

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
observable behavior. Shell may land first while the shared controller is still
forming, but the Shell feature flag is a disaster-recovery kill switch rather
than the normal rollout gate. AI and Shell still must both run through the
shared lifecycle controller described in the implementation plan.

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
- Keep a bounded live output tail buffer of at least 64 KiB per in-flight slot
  so a browser opening focus mode mid-run receives partial output for Shell and
  AI workers through the same catch-up path.
- Server shutdown should attempt best-effort cleanup of registered subprocesses.

This is a shared correctness fix, not Shell-only. Shell commands are more
likely to spawn children, but AI CLIs can do it too.

### 1.4 Disposition Grammar

Worker results and worker configuration use the same disposition grammar:

- `review`, `done`, `blocked`, or any configured custom column key moves the
  ticket to that column and clears `assigned_to`.
- `worker:NAME` hands the ticket to the worker whose name matches `NAME` after
  trimming whitespace and case-folding.
- `pass:LEFT`, `pass:RIGHT`, `pass:UP`, and `pass:DOWN` hand the ticket to the
  worker occupying the adjacent grid cell in that direction. Direction matching
  is case-insensitive.
- `pass:RANDOM` selects one occupied adjacent cell at random.
- `random:PATTERN` selects a non-self worker at random. Blank `PATTERN` matches
  any other worker. Nonblank `PATTERN` is currently an exact normalized worker
  name match, not a glob or regular expression.

Invalid disposition values fail validation before mutating the ticket.

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
keyboard navigation, export/import, transfer, and team save/load. Disabled
unknown-type cards still support remove, move, duplicate, export, transfer, and
copy operations; only configure and run actions are disabled.

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
- Unknown worker type cards can be removed without installing that type.
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
- A manual Shell worker with an empty queue is runnable. The button copy must
  make that explicit, using "Run once" plus helper text such as "Creates a
  worker-run ticket when the queue is empty." The corresponding synthetic
  ticket is the landing zone for commands that import external tickets, restart
  test servers, or otherwise do useful work without first receiving a user
  ticket.

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
  "worker": {
    "name": "my-shell-worker",
    "slot_index": 3,
    "coord": {"row": 1, "col": 3}
  }
}
```

`worker.slot_index` and `worker.coord` are snapshots captured at run start.
Commands that need a durable worker identifier should prefer `slot_index`;
`coord` is included for human-readable context and may no longer reflect the
worker's current grid position if the worker is moved later.

Delivery modes:

- `stdin-json` - write the JSON blob to subprocess stdin, then close stdin.
  Recommended default.
- `env-vars` - scalar fields become environment variables:
  `BULLPEN_TICKET_ID`, `BULLPEN_TICKET_TITLE`, `BULLPEN_TICKET_FILENAME`,
  `BULLPEN_PROJECT`, `BULLPEN_TICKET_STATUS`, `BULLPEN_TICKET_PRIORITY`, and
  `BULLPEN_TICKET_TAGS`. Tags are encoded as a JSON array string, not a
  comma-separated list, so tags containing punctuation round-trip safely. The
  ticket body is written to a tempfile and exposed as
  `BULLPEN_TICKET_BODY_FILE`.
- `argv-json` - pass the JSON blob as one positional argument.

Ticket data is serialized as UTF-8. Bullpen ticket storage is expected to
normalize ticket bodies to valid UTF-8 before worker execution. If a malformed
ticket body is encountered, the lifecycle rejects the run before launching the
Shell command, records the reason `invalid_ticket_encoding`, and moves the
ticket through the normal error/retry path.

`argv-json` length check:

- POSIX: use `os.sysconf("SC_ARG_MAX")` when available, subtracting at least
  4096 bytes for command/env headroom.
- Windows: use a conservative 24 KiB maximum for the JSON argument because
  `CreateProcess` has a smaller command-line limit than typical POSIX systems.
- If the payload exceeds the limit, fall back to `stdin-json`. The run record
  must include `delivery: "stdin-json"` and
  `delivery_fallback_from: "argv-json"` so the fallback is visible in the UI.
  The live output stream must also emit a line such as
  `[bullpen] payload 28KiB > argv limit, using stdin-json` before the child
  command starts so a command author can diagnose why `sys.argv[1]` was empty.

Body tempfile lifecycle:

- Create with `tempfile.mkstemp()` mode `0600`.
- Delete in a `finally` block tied to subprocess lifetime.
- A child process that backgrounds work may outlive the parent and find the
  file gone. Shell workers that detach must copy the body first.

### 3.4 Output Contract

Exit code is the primary signal. JSON stdout may refine a successful result,
but it must not contradict the process outcome.

| Exit code | stdout                  | Outcome |
|-----------|-------------------------|---------|
| 0         | empty / non-JSON        | success using configured disposition |
| 0         | JSON object             | success using JSON disposition and ticket updates |
| 78        | any                     | reroute to Blocked, no retry |
| non-0     | any                     | error, retry per `max_retries`, then Blocked |
| timeout   | n/a                     | error with reason `timeout`, retry per `max_retries`, then Blocked |

Exit code 78 is reserved for an intentional terminal block, matching the
traditional `EX_CONFIG` meaning closely enough to be memorable while avoiding
common collisions such as Python `argparse`, `grep`, and linters that use exit
code 2. Exit code 2 has no special meaning in Bullpen.

When stdout is a JSON object, recognized keys are:

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

Validation policy:

- Unknown top-level keys are ignored.
- Known top-level keys with invalid values fail the run.
- `status` is not a recognized key. If present, it is ignored like any other
  unknown key. Outcome comes from the exit code only.
- For exit code 0, `disposition` may override the configured worker
  disposition and `ticket_updates` may mutate whitelisted ticket fields.
- For exit code 78 or any other nonzero exit, `disposition` and
  `ticket_updates` are ignored. If stdout is JSON and contains a valid `reason`,
  Bullpen uses that reason in addition to stderr/output excerpts.
- For nonzero exits, malformed JSON stdout is ignored. The exit code, stderr,
  timeout state, and captured output are already the failure signal, and a
  malformed diagnostic payload must not mask that signal.
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

Reason surfacing:

- The selected reason is stored in the `worker_run` history row.
- The reason is written into the corresponding Markdown output block.
- If the run fails, times out, or exits 78, the same reason is included in the
  Socket.IO completion/error payload so the board can show a toast or inline
  error without reparsing the ticket body.
- Timeout uses the exact canonical reason string `timeout`.

stderr is always captured, capped, and persisted with the run record regardless
of outcome.

### 3.5 Run Record Storage

Shell runs produce three records:

1. A structured frontmatter history row.
2. A Markdown output block in the ticket body.
3. Plaintext sidecar artifacts for captured stdout/stderr.

The ticket body must remain at or below 1 MiB after appending worker output.
This cap includes all Markdown content, not frontmatter.

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
    reason: null
    exit_code: 0
    duration_ms: 1234
    delivery: "stdin-json"
    delivery_fallback_from: null
    stdout_bytes: 120
    stderr_bytes: 44
    stdout_observed_bytes: 120
    stderr_observed_bytes: 44
    stdout_truncated: false
    stderr_truncated: false
    stdout_artifact: ".bullpen/logs/worker-runs/review-and-fluff-7dhd/shell-run-20260418T153000Z-slot3.stdout.log"
    stderr_artifact: ".bullpen/logs/worker-runs/review-and-fluff-7dhd/shell-run-20260418T153000Z-slot3.stderr.log"
    body_excerpt_truncated: false
    output_block_id: "shell-run-20260418T153000Z-slot3"
```

The structured row is intentionally metadata only. Command text is never
persisted in history rows or output blocks. Viewers with edit permission may see
the current command from the serialized layout on the worker card/config modal,
not from run history.

Sidecar artifacts:

- Store stdout/stderr under
  `.bullpen/logs/worker-runs/{task_id}/{output_block_id}.stdout.log` and
  `.bullpen/logs/worker-runs/{task_id}/{output_block_id}.stderr.log`.
  `output_block_id` must include enough precision to avoid same-slot rapid
  rerun collisions, using either millisecond timestamp precision or a short
  monotonic suffix after the timestamp.
- Capture at most 1 MiB per stream. Truncate with visible markers and set the
  `*_truncated` flags in history.
- `stdout_bytes` and `stderr_bytes` record the stored artifact bytes after
  capping. `stdout_observed_bytes` and `stderr_observed_bytes` record the total
  stream bytes observed before capping when the platform can measure them
  cheaply; otherwise they equal the stored byte counts.
- The artifacts are plaintext server-managed logs. They are not scrubbed,
  encrypted, or automatically committed.

Markdown output block:

- Always write sidecar artifacts first.
- Build the newest run's output block with full stdout/stderr when the new
  ticket body would remain at or below 1 MiB.
- If the newest run's full block would exceed the ticket cap, reduce that block
  to maximally useful
  excerpts: the first 64 KiB and last 64 KiB of each overlarge stream, plus the
  sidecar artifact path and byte/truncation metadata.
- If the body would still exceed the cap after excerpting the newest run,
  compact the oldest existing Worker Output blocks into summary stubs until the
  body fits. A compacted stub preserves timestamp, worker name/type, outcome,
  disposition, reason, duration, delivery mode, output byte counts, and sidecar
  artifact paths. Compaction must not delete sidecar artifacts.
- If the newest run's metadata-only stub would itself push the ticket body over
  1 MiB after older blocks have been compacted, keep the sidecar artifacts and
  fail the run-record write with a visible server error. Do not write a partial
  or malformed ticket body.

Markdown body block:

````markdown
## Worker Output

### 2026-04-18T15:30:00Z - Shell gate (shell)

Outcome: success
Disposition: review
Reason: none
Exit code: 0
Duration: 1.234s
Delivery: stdin-json
stdout artifact: .bullpen/logs/worker-runs/review-and-fluff-7dhd/shell-run-20260418T153000Z-slot3.stdout.log
stderr artifact: .bullpen/logs/worker-runs/review-and-fluff-7dhd/shell-run-20260418T153000Z-slot3.stderr.log

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
corresponding body block.

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
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or any variable whose
  name case-insensitively contains `TOKEN`, `SECRET`, `KEY`, `PASSWORD`,
  `CREDENTIAL`, or `PASSPHRASE` unless the user explicitly re-adds it in the
  Shell worker env. `BULLPEN_MCP_TOKEN` is the exception: it is always rejected
  for Shell workers in v1. This catches names such as `AWS_ACCESS_KEY_ID`,
  `DATABASE_PASSWORD`, `GITHUB_TOKEN`, and `SERVICE_CREDENTIAL_FILE`.
  The modal copy must explain the broad filter: "Common-name variables
  containing TOKEN, KEY, SECRET, PASSWORD, CREDENTIAL, or PASSPHRASE are
  filtered by default. Add non-sensitive variables back explicitly if needed."
- **No MCP access in v1.** Shell workers cannot call Bullpen MCP tools by
  inheriting the host session. `BULLPEN_MCP_TOKEN` is neither inherited nor
  accepted as configured Shell env, even when another env rule would otherwise
  allow it. Opt-in MCP access is a deferred feature.
- **Output caps.** Capture at most 1 MiB each for stdout and stderr into
  sidecar artifacts, then keep the ticket body under 1 MiB using full output,
  head/tail excerpts, or compacted output summaries as described in §3.5.
- **Plaintext warnings.** The config modal must warn that command/env are
  stored in plaintext in workspace data and stdout/stderr are stored in task
  history and `.bullpen/logs/worker-runs/` in plaintext. No automatic secret
  scrubbing in v1.
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
- `.bullpen/logs/` must be covered by Bullpen's default `.bullpen/.gitignore`
  so worker-run artifacts are not accidentally committed.
- Backups contain both raw Shell config and captured output.

### 3.7 Testability

Add `tests/test_shell_worker.py` covering:

- exit code to outcome mapping
- JSON stdout parsing and validation
- exit code 78 reroutes to Blocked without retry
- exit code 2 retries like any other nonzero error
- JSON `status` is ignored and cannot override the exit-code outcome
- malformed JSON stdout is ignored on nonzero exits
- unknown top-level JSON keys ignored
- disallowed `ticket_updates` keys fail closed with no partial updates
- `reason` lands in history, the output block, and failure completion payloads
- timeout records the canonical reason `timeout`
- timeout path
- process group cancellation
- output truncation
- ticket body stays below 1 MiB using sidecar artifacts, head/tail excerpts, and
  old output-block compaction
- newest-run excerpting happens before old-block compaction; artifact write
  still succeeds when the body block cannot be appended
- rapid same-slot reruns produce unique artifact paths
- env allowlist and explicit env overrides
- secret env filtering for realistic names including `AWS_ACCESS_KEY_ID`,
  `DATABASE_PASSWORD`, `GITHUB_TOKEN`, `SERVICE_CREDENTIAL_FILE`, and
  lowercase variants
- `BULLPEN_MCP_TOKEN` is never inherited and is rejected as configured Shell env
- cwd confinement and symlink escape rejection
- argv length fallback on POSIX and Windows
- argv fallback emits a visible output line before command execution
- no command interpolation
- structured history row plus Markdown output block
- command/env redaction in serialized layout for read-only viewer contexts
- unknown worker type removal
- live focus buffer catch-up for Shell output
- invalid ticket-body encoding fails before subprocess launch

Use real small commands where possible (`python3 -c ...`, `/bin/true`,
`/bin/false`) rather than mocking `subprocess`, because quoting and shell
semantics are part of the feature. POSIX-only command tests must be skipped on
Windows.

Shared lifecycle/controller tests cover:

- synthetic-ticket idempotency across scheduler restart, including late
  `on_interval` ticks that must reuse the nominal interval boundary
- default `.bullpen/.gitignore` includes `logs/`
- feature flag behavior defaults Shell on and can disable it as a
  disaster-recovery contingency

E2E coverage:

- create a Shell worker via Socket.IO
- configure command and delivery mode
- assign a ticket
- assert final ticket status/disposition
- assert captured stderr appears in the output block
- assert command text is absent from history and output blocks
- assert read-only layout serialization hides command/env values

### 3.8 Example Shell Workers

The Add Worker library offers Shell examples alongside the blank Shell worker.
Choosing one creates a prefilled Shell worker whose command, disposition,
delivery mode, and relevant env defaults can then be edited in the config
modal.

Examples live in `static/shell_worker_examples.json`.

Each example must include:

- `id`
- `name`
- one-line `description`
- `command`
- `ticket_delivery`
- default `disposition`
- optional `max_retries`
- optional `env`
- `platforms`: `["posix"]`, `["windows"]`, or `["posix", "windows"]`

Seed examples:

1. **Tag router** - POSIX/Windows, requires Python.

   Command:

   ```text
   python3 -c 'import json,sys; t=json.load(sys.stdin); sys.exit(0 if "bug" in t.get("tags", []) else 78)'
   ```

   Delivery: `stdin-json`. Disposition: `worker:triage-bugs`.

   Bug tickets continue; non-bug tickets exit 78 and move to Blocked without
   retry. Users can change disposition to a pass direction for a board flow.

2. **Title length gate** - POSIX.

   Command:

   ```text
   [ ${#BULLPEN_TICKET_TITLE} -ge 10 ] || { echo "title too short" >&2; exit 78; }
   ```

   Delivery: `env-vars`. Disposition: `pass:RIGHT`.

3. **Body contains filter** - POSIX.

   Command:

   ```text
   grep -q -i "security" "$BULLPEN_TICKET_BODY_FILE" || { code=$?; [ "$code" -eq 1 ] && exit 78; exit "$code"; }
   ```

   Delivery: `env-vars`. Disposition: `worker:security-review`.

   Non-match exits 78 so it blocks/reroutes without retry rather than using
   `grep`'s ordinary exit 1 error path. Real `grep` errors, including exit 2,
   still flow through the retry path.

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

   Delivery: `stdin-json`. Disposition: `pass:RIGHT`. Default
   `max_retries: 0` to avoid duplicate webhook posts. Env must include any auth
   token the user wants to send.

6. **Ticket-to-file archiver** - POSIX.

   Command:

   ```text
   printf "=== %s ===\n%s\n\n" "$BULLPEN_TICKET_ID" "$(cat "$BULLPEN_TICKET_BODY_FILE")" >> .bullpen/logs/shell-archive.log
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

### Phase 3 - Shell Backend Validation With Kill Switch

Shell lands first to validate Shell-specific requirements. It is enabled by
default, while the feature flag remains available as a disaster-recovery kill
switch if Shell behavior destabilizes the board during implementation or early
use. The goal is to prove the command, payload, output, artifact, and
synthetic-ticket contracts before migrating the current AI backend.

Feature flag:

- Default is enabled.
- Operators can disable Shell globally with `BULLPEN_ENABLE_SHELL_WORKERS=0`.
- Workspace config may also disable it with
  `features.shell_workers_enabled: false` in `.bullpen/config.json`.
- The environment variable takes precedence over workspace config so automated
  tests can force the feature on or off without mutating workspace files.

Process:

- Implement Shell config validation.
- Implement ticket payload construction and delivery modes.
- Implement JSON stdout parser and validation.
- Implement run record metadata, sidecar artifacts, Markdown output blocks, and
  ticket-body compaction.
- Implement Shell result parsing as an adapter that feeds the same disposition
  grammar as AI.
- Validate manual empty-queue use cases, including importing an external ticket
  into Bullpen and restarting a test server.
- Keep the flagged implementation small and explicitly temporary. It may call
  adapter shims while the shared controller is still forming, but it must not
  introduce a second long-lived queue runner, retry handler, process registry,
  output stream path, or disposition implementation.
- Keep the kill switch wired throughout this phase so Shell can be disabled
  without reverting code if a serious regression appears.

Done when:

- Shell-specific adapter behavior passes the §3.7 tests.
- Synthetic tickets, output artifacts, and disposition results are observable in
  the board through normal task events.
- Any temporary Shell-only lifecycle shim is named, isolated, and listed for
  removal in Phase 4.

### Phase 4 - Backend Rationalization and Merge

This phase exists to prevent AI and Shell from becoming two separate worker
backends with similar-but-divergent lifecycle behavior. The temporary Phase 3
Shell path must be reconciled here before the feature is considered stable.

Process:

- Characterize the current AI backend before moving code: queue mutation,
  synthetic ticket creation, `Assigned -> In Progress` transition, output
  streaming, retries, timeout, stop, yank, pass/handoff/random disposition,
  watch-column refill, Socket.IO events, and focus output catch-up.
- Introduce a shared `WorkerRunController` that owns task acquisition,
  synthetic ticket creation, status transitions, retry/backoff, queue advance,
  disposition dispatch, process registration, and emits.
- Move the current AI worker onto the shared controller behind an `AIWorkerType`
  adapter. The old AI-specific entry point may remain as a compatibility
  wrapper, but it must delegate immediately to the shared controller.
- Move Shell onto the same controller. The Shell adapter may provide argv, env,
  cwd, input delivery, artifact storage, and result parsing only.
- Remove or quarantine duplicate lifecycle helpers after both AI and Shell pass
  parity tests. No second queue runner, retry handler, process registry, output
  stream path, or disposition implementation may remain.
- Keep the Shell kill switch wired until the shared controller runs both AI and
  Shell and the parity suite is green. After that, keep it only if it remains
  useful as an operator-facing recovery control.

Regression-minimizing tests:

- AI characterization tests for the current happy path, error/retry path,
  timeout path, manual empty-queue synthetic ticket, stop, yank, process-tree
  cleanup, watch-column refill, and each disposition form.
- Event-order tests asserting `task:created`, `task:updated`, `layout:updated`,
  `worker:output`, and `worker:output:done` are emitted in the same observable
  order for AI before and after migration.
- Golden ticket tests comparing final ticket frontmatter/body for AI runs before
  and after migration, including output blocks and retry history.
- Shared-controller tests that run the same lifecycle cases with an AI test
  adapter and a Shell test adapter.
- No-duplication tests or static checks proving Shell does not call a separate
  process registry, retry implementation, queue advancement path, or
  disposition dispatcher.
- End-to-end smoke tests that run one AI worker and one Shell worker through the
  same board flow in a single workspace.

Done when:

- `start_worker()` is a worker-type dispatch wrapper, not an AI backend.
- AI and Shell both call the same controller for lifecycle transitions.
- Existing AI tests pass without weakening assertions.
- New Shell tests cover only Shell-specific adapter behavior plus shared
  lifecycle parity.

### Phase 5 - Shell Worker Frontend

- Add worker type selection to Create Worker.
- Add Shell-specific config fields.
- Add Shell examples picker.
- Add plaintext and export/transfer warnings.
- Render Shell run history/output blocks.
- Render unknown types as disabled occupied cards.

### Phase 6 - Hardening and E2E

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

2. **Synthetic ticket visibility.** The spec defines generated titles, tags,
   body metadata, and run keys. Design still needs to settle the visual
   treatment and short copy that makes synthetic tickets obvious on the board
   without making them feel like user-authored work.

3. **Artifact retention policy.** Sidecar stdout/stderr artifacts keep ticket
   bodies bounded, but the spec does not yet define retention age, maximum
   workspace log size, pruning behavior, or whether export should include
   worker-run artifacts. Pick defaults before enabling high-frequency scheduled
   Shell workers.

4. **Workspace export warning UX.** The spec requires warnings for Shell config
   exposure in export/team/transfer flows. The exact UI copy and confirmation
   mechanics need design, especially for bulk "export all" flows.

5. **Shell availability on minimal systems.** POSIX assumes `/bin/sh`; Windows
   assumes `cmd.exe`. If Bullpen later runs in restricted containers, expose a
   startup health check that marks Shell worker creation unavailable when no
   shell can be launched.

6. **Windows parity for examples.** The v1 examples are mostly POSIX-oriented.
   Before calling the example set complete, add at least one Windows-native
   example or document why Python-based examples are the supported cross-platform
   path.

---

## 7. Deferred Features

- Worktree support for Shell workers.
- Auto-commit / auto-PR on Shell worker success.
- Per-workspace capability controls beyond the current auth/write model.
- Secret env vars backed by OS keychain or a server-side secret store.
- Opt-in Shell access to Bullpen MCP tools or a short-lived MCP token.
- Long-lived Tool worker type that speaks MCP/JSON-RPC to a subprocess.
- Eval worker implementation.

---

## 8. Deferred Feedback

The review feedback was incorporated except for two recommendations that conflict
with product direction. The second-pass feedback was incorporated in full.

1. **Make manual empty-queue Shell runs a no-op.** Not accepted. Manual Shell
   runs intentionally use the same rules as AI workers and synthesize a ticket
   when no queued ticket exists. This supports commands that import an external
   ticket into Bullpen and commands such as restarting a test server. The UX must
   make ticket creation explicit instead of disabling the action.

2. **Require AI migration before any Shell backend work lands.** Not accepted as
   written. Shell may land first and be enabled by default so its requirements
   can be validated in normal use. The backend rationalization phase remains
   mandatory, and any temporary Shell-only lifecycle shim must be isolated and
   removed during that phase. The feature flag is retained as a
   disaster-recovery kill switch, not as the primary rollout mechanism.
