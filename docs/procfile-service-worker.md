# Procfile-Backed Service Workers

## Summary

This proposal adds a **Procfile-backed mode** to the existing Service worker
architecture. The goal is to let Bullpen run the same committed process command
that a repo already uses for deployment, without copying that command into
Bullpen config and letting it drift.

This is **not** a new top-level worker type. It is a new **command source**
for `type: "service"` workers.

The implementation should:

- keep `type: "service"` as the only long-running process worker type,
- add a Service-only `command_source: "manual" | "procfile"`,
- add a Service-only `procfile_process` selector,
- add a Service-only `port` field that seeds `PORT` into the child env,
- resolve Procfile commands through a shared server-side helper used by both
  runtime and UI preview,
- re-read `<cwd>/Procfile` on every start/restart,
- and preserve the existing Service worker lifecycle, health, logging, ticket
  order, and restart semantics.

---

## Goals

- Make Procfile-based repos near-zero-config in Bullpen.
- Use the committed `Procfile` as the source of truth for what to run.
- Avoid creating a parallel Bullpen-only command string that drifts from repo
  config.
- Fit cleanly into the existing Service worker implementation in
  [`server/service_worker.py`](../server/service_worker.py).

## Non-goals

- No new top-level worker type such as `type: "procfile"`.
- No extension of this feature to Shell, AI, or Eval workers in v1.
- No `.env` loading, buildpack emulation, or `release:` phase support.
- No support for running multiple Procfile entries from one worker.
- No path selection beyond `<cwd>/Procfile`.

---

## Architectural Decision

### Chosen shape

Procfile support is modeled as:

- `type: "service"`
- `command_source: "manual" | "procfile"`

with additional Service-only fields:

- `procfile_process`
- `port`

### Why this shape fits Bullpen

Bullpen's worker architecture treats `type` as a primary identity. Validation,
normalization, serialization, UI branching, copy/paste, transfer, team
save/load, export/import, and runtime dispatch all key off that field today in
[`server/worker_types.py`](../server/worker_types.py).

Creating a new top-level `procfile` worker type would duplicate much of the
existing Service worker behavior for no architectural benefit. Procfile mode is
not a new supervision model; it is a different way to produce the command
string that the Service worker runs.

So the correct abstraction is:

- **Service worker** = lifecycle owner
- **Manual vs Procfile** = command source

---

## User Story

If a repo has:

```Procfile
web: gunicorn -w $WEB_CONCURRENCY -b 0.0.0.0:$PORT app:wsgi
worker: rq worker
```

the user should be able to:

1. create or convert a Service worker,
2. set `command_source = procfile`,
3. choose `web`,
4. set `port = 3000`,
5. preview the resolved command,
6. start the service,

and Bullpen should execute the resolved `web` line using the existing Service
worker runtime.

---

## Config Model

### Service worker fields

Add these Service-only fields to normalized worker slots:

| Field | Type | Default | Notes |
|---|---|---:|---|
| `command_source` | string | `"manual"` | `"manual"` or `"procfile"` |
| `procfile_process` | string | `"web"` | Used only when `command_source == "procfile"` |
| `port` | int or null | `null` | Injected as `PORT` for Service workers |

Existing Service fields remain unchanged:

- `command`
- `cwd`
- `pre_start`
- `ticket_action`
- `startup_grace_seconds`
- `startup_timeout_seconds`
- `health_type`
- `health_url`
- `health_command`
- `health_interval_seconds`
- `health_timeout_seconds`
- `health_failure_threshold`
- `on_crash`
- `stop_timeout_seconds`
- `log_max_bytes`
- `env`

### Semantics

- If `command_source == "manual"`, Bullpen behaves like today and uses
  `worker["command"]`.
- If `command_source == "procfile"`, Bullpen ignores `worker["command"]` at
  runtime and resolves the raw command from `<cwd>/Procfile`.
- `command` is still persisted so switching back to manual mode restores the
  prior command text.
- `port` is scoped to Service workers only in v1.

### Normalization rules

`normalize_worker_slot()` should:

