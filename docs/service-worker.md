# Service Workers

Service workers supervise a single long-running process from a worker grid slot.
Unlike AI and Shell workers, which run a command to completion for each ticket,
a Service worker's job is to keep one configured process under Bullpen control:
start it, stop it, restart it, stream logs, detect crashes, and show health.

The ticket is not the service. The **Service worker is the service**. Tickets are
**service orders**: a ticket can ask the Service worker to restart the process as
part of a normal workflow, then move on through the board. Manual controls can
also start, stop, or restart the service with no ticket involved.

The motivating use case: Bullpen runs inside a Docker container that also hosts
an application under development. The container exposes a second proxied TCP
port for that application. A Service worker lets the user start, stop, and
restart the hosted application from Bullpen, with the worker's log pane acting
as the live server log.

This document is the design spec for a first implementation. It favors a
conservative v1: services die with Bullpen, nothing is automatically re-adopted
or auto-started after restart, and the service remains easy to reason about.

---

## Concept

A Service worker owns at most one subprocess per worker slot.

- The worker's state reflects the **process state**: stopped, starting,
  running, healthy, unhealthy, stopping, or crashed.
- Ticket assignment is a service order, usually "restart the service for this
  ticket, then route the ticket onward."
- Manual Start / Stop / Restart actions operate on the Service worker directly
  and do not require a queued ticket.
- Output is streamed live into the worker focus/log pane and persisted to a
  bounded log file under `.bullpen/logs/services/`.
- Bullpen owns the process group, kill semantics, crash detection, health
  checks, and log retention. Users do not configure PID files, `nohup`, detach
  behavior, or log paths.

This replaces the "sack of scripts" pattern (one worker to start, one to stop,
one for status, coordinating through a PID file in user space) with one
first-class worker type that handles supervision once.

---

## Service Orders

Service workers support two primary flows.

### Manual Control

The user opens the worker menu or service detail pane and clicks **Start**,
**Stop**, or **Restart**.

- No ticket is required.
- Bullpen records the control action in the service event log.
- The service log pane receives pre-start output, process output, health
  changes, stop events, and crash events.
- Manual actions do not create synthetic tickets in v1.

### Ticket Flow Control

A ticket can be dropped onto or routed to a Service worker as part of a larger
board flow, for example:

```text
Spec -> Spec Review -> Implementation -> Validation -> PR Generation -> Test Server Restart
```

When a ticket reaches the Service worker:

1. The worker treats the ticket as a service order.
2. The configured **Ticket action** is executed. V1 default:
   `start-if-stopped-else-restart`.
3. Bullpen injects ticket data into the service environment for the pre-start
   and main command.
4. The service order succeeds when the requested action completes and the
   service reaches the required readiness point.
5. The ticket moves through the worker's configured Output route.

The service process remains running after the ticket leaves the worker queue.
The ticket is not bound to the service forever.

### Ticket Action

V1 supports:

- `start-if-stopped-else-restart` (default): start the service when stopped;
  otherwise restart it.
- `restart`: stop the service if running, then start it.
- `start-if-stopped`: start only when stopped; if already running, treat the
  order as successful after the readiness check. If health is configured and
  the service is currently unhealthy, wait for a healthy check bounded by
  `startup_timeout_seconds`; do not succeed on process liveness alone.

Deferred actions:

- `stop`
- `restart-if-command-changed`
- custom pre-start-only orders

### Readiness Point

The service order completes at one of these points:

- If no health check is configured: when the main process has spawned and
  remains alive for `startup_grace_seconds` (default 2).
- If a health check is configured: only when the first health check succeeds.

`startup_timeout_seconds` (default 60) covers the entire service order attempt
from the start of pre-start through readiness. A hung pre-start, slow spawn,
startup grace wait, or first-health wait all consume the same deadline.

If the process exits, pre-start fails, or readiness is not reached before that
deadline, the service order fails. The ticket goes through the normal worker
retry/backoff policy and then to Blocked.

---

## Configuration

Reserve `type: "service"` in `layout.json`. Do not use a separate `kind` field;
Bullpen's worker-type registry, copy/paste, transfer, team save/load, and
unknown-type preservation all use `type`.

Fields in the create/configure worker dialog:

- **Command** (required): a single shell-interpreted command line, e.g.
  `python3 hosted-app.py --port=$HOSTED_PORT`. Executed via `/bin/sh -c` on
  POSIX and `cmd.exe /c` on Windows.
- **Working directory**: relative to the workspace root. Same containment rules
  as Shell workers; realpath must stay inside the workspace and symlink escapes
  are rejected.
- **Environment**: key/value rows merged on top of the same minimal inherited
  env model as Shell workers.
- **Pre-start** (optional): a shell command run to completion before the main
  command. Typical use: `git fetch && git checkout "$BULLPEN_SERVICE_COMMIT"`.
  Nonzero exit aborts the start, captures output in the service log, and marks
  the service order failed.
- **Ticket action**: `start-if-stopped-else-restart`, `restart`, or
  `start-if-stopped`.
- **Output**: normal Bullpen disposition route for service-order tickets
  (`review`, `done`, `worker:NAME`, `pass:RIGHT`, etc.).
- **Max retries**: retry policy for service-order tickets when start/restart
  fails.