- default `command_source` to `"manual"` for Service workers,
- coerce invalid values back to `"manual"`,
- default `procfile_process` to `"web"`,
- normalize blank `procfile_process` back to `"web"`,
- normalize `port` to `None` when blank/missing,
- clamp `port` to valid integer range only at validation time, not by silently
  changing invalid values to a guessed port.

### Serialization / persistence

The new fields must survive all existing persistence paths:

- layout save/load
- browser round trip
- copy/paste
- team save/load
- transfer
- export/import
- app restart

This is required behavior, not an implementation detail.

---

## Procfile Discovery

Bullpen always reads Procfile content from:

```text
<resolved worker cwd>/Procfile
```

where worker `cwd` uses the same containment rules the Service worker already
uses today:

- relative to workspace root,
- realpath must remain inside the workspace,
- symlink escapes rejected,
- missing directories rejected.

There is intentionally **no custom Procfile path field** in v1.

Rationale:

- keeps config minimal,
- keeps the feature aligned with existing deploy conventions,
- avoids introducing a second path-validation surface.

---

## Procfile Parsing

### Accepted format

Bullpen parses a Procfile as line-oriented text:

- ignore blank lines,
- ignore lines whose first non-whitespace char is `#`,
- parse entries matching `^([A-Za-z0-9_-]+):\s*(.+)$`.

### Selection rules

- If `procfile_process` is found exactly once, use that command.
- If it appears more than once, use the first and log a warning.
- If it does not appear, start fails with:

```text
Procfile has no '<name>:' process
```

- If the Procfile file does not exist, start fails with:

```text
Procfile not found in <cwd>
```

### Explicitly unsupported in v1

- multiline continuation
- buildpack-specific parsing rules
- shell heredocs spanning lines
- include/import behavior

The resolved line is treated as the raw command string passed to the existing
shell-based Service worker execution path.

---

## Command Resolution

### Shared resolver

Add a single server-side helper responsible for:

1. resolving worker `cwd`,
2. locating `<cwd>/Procfile`,
3. parsing process entries,
4. selecting `procfile_process`,
5. building the child env,
6. interpolating the command,
7. returning both raw and resolved command metadata.

This helper must be used by:

- runtime start/restart,
- UI preview,
- UI process-name dropdown population.

The frontend must not implement its own Procfile parser or interpolation logic.

### Proposed return shape

Something like:

```json
{
  "cwd": "/abs/path/to/repo",
  "procfile_path": "/abs/path/to/repo/Procfile",
  "process_names": ["web", "worker"],
  "selected_process": "web",
  "raw_command": "gunicorn -w $WEB_CONCURRENCY -b 0.0.0.0:$PORT app:wsgi",
  "resolved_command": "gunicorn -w 2 -b 0.0.0.0:3000 app:wsgi",
  "warnings": ["Procfile process 'web' appears multiple times; using first entry."]
}
```

---

## Environment and Interpolation

### Scope

Interpolation is **Service-worker-only** in v1.

It applies to:

- manual Service commands
- Procfile-resolved Service commands
- Service `pre_start`
- optionally Service shell health checks if implemented through the same helper

It does **not** apply to:

- Shell workers
- AI workers
- Eval workers

### Env assembly

Continue to build the child env using the existing Service worker flow:

1. minimal inherited env
2. Bullpen Service vars
3. ticket-derived vars
4. configured env rows

Insert `PORT` into that Service child env when `worker["port"]` is set.

Recommended ordering:

1. `_minimal_env()` baseline
2. `PORT=<port>` if present
3. Bullpen-injected `BULLPEN_*`
4. ticket env
5. configured user env overrides

That preserves the current invariant that explicit user env wins.

### Interpolation behavior

Before spawn, Bullpen interpolates `$VAR`, `${VAR}`, and `$$` against the final
child env.

Rules:

- `$VAR` and `${VAR}` substitute from the final env
- undefined vars become `""`
- `$$` becomes literal `$`
- interpolation runs once per start/restart
- Procfile is re-read and re-resolved on each start/restart

### Logging

On start, Bullpen should log the resolved command it is about to execute.

If interpolation references an unset variable, log a warning such as:

```text
[bullpen] unresolved Procfile variable $FOO; substituting empty string
```

If the resolved command contains secret-looking values, log the command with
those substituted values redacted.

### Why interpolate in Bullpen instead of relying on `/bin/sh -c`

- gives the user a trustworthy preview,
- keeps runtime behavior aligned with preview behavior,
- lets logs show what Bullpen actually ran,
- avoids `$PORT` behaving differently on Windows shells.

---

## Runtime Integration

### Start sequence

In `ServiceWorkerController._start_sequence()`:

1. load normalized Service worker config
2. resolve `cwd`
3. build child env including `PORT`
4. resolve raw command:
   - manual mode: `worker["command"]`
   - Procfile mode: selected Procfile entry
5. interpolate command using the shared resolver/helper
6. run `pre_start` through the same interpolation flow
7. continue through existing spawn, log, health, and monitor paths

### What stays unchanged

- process supervision model
- `subprocess.Popen(..., _command_argv(command))`
- service log file ownership and rotation
- health checks
- ticket order flow
- crash handling
- stop timeout behavior
- no re-adoption after Bullpen restart
- no auto-start on Bullpen restart

### Config hash

Include these fields in `_service_config_hash()`:

- `command_source`
- `procfile_process`
- `port`

`command` must remain in the hash too, because switching back to manual mode
should still see command edits as config changes.

---

## Validation Rules

Validation should be explicit and mode-aware.

### Manual Service mode

When `command_source == "manual"`:

- `command` is required
- `procfile_process` may be stored but is not used

### Procfile Service mode

When `command_source == "procfile"`:

- `procfile_process` is required logically, but may normalize to `"web"`
- `command` is not required
- missing Procfile is not a save-time validation error if the worker is merely
  stored; it is a preview/start-time resolution error

### Shared Service validation

- `port` must be integer `1..65535` when provided
- reserved `BULLPEN_*` env names still rejected
- existing health-check validation unchanged

This split matters because the user may save a Procfile-backed Service worker in
one environment and start it later after the repo changes.

---

## UI Proposal

### Worker editor

For `type: "service"` workers:

- add **Command Source** select:
  - `Manual command`
  - `Procfile`
- add **Port** field near the top of the Service config
- when `command_source == "manual"`:
  - show the existing Command textarea
- when `command_source == "procfile"`:
  - hide the Command textarea
  - show a **Process name** picker populated from the server helper
  - show Procfile status/path info
  - show resolved-command preview

### Preview behavior

The resolved-command preview should:

- come from the backend helper, not client-side parsing
- refresh when `cwd`, `procfile_process`, `port`, or env rows change
- redact secret-looking values in display
- show parse/resolution errors inline

### Disabled / degraded states

- If `<cwd>/Procfile` is missing, Procfile mode may still be selectable if the
  user wants to save config before the file exists, but preview/start must show
  the concrete missing-file error.
- If process names cannot be loaded, keep the current `procfile_process` value
  visible and show resolution errors rather than silently resetting it.

This is better than greying the whole mode out, because it preserves stored
config and behaves predictably when repos are in flux.

### Worker card

Recommended card additions for Service workers:

- optional badge showing `Procfile:web` or `Procfile:worker`
- optional `:3000` display when `port` is set

These are nice-to-have, not blockers for v1.

---

## API / Backend Contract

If the editor needs live Procfile inspection and preview, add a narrow endpoint
or Socket.IO event such as:

```text
service:procfile:preview
```

or an HTTP endpoint scoped to workspace + slot draft state.

Input should include enough draft fields to preview unsaved changes:

- `cwd`
- `command_source`
- `procfile_process`
- `port`
- `env`
- `command`
- `pre_start` if previewing that too

Output should include:

- discovered process names
- raw command
- resolved command
- warnings
- errors

The preview path must call the same resolver used by start/restart.

---

## Compatibility and Migration

### Existing Service workers