- **Startup grace seconds**: time the process must stay alive when no health
  check is configured. Default 2.
- **Startup timeout seconds**: max time to wait for readiness. Default 60.
- **Health check** (optional): HTTP or shell check. See
  [Health checks](#health-checks).
- **On crash**: `stay-crashed` for v1. Automatic restart is deferred.
- **Stop timeout seconds**: graceful stop window before force-kill. Default 5.
- **Log max bytes**: max service log size before rotation. Default 5 MiB.

No Start on boot in v1. No re-adoption in v1. Services terminate when Bullpen
terminates.

### Injected Environment

Bullpen injects namespaced variables for pre-start, main command, and shell
health checks:

```text
BULLPEN_WORKSPACE
BULLPEN_SERVICE_SLOT
BULLPEN_SERVICE_NAME
BULLPEN_SERVICE_ORDER_ID
BULLPEN_SERVICE_COMMIT
BULLPEN_TICKET_ID
BULLPEN_TICKET_TITLE
BULLPEN_TICKET_STATUS
BULLPEN_TICKET_PRIORITY
BULLPEN_TICKET_TAGS
```

`BULLPEN_SERVICE_ORDER_ID` is the ticket id for ticket-triggered orders and a
generated event id for manual actions. `BULLPEN_TICKET_*` values are blank for
manual actions.

`BULLPEN_SERVICE_COMMIT` is intentionally conservative in v1:

1. If the ticket has explicit frontmatter `commit`, use it.
2. Otherwise, if the ticket body contains a line matching `commit: <7-40 hex>`,
   use the first match. The `commit` label and hex characters are
   case-insensitive.
3. Otherwise, leave it blank.

Do not scan for the first arbitrary hex string in the body; that creates
surprising matches.

Configured env rows override inherited env, but `BULLPEN_MCP_TOKEN` is never
accepted. If a configured env row uses a Bullpen-reserved name, validation fails.

---

## What the User Sees

The worker card is the center of the Service worker experience: it holds the
configuration entry point, service controls, activation menu, state display,
and ticket drop target. The focus/detail pane can offer a larger log view, but
users should be able to understand and control the service from the card.

The worker card shows service state instead of ordinary queued/idle copy:

```text
running · healthy · pid 48213 · up 12m
```

Color:

- green: healthy
- yellow: starting, running without health yet, or unhealthy
- red: crashed
- grey: stopped

The worker card menu provides:

- **Start**
- **Stop**
- **Restart**
- **View Logs**
- **Configure**

The focus/detail pane may repeat Start / Stop / Restart beside the larger log
view for convenience, but the worker card remains the primary control surface.

The log pane reuses the existing worker output/focus component where practical.
Opening the log pane sends an immediate catch-up payload: current service state
plus the latest log tail.

Editing Command, Env, Pre-start, or Health Check while the service is running
shows "Restart to apply." The server stores enough runtime metadata to compare
the active config hash with the current configured hash.

If an edit lands while a ticket-triggered service order is already in progress,
that order continues with the config snapshot it started with. The saved config
becomes pending and applies to the next manual start/restart or ticket order.
This avoids changing command, env, health, or timeout behavior underneath an
in-flight operation.

If tickets are queued behind the active order, the UI should show that pending
config will apply to those queued orders. V1 does not snapshot config at
enqueue time; a service order captures config only when it becomes active.

When a ticket triggers a restart, the ticket detail should show a service-order
history row with the service action, final outcome, duration, and log artifact
path. The ticket should not become "the service"; it should continue through
its normal board route when the order succeeds.

---

## State Machine

```text
No health check:

 stopped ──Start/Order──▶ starting ──startup grace──▶ running
    ▲                         │                         │
    │                         ▼                         ▼
    └──── stopped ◀── stopping ◀────── Stop       unexpected exit
                                                      │
                                                      ▼
                                                   crashed

Health check configured:

 stopped ──Start/Order──▶ starting ──first healthy check──▶ healthy
    ▲                         │                              │  ▲
    │                         ▼                              ▼  │
    └──── stopped ◀── stopping ◀────── Stop              unhealthy
                                                         │
                                                         ▼
                                                   unexpected exit
                                                         │
                                                         ▼
                                                      crashed
```

Notes:

- `starting` covers pre-start, spawn, startup grace, and initial health check.
- `healthy` and `unhealthy` only apply when a health check is configured.
- `running` is used only for the no-health terminal alive state after startup
  grace.
- Health checks can move a service between `healthy` and `unhealthy` for as
  long as the process remains alive.
- `crashed` means the process exited without an explicit Stop or failed during
  pre-start/startup.
- `stay-crashed` is the only v1 crash policy.

Ticket status is separate from service state. A service-order ticket can leave
the worker queue while the service keeps running.

---

## Server-Side Design

Suggested module: `server/service_worker.py`.

One runtime controller per `(workspace_id, slot_index)`:

```python
class ServiceWorkerController:
    def start(self, *, order=None): ...
    def stop(self, *, order=None, timeout=5): ...
    def restart(self, *, order=None): ...
    def state_snapshot(self): ...
    def log_tail(self, max_bytes=65536): ...
```

Where `order` is either:

- a ticket service order, with ticket id and disposition context
- a manual control event, with generated id and actor context when available

The controller should integrate with the existing worker-type registry as
`type: "service"`. It should reuse existing Shell/shared worker code where
possible:

- cwd confinement
- minimal env and secret filtering
- process group/tree termination
- live output buffering/catch-up
- Socket.IO workspace scoping
- layout normalization/copy/paste/transfer/team paths

Service workers need their own lifecycle controller because they do not finish
by moving the service process through a disposition. Only the **service order**
finishes.

### Runtime State

Desired config lives in `layout.json` with the worker slot.

Observed runtime state is not part of layout save/load, copy/paste, transfer,
or team export. Store it in memory and, where needed for cleanup/debugging, in a
versioned runtime file:

```json
{
  "version": 1,
  "services": [
    {
      "workspace_id": "workspace-id",
      "slot_index": 3,
      "pid": 48213,
      "pgid": 48213,
      "started_at": "2026-04-20T15:30:00Z",
      "command_hash": "sha256:...",
      "config_hash": "sha256:...",
      "log_path": ".bullpen/logs/services/slot-3/service.log",
      "state": "running"
    }
  ]
}
```

This file is for cleanup and debugging in v1, not re-adoption. On Bullpen
startup, stale entries should be marked stopped/unknown and cleared after
best-effort cleanup checks.

### Config Hash

The Service controller computes a canonical `config_hash` from the fields that
affect process behavior, readiness, routing, and retention:

- `command`
- `cwd`
- `env`
- `pre_start`
- `ticket_action`
- `disposition`
- `max_retries`
- `startup_grace_seconds`
- `startup_timeout_seconds`
- `health`
- `health_interval_seconds`
- `health_timeout_seconds`
- `health_failure_threshold`
- `on_crash`
- `stop_timeout_seconds`
- `log_max_bytes`

Canonicalization rules:

- normalize through `normalize_worker_slot()` first
- serialize only the hash field set above
- sort object keys
- preserve env row order after normalization, because duplicate shell env keys
  are order-sensitive and the last value wins
- include explicit defaults for absent optional fields
- exclude cosmetic and runtime fields such as name, row, col, task queue,
  process state, started time, pid, and active order id

The UI compares current `config_hash` with runtime `active_config_hash` to show
"Restart to apply." The helper should have focused tests so cosmetic edits do
not make the banner flicker.

### Spawn

POSIX:

- Launch with `start_new_session=True`.
- Stop with `SIGTERM` to the process group, wait `stop_timeout_seconds`, then
  `SIGKILL` the group.
- Pre-start commands use the same process-group treatment as the main service
  process, so cancellation or timeout kills the whole pre-start tree.

Windows:

- Launch with `CREATE_NEW_PROCESS_GROUP`.
- Stop first attempts a graceful console break when supported:
  `proc.send_signal(signal.CTRL_BREAK_EVENT)`, then waits
  `stop_timeout_seconds`.
- If the process is still alive, fall back to the existing
  `taskkill /T /F /PID` tree cleanup behavior used by Shell workers.
- Pre-start commands use the same process-group/process-tree cleanup path as
  the main service process.

Windows support is in scope for v1. The exact graceful-stop sequence still
needs direct platform testing, but the v1 behavior is explicit: graceful
best-effort first, forceful tree cleanup second.

### Logging

Service logs are file-backed from the moment the process starts. Do not rely on
parent-owned pipes as the only copy of stdout/stderr.

Recommended v1 design:

- Open `.bullpen/logs/services/slot-{slot_index}/service.log` in append mode.
- Merge stderr into stdout at subprocess launch (`stderr=STDOUT`) for the main
  service and pre-start command, then write the single combined stream to the
  log. This preserves stream order at the level the OS provides and avoids two
  reader threads tearing lines into the same file.
- The reader thread writes each line to the log and emits live `service:log`
  batches.
- `service:tail` reads the current log files by path on demand for catch-up;
  no long-lived tailer holds the log file open.

This design is also compatible with a future re-adoption feature.

Retention is in scope for v1:

- Default `log_max_bytes`: 5 MiB.
- Keep current log plus one rotated suffix (`service.log.1`).
- Rotate on start and when appending would exceed the cap. Rotation happens
  under the service log writer lock: close current file, move current to
  `service.log.1`, open a fresh `service.log`, then emit a short rotation
  marker. This avoids POSIX unlinked-inode tails and Windows rename failures.
- Never include logs in git by default; `.bullpen/logs/` remains gitignored.

### Monitor

A monitor thread waits for process exit.

On exit:

- record exit code, duration, timestamp, and order id if any
- if state was `stopping`, transition to `stopped`
- otherwise transition to `crashed`
- emit a state update
- append a service history entry to the active order ticket if the crash affects
  a pending order

Unexpected crashes after a ticket has already completed should be recorded in
the service log and emitted to the UI, but they should not mutate an old ticket.

### Socket Events

Commands from UI:

```text
service:start   {workspaceId, slot}
service:stop    {workspaceId, slot}
service:restart {workspaceId, slot}
service:tail    {workspaceId, slot, max_bytes}
```

Ticket assignment uses the existing worker assignment path. If a ticket is
queued on a Service worker and the worker activation says it should run, the
Service worker creates a service order and performs the configured ticket
action.

Server emits:

```text
service:state {workspaceId, slot, state, health, pid, started_at, exit_code,
               config_hash, active_config_hash}
service:log   {workspaceId, slot, lines, catchup=false, reset=false}
```

Service logs use separate `service:*` events because they have different
lifecycle rules from finite AI/Shell worker output. They still must follow the
same workspace room scoping and catch-up conventions.

`service:tail` responds with `service:log` using `catchup: true` and
`reset: true`. The client replaces its current service log buffer for that slot
before appending the returned lines. Live `service:log` batches omit both flags
or set them false and are appended.

### Ticket Cancellation

If a service-order ticket is yanked, archived, deleted, or otherwise removed
from the Service worker while its action is still pending, Bullpen treats that
as user cancellation of the service order.

V1 cancellation goals:

- cancel the pending service order and stop mutating the ticket
- emit a service-order-canceled state/log event
- leave the service in a known state when possible

Known-state policy:

- If cancellation happens before the service process was changed, leave the
  service as-is.
- If cancellation happens during pre-start, terminate the pre-start process and
  leave the main service in its previous state.
- If cancellation happens during a stop/start restart transition, finish the
  currently active process-tree operation before reporting cancellation. Do not
  abandon an unknown half-stopped process tree.

This is an area for careful implementation and tests, but the product intent is
clear: user cancellation should regain control and should not leave an orphaned
or unknowable process state.

---

## Ticket History and Audit

Service-order tickets should get structured history rows, similar in spirit to
Shell worker `worker_run` rows.

Events to record:

- `service_order_started`
- `service_order_succeeded`
- `service_order_failed`
- `service_order_retried`

Fields:

```yaml
history:
  - timestamp: "2026-04-20T15:30:00Z"
    event: "service_order_succeeded"
    worker_type: "service"
    worker_name: "Test server"
    worker_slot: 3
    task_id: "restart-test-server-Ab12"
    action: "restart"
    state: "healthy"
    health: "healthy"
    pid: 48213
    duration_ms: 4321
    exit_code: null
    reason: null
    log_artifact: ".bullpen/logs/services/slot-3/service.log"
    config_hash: "sha256:..."
```

Manual service controls should be logged in the service log and emitted to the
UI. They do not create tickets in v1.

---

## Health Checks

Health checks are optional.

Types:

- **HTTP**: URL must be `http://` or `https://`; any 2xx response is healthy.
- **Shell**: command exits 0 when healthy.

Config:

- `health_interval_seconds`: default 5
- `health_timeout_seconds`: default 2
- `health_failure_threshold`: default 3
- `startup_timeout_seconds`: default 60

HTTP checks:

- Follow no redirects by default in v1.
- Capture status code and short error reason.
- Limit URLs to local/private targets in v1. Accepted targets:
  - `localhost`
  - loopback IPv4/IPv6
  - RFC1918 IPv4 private ranges
  - IPv4 link-local `169.254.0.0/16`
  - IPv6 unique-local `fc00::/7`
  - IPv6 link-local `fe80::/10`
- Hostnames other than `localhost` are allowed only when every resolved address
  is in an accepted range at check time. Re-resolve each check and reject mixed
  public/private results. This keeps health checks aligned with local/dev-server
  use and avoids turning Bullpen into a general network probe.

Shell checks:

- Use the same cwd confinement and env construction as the main service.
- Capture stdout/stderr to the service log with a prefix.
- Apply a timeout.

Shell health checks use the same cwd confinement and Service environment as the
main command so checks can reference the same port/env settings. They still use
the same secret filtering and `BULLPEN_MCP_TOKEN` rejection rules.

---

## Shutdown Behavior

V1 policy: **cascade stop**.

When Bullpen exits cleanly or receives SIGTERM/SIGINT, it stops all running
Service workers:

1. snapshot the active service controllers
2. send graceful stop to all service process trees concurrently
3. wait until a single shutdown deadline equal to the maximum active
   `stop_timeout_seconds`
4. force-kill remaining process trees concurrently
5. write final state/log entries best-effort

The shutdown cascade is not serial. Stopping 10 services with a five-second
timeout should take roughly one timeout window, not 50 seconds.

Nothing starts automatically on Bullpen startup. No re-adoption in v1. No
double-forking or orphaned service survival.

Rationale: Bullpen is a development controller. If a user wants a persistent
test server outside Bullpen, they can run it in another shell. If they want
production persistence, they should deploy it under a real process supervisor.

Deferred possibilities:

- Re-adopt live service processes after Bullpen restart.
- Explicit "survive Bullpen restart" per-service option.
- Start on boot.
- Integration with external process supervisors.

When a workspace is removed while one of its services is running, Bullpen uses
the same cascade-stop policy scoped to that workspace before the workspace is
removed from the active project list. Service events emitted during teardown
remain scoped to that workspace.

---

## Security Model

Service workers execute arbitrary user-configured commands. They are not a
sandbox.

They inherit Shell worker guardrails:

- Working directory must resolve inside the workspace root; symlink escapes are
  rejected.
- Command strings are stored plaintext in `layout.json`.
- Env values are stored plaintext in `layout.json`.
- Logs are stored plaintext under `.bullpen/logs/services/`.
- No ticket-field interpolation into command strings.
- Minimal inherited env.
- Secret env filtering for names containing `TOKEN`, `KEY`, `SECRET`,
  `PASSWORD`, `CREDENTIAL`, or `PASSPHRASE`.
- `BULLPEN_MCP_TOKEN` is never inherited and cannot be configured.
- `.bullpen/logs/` remains gitignored by default.

Start / Stop / Restart require workspace write permission. Until Bullpen has
read-only roles, all authenticated workspace users are treated as editors; the
future serializer must redact Service command/env values for read-only viewers
the same way Shell values are redacted.

Deferred security hardening:

- CPU and memory limits.
- Per-workspace capability controls.
- Secret storage backed by keychain or encrypted store.
- More granular network egress policy for health checks.

---

## Implementation Scope

Backend:

- Add `ServiceWorkerType` with `type: "service"` to the worker-type registry.
- Extend slot normalization, serialization/redaction, copy/paste, transfer,
  team save/load, import/export, and unknown-type preservation for Service
  fields.
- Add `server/service_worker.py` or equivalent controller module.
- Integrate Service worker assignment into the existing `start_worker()`
  dispatch path while keeping service process lifecycle separate from ticket
  disposition.
- Reuse Shell/shared helpers for cwd/env/process cleanup where possible.
- Add service state/log Socket.IO events.
- Add startup/shutdown hooks in `create_app()` to initialize controllers and
  stop all services on shutdown.
- Add bounded log storage under `.bullpen/logs/services/`.

Frontend:

- Add Service tab to the Add Worker flow.
- Add Service-specific config fields.
- Add worker card state display.
- Add focus/detail pane controls: Start, Stop, Restart, View Logs.
- Show "Restart to apply" when current config differs from active config.
- Show plaintext command/env/log warnings.

Tests:

- Service slot normalization and round-trip through configure, duplicate,
  copy/paste, team save/load, transfer, export/import, and app restart.
- Manual start/stop/restart.
- Ticket-triggered restart routes ticket on success.
- Ticket-triggered failure retries then blocks.
- Process group/tree kill.
- Bullpen shutdown stops all services.
- Crash detection.
- Health success/failure transitions.
- Startup timeout.
- Log rotation/capping.
- Log catch-up for a newly opened browser/focus pane.
- Workspace scoping for events.
- Command/env redaction for read-only serialization.
- Windows process-tree cleanup behavior.

---

## Deferred Work

- Re-adopt services after Bullpen restart.
- Start on boot.
- Explicit survive-Bullpen-restart option.
- Automatic restart crash policy with exponential backoff.
- CPU and memory limits.
- Richer service-order actions beyond `start-if-stopped-else-restart`,
  `restart`, and `start-if-stopped`.
- Remote health-check policy controls.
- External supervisor integration.

Not planned:

- Multiple services per Service worker. Use multiple Service workers instead.

---

## V1 Decision Index

This is an index only; the body sections above are authoritative.

- Service workers ship with Windows support: [Spawn](#spawn) and
  [Windows stop semantics](#windows-stop-semantics).
- The Service worker is the service; tickets are service orders:
  [Service orders](#service-orders).
- One Service worker supervises at most one service process:
  [Concept](#concept).
- Default ticket action is `start-if-stopped-else-restart`:
  [Ticket action](#ticket-action).
- Ticket-triggered orders route onward only after readiness:
  [Readiness point](#readiness-point).
- Manual Start / Stop / Restart do not create tickets:
  [Manual control](#manual-control).
- Removing a ticket from an in-flight service order cancels that order:
  [Ticket cancellation](#ticket-cancellation).
- HTTP health checks are limited to local/private addresses:
  [Health checks](#health-checks).
- Service logs use separate `service:*` events:
  [Socket events](#socket-events).
- Desired Service configuration lives on the worker slot:
  [Runtime state](#runtime-state).
- The worker card is the primary Service UI surface:
  [What the user sees](#what-the-user-sees).
- Default log retention is current 5 MiB plus one 5 MiB rotated log:
  [Logging](#logging).

---

## V1 Issue Resolution

This pass turns most review issues into explicit v1 behavior.

### Private-Network Health Checks

Decision: HTTP health checks are local/private only.

Accepted targets are `localhost`, loopback IPv4/IPv6, RFC1918 IPv4 private
ranges, IPv4 link-local, IPv6 unique-local, and IPv6 link-local. Docker bridge
addresses are covered by the private IPv4 ranges in the default Docker setups
Bullpen is targeting.

Hostname handling:

- Parse and validate the URL before making the request.
- Reject redirects in v1.
- Resolve the hostname on every health check attempt.
- Allow the request only if every resolved address is in the accepted set.
- Reject mixed public/private DNS answers.
- Treat DNS failure during a check as an unhealthy result. Saving config does
  not require the hostname to resolve immediately.

Implementation note: put this in a small testable helper rather than embedding
it in the health-check loop. Python's `ipaddress` module covers the address
classification cleanly.

Tests:

- accepts `http://localhost:3000/`
- accepts `http://127.0.0.1:3000/`
- accepts RFC1918 targets such as `http://172.17.0.2:3000/`
- rejects public literals such as `http://8.8.8.8/`
- rejects hostnames resolving to public addresses
- rejects hostnames resolving to both private and public addresses
- rejects redirects without following them

### Windows Stop Semantics

Decision: Windows is supported in v1 with graceful best-effort followed by
forceful cleanup.

V1 stop sequence:

1. Launch with `CREATE_NEW_PROCESS_GROUP`.
2. Attempt `proc.send_signal(signal.CTRL_BREAK_EVENT)` when available.
3. Wait `stop_timeout_seconds`.
4. If still alive, run `taskkill /T /F /PID <pid>`.
5. Record whether the stop was graceful or forceful in the service log and
   service history row when a ticket order is active.

This mirrors the product expectation of a graceful stop window without making
the whole feature depend on perfect Windows console-control behavior. Direct
Windows testing is still required before the phase is closed.

Tests:

- process tree is cleaned up after forceful fallback
- service state becomes `stopped` after manual stop
- ticket order records forceful stop when fallback is needed
- shutdown cascade uses the same cleanup path

### Service-Order Concurrency

Decision: one active service operation per worker slot.

Rules:

- The controller has a per-slot operation lock.
- A Service worker may have many queued tickets, but at most one active service
  order.
- Additional tickets remain in `task_queue` until the active order completes.
- Re-entering `start_worker()` for the same Service worker while an order is
  active must not start a second process or mark the second ticket successful.
  Return/record `busy` to the caller, leave queued tickets in `task_queue`, and
  emit the current service state.
- After the active order completes, the normal worker advancement path starts
  the next queued ticket if activation allows it.
- Manual Start / Restart are rejected while a ticket order is active. The UI
  should disable them and the server should still enforce the rule.
- Manual Stop is rejected while a ticket order is active; ticket yank/removal is
  the cancellation path for ticket-triggered work.
- Manual Start / Stop / Restart are also serialized against each other by the
  same operation lock.

Cancellation:

- Removing the active ticket from the worker queue cancels the active order.
- Manual Stop is not the cancellation mechanism for an active ticket order in
  v1. Use ticket removal/yank for that because it preserves a clear audit path.
- A manual Start or Restart that becomes stuck in pre-start has no ticket to
  yank, so Manual Stop remains available for manual-initiated operations and
  means "cancel the current manual operation and restore a known service state."
- If a ticket is canceled while the controller is in a stop/start transition,
  the controller finishes the current process-tree operation before reporting
  cancellation.

Tests:

- two queued tickets execute service orders one at a time
- duplicate `start_worker()` calls do not start duplicate processes
- duplicate `start_worker()` calls leave later tickets queued rather than
  succeeding or failing them
- manual restart during an active ticket order is rejected server-side
- manual stop during a manual pre-start cancels the manual operation
- yanking the active ticket cancels the order and leaves a known service state

### Config Edits During Active Work

Decision: edits are allowed and become pending config.

Rules:

- Each operation captures a normalized config snapshot before it starts.
- The running process records `active_config_hash`.
- The current slot config records `config_hash`.
- If the hashes differ, the UI shows "Restart to apply."
- Active ticket orders keep using their snapshot until completion.
- Queued tickets that have not started yet use the newest config when they
  become active.

This lets users fix config without fighting the form, while avoiding surprising
mid-flight changes to command, env, health, timeouts, or routes.

Tests:

- editing command while running does not mutate the live process command
- card/detail UI shows pending config when hashes differ
- queued-ticket hint appears when pending config will affect queued orders
- next restart uses the edited config
- active ticket order history records the config hash it actually used

### Failure, Retry, and History Shape

Decision: service-order failure uses the existing worker retry/backoff policy,
but records service-specific history events.

Service orders should not emit `event: worker_run`; that event means a finite
AI/Shell run. Use service events:

- `service_order_started`
- `service_order_ready`
- `service_order_failed`
- `service_order_retried`
- `service_order_canceled`

Failure routing:

- Pre-start nonzero exit: retryable unless config validation failed before the
  process was launched.
- Main process spawn failure: non-retryable when the executable/shell cannot be
  launched; retryable for ordinary process exit during startup.
- Main process exits during startup grace: retryable.
- Health never becomes ready before `startup_timeout_seconds`: retryable.
- Ticket cancellation/yank: non-retryable cancellation; do not move the ticket
  to Blocked as a failure unless the existing yank path chooses a human column.
- Exhausted retries: move to Blocked with the last service-order reason.

History rows should include `attempt`, `max_retries`, `action`, `state`,
`health`, `pid`, `duration_ms`, `exit_code`, `reason`, `log_artifact`,
`config_hash`, and `active_config_hash`.

Tests:

- pre-start failure retries then blocks
- health timeout retries then blocks
- non-retryable config validation failure blocks immediately
- cancellation records `service_order_canceled` and does not consume retries
- successful retry records both failed and succeeded attempts

### Commit Extraction

Decision: `BULLPEN_SERVICE_COMMIT` extraction is deterministic but does not
validate Git object existence.

Rules:

- Prefer explicit ticket frontmatter `commit`.
- Otherwise use the first body line matching `commit: <7-40 hex>`.
- Match the label and hex case-insensitively.
- Preserve the matched hex string as written except for surrounding whitespace
  trim.
- Leave the value blank when no match exists.

The Service worker should not run `git cat-file` itself. It does not know
whether the workspace is a Git repository, whether the pre-start command uses
Git, or whether the commit is intended for some other tool. If the configured
pre-start command runs `git checkout "$BULLPEN_SERVICE_COMMIT"` and the value
is invalid, that command fails normally and the service order follows the
pre-start failure path.

Tests:

- frontmatter commit wins over body commit
- first body match wins
- uppercase hex and uppercase `COMMIT:` match
- no arbitrary first hex string is extracted
- invalid Git object is left to pre-start command failure, not prevalidated

### Manual Action Authorization

Decision: service controls use the same write-authorized Socket.IO model as
other worker mutations.

Current Bullpen deployments have either authenticated editor users or
localhost/no-auth mode. In no-auth mode, any connected client is effectively an
editor. Service workers do not add a new auth model in v1; they make the risk
more visible because Start / Stop / Restart execute arbitrary configured
commands.

Implementation requirements:

- Register service control events through the same auth/session gate as
  `worker:start`, `worker:stop`, and `worker:configure`.
- Never expose command/env values through read-only serialization.
- Include plaintext command/env warnings anywhere service config is created,
  transferred, exported, or saved in a team.
- Keep manual actions in the service log with actor context when available.

Open product concern: binding Bullpen to a non-loopback interface with auth
disabled is already risky. Service workers increase the blast radius, but the
fix belongs to the broader server startup/security policy rather than this
worker type alone.

### Preview Proxy Coupling

Decision: no direct preview-proxy coupling in v1.

The Service worker owns process state, logs, and health. A preview pane or
proxied TCP port may read that state later, but the Service worker should not
special-case preview routing, reserve ports, or infer preview URLs in v1.

The only v1 overlap is configuration: users may set env vars such as
`HOSTED_PORT` and configure health checks against the same local/private URL.

Deferred integration points:

- show a "Open preview" action when a workspace has preview proxy config
- derive preview health from Service health
- stop preview affordances when the service is stopped/crashed

## Remaining Review Points

Only two issues still need human confirmation before the full implementation is
locked:

1. **Windows graceful behavior acceptance.** The spec now says graceful
   `CTRL_BREAK_EVENT` first, `taskkill /T /F` second. Confirm that forceful
   fallback is acceptable for v1 services that do not handle console break.
2. **No-auth exposure policy.** The Service worker can proceed using existing
   auth behavior, but a separate security decision should decide whether
   non-loopback binds with auth disabled should become a hard startup error.

Neither blocks starting the backend normalization/controller work.

---

## Implementation Work Breakdown

The plan is mature enough for phased implementation. Each phase should end with
a commit and a ticket/update that records the phase result.

### Phase 1 - Type Registration and Persistence

Goal: Bullpen can create, persist, serialize, duplicate, copy/paste, transfer,
save/load teams, and import/export Service workers without running processes.

Backend:

- Add `service` to `VALID_WORKER_TYPES` and `WORKER_TYPES` in
  `server/worker_types.py`.
- Add `ServiceWorkerType` with validation for command, cwd, env,
  `ticket_action`, health config, startup/stop/log limits, and crash policy.
- Extend `normalize_worker_slot()` for Service fields.
- Extend `serialize_worker_slot()` read-only redaction for Service command,
  pre-start, env, and health shell command.
- Extend worker add/configure validation paths in `server/events.py`.
- Ensure copy, duplicate, paste, transfer, team save/load, and unknown-type
  preservation keep Service config and drop runtime-only fields.

Frontend:

- Add Service as an Add Worker/configure option.
- Add Service form fields with plaintext warnings.
- Add Service icon/color helpers in `static/utils.js`.
- Render disabled/not-runnable state correctly until controller events exist.

Tests:

- normalization defaults
- redaction
- duplicate/copy/paste preserves `type: "service"`
- team save/load round trip
- transfer/export/import round trip

Commit suggestion: `feat: add service worker type persistence`

### Phase 2 - Service Controller and Manual Lifecycle

Goal: manual Start / Stop / Restart works for one service per slot with logs,
state events, shutdown cleanup, and no ticket involvement.

Backend:

- Add `server/service_worker.py`.
- Implement `ServiceWorkerController` keyed by `(workspace_id, slot_index)`.
- Add controller registry helpers: get/create, snapshot, stop all for
  workspace, stop all globally.
- Implement config snapshot/hash calculation.
- Implement cwd/env helpers by reusing or extracting Shell worker helpers.
- Implement POSIX and Windows process launch/stop paths.
- Implement file-backed service logging and current-plus-one rotation.
- Implement monitor thread for exit/crash transitions.
- Add `service:start`, `service:stop`, `service:restart`, and `service:tail`
  events in `server/events.py`.
- Add app shutdown hook to stop active services.

Frontend:

- Add service state store keyed by workspace/slot.
- Listen for `service:state`, `service:log`, and `service:tail` catch-up.
- Add worker-card service state display and menu actions.
- Add focus/detail service log view.
- Show "Restart to apply" when config hashes differ.

Tests:

- manual start launches a long-running command
- manual stop terminates the process tree
- manual stop cancels a manual pre-start and kills the whole pre-start tree
- manual restart replaces the process
- crash transitions to `crashed`
- config hash is stable across cosmetic/no-op normalization changes
- log tail catch-up resets the client buffer after opening focus view
- log rotation caps current plus one rotated file without tail/rename races
- shutdown cascade stops services concurrently within one timeout window
- workspace removal cascade-stops only that workspace's services

Commit suggestion: `feat: add service worker manual lifecycle`

### Phase 3 - Ticket Service Orders

Goal: dropping or routing a ticket to a Service worker performs the configured
ticket action, waits for readiness, then uses the normal disposition pipeline.

Backend:

- Teach `start_worker()` to dispatch `type: "service"` to the Service order
  path.
- Implement service-order acquisition without creating synthetic tickets for
  manual service controls.
- Implement `ticket_action` values:
  `start-if-stopped-else-restart`, `restart`, and `start-if-stopped`.
- Serialize service-order attempts with the per-slot operation lock.
- Use config snapshots for each order.
- Add service-order history rows on tickets.
- Integrate retry/backoff and final Blocked disposition with existing worker
  completion helpers where possible.
- Route successful orders through the existing disposition grammar.
- Handle ticket yank/cancellation as service-order cancellation.

Frontend:

- Show active service-order ticket on the worker card without making it look
  like the service process is owned by the ticket forever.
- Disable manual service controls while a ticket order is active.
- Show service-order result/history in ticket detail through existing history
  rendering where possible.

Tests:

- drop ticket starts stopped service and routes ticket on readiness
- drop ticket restarts running service and routes ticket on readiness
- `start-if-stopped` succeeds without restart when already running and ready
- `start-if-stopped` waits for health with a bounded timeout when already
  running but unhealthy
- two queued tickets execute serially
- duplicate dispatch does not spawn duplicate service processes
- duplicate dispatch leaves later tickets queued
- service-order failure retries then blocks
- cancellation/yank records canceled and leaves known state

Commit suggestion: `feat: add service worker ticket orders`

### Phase 4 - Health Checks and Readiness

Goal: Service state and ticket routing are gated by configured readiness.

Backend:

- Implement HTTP health checks with local/private target validation.
- Implement shell health checks with cwd/env confinement and timeout.
- Add health monitor loop and thresholds.
- Gate service-order success on first health success when configured.
- Emit health transitions in `service:state`.
- Prefix shell health output in service logs.

Frontend:

- Add health config fields.
- Show running/healthy/unhealthy/stopped/crashed states on card and focus view.
- Surface concise health failure reasons.

Tests:

- no health check uses startup grace
- HTTP 2xx marks healthy
- HTTP failure threshold marks unhealthy
- later HTTP success moves unhealthy back to healthy
- health startup timeout fails order
- private-network URL validator accepts/rejects expected targets
- shell health timeout fails check without killing main service

Commit suggestion: `feat: add service worker health checks`

### Phase 5 - Hardening, Parity, and Documentation

Goal: close platform, security, and operational gaps before declaring the
feature complete.

Backend/tests:

- Run and fix Windows process-tree tests.
- Add multi-workspace event scoping tests for `service:*`.
- Add read-only serialization tests for Service secrets.
- Add controller cleanup tests for removed workers and removed workspaces.
- Add stale runtime-file cleanup behavior if runtime metadata is written.
- Add regression tests for copy/paste, transfer, team save/load, and import
  after Service runtime state exists.

Frontend/docs:

- Polish Service card/focus UI.
- Add Service worker README/user docs.
- Document no-auth exposure warning and plaintext storage.
- Document examples for common dev-server commands.

Commit suggestion: `feat: harden service worker v1`

---

## Declined Comments

One appended suggestion was only partially accepted:

- **Do not prevalidate `BULLPEN_SERVICE_COMMIT` with `git cat-file`.** The spec
  now defines first-match and case-insensitive extraction, but the Service
  worker will not verify Git object existence itself. Service workers can run
  outside Git repositories, and the pre-start command may not use Git at all.
  Invalid commits should fail through the configured pre-start command, such as
  `git checkout "$BULLPEN_SERVICE_COMMIT"`, and then follow the normal
  pre-start failure path.

All other appended comments were accepted and baked into the main spec.

---

## Implementation Readiness

The feature is **ready for phased implementation**, with Phase 1 and Phase 2
now sufficiently specified to start.

What can start now:

- Type registration, normalization, serialization, copy/paste, transfer, team,
  import/export, and UI form work.
- Manual lifecycle controller work with config hashes, pre-start tree kill,
  bounded logs, service state/log events, parallel shutdown, and workspace
  teardown cleanup.
- Ticket-order implementation after the manual lifecycle is stable.

What still deserves confirmation before final release:

- Whether Windows forceful fallback after `CTRL_BREAK_EVENT` is acceptable for
  v1.
- Whether the broader app should reject non-loopback binds when auth is
  disabled.

Risk assessment:

- Highest correctness risk: process lifecycle and cancellation during pre-start
  and stop/start transitions.
- Highest UX risk: making it clear that the worker owns the service while
  tickets are only orders, especially when pending config will affect queued
  tickets.
- Highest security risk: arbitrary command execution becoming more convenient
  in no-auth or remotely exposed deployments.
- Highest test risk: Windows process-tree cleanup, log rotation/tail catch-up,
  and Socket.IO event scoping.

---

## Related Docs

- [shell-worker.md](shell-worker.md) — the closest existing worker type;
  Service reuses its config containment, env model, and log pane UI.
- [worker-types.md](worker-types.md) — worker-type registry and dispatch.
- [docker.md](docker.md) — container requirements.