Existing Service workers should continue to normalize as:

- `command_source = "manual"`
- `procfile_process = "web"`
- `port = null`

No migration step should be required beyond normalization defaults.

### Existing commands containing `$VAR`

If interpolation is added for all Service commands, existing Service workers
that already rely on shell expansion will continue to work in most cases.
However, because this introduces new behavior around `$$` and unset-variable
logging, it should be treated as a deliberate Service-worker change and called
out in release notes.

---

## Testing Requirements

This feature should be tested as an extension of the existing Service-worker
matrix, not as an isolated parser feature.

### Resolver tests

- parse blank/comment lines correctly
- select the right process entry
- duplicate process name uses first and warns
- missing Procfile errors cleanly
- missing process errors cleanly
- interpolation expands `$VAR`, `${VAR}`, `$$`
- unset variable warning emitted
- redaction works in preview/logged command

### Worker normalization / validation tests

- Service worker defaults for new fields
- invalid `command_source` normalizes to manual
- `port` validation
- manual mode still requires `command`
- Procfile mode does not require `command`

### Runtime tests

- manual Service start still works unchanged
- Procfile-backed Service start resolves and runs selected command
- re-read Procfile on restart picks up file changes
- `port` seeds `PORT`
- configured env can override `PORT`
- preview resolution matches actual start resolution
- config hash changes when `command_source`, `procfile_process`, or `port`
  changes

### Persistence tests

- copy/paste
- transfer
- export/import
- team save/load
- restart durability

### UI tests

- Service modal shows correct controls per `command_source`
- preview updates on field edits
- preview errors shown inline
- process picker populated from backend response

---

## Implementation Proposal

### Phase 1: Backend data model

- extend Service normalization in `server/worker_types.py`
- extend Service validation
- include new fields in serialization and config hash paths

### Phase 2: Shared resolver

- add a dedicated resolver module or helper for:
  - Procfile path resolution
  - Procfile parsing
  - env assembly helpers
  - interpolation
  - preview metadata

Recommended location:

- `server/service_worker.py` if kept tightly scoped
- or `server/service_worker_procfile.py` if separation improves readability

### Phase 3: Runtime integration

- wire resolver into `_start_sequence()`
- use it for manual and Procfile Service command resolution
- log resolved command with redaction

### Phase 4: UI

- update `static/components/WorkerConfigModal.js`
- add preview/process-list fetch path
- add inline error/warning display

### Phase 5: Persistence + regression coverage

- add normalization/persistence tests
- add runtime tests
- add modal tests if present in current frontend test style

---

## Open Issues

These are the remaining design questions that should be resolved before coding
or during implementation with an explicit decision.

1. Should Procfile mode be saveable when `<cwd>/Procfile` is currently missing,
   or should save-time validation block it?

   Recommendation: allow save, fail preview/start with explicit error.

2. Should interpolation apply to Service `health_command` as well as `command`
   and `pre_start`?

   Recommendation: yes, if implemented through the same helper, because users
   will reasonably expect `PORT` to work there too.

3. Should the worker card show a Procfile badge and port in v1, or should that
   wait for a follow-up UI pass?

   Recommendation: optional for v1; functional editor/runtime support matters
   more.

4. How aggressive should redaction be in preview/log output?

   Recommendation: use the existing secret-marker heuristic first, and avoid
   inventing value-pattern redaction in this feature unless needed.

5. Should duplicate Procfile process names be merely warnings, or hard errors?

   Recommendation: warning + first match, to stay tolerant of imperfect repos.

6. Should preview resolve against unsaved env rows and port values?

   Recommendation: yes; otherwise preview is not very useful.

7. Should `PORT` remain overrideable by explicit user env rows?

   Recommendation: yes, to preserve the existing "configured env wins"
   principle.

---

## Recommended Decision

Proceed with this feature as:

- a **Procfile-backed command source for Service workers**,
- **Service-only** in scope for v1,
- with a **shared backend resolver** powering both preview and runtime,
- and with explicit persistence, validation, and regression coverage across the
  existing Service-worker lifecycle.
