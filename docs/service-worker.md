# Service Workers

Service workers supervise a single long-running process on behalf of a ticket.
Unlike Shell and AI workers — which run a command to completion and then hand
the ticket back — a Service worker's job is to **keep a process alive**, stream
its output into the ticket log, and obey explicit Start / Stop / Restart
actions from the user.

The motivating use case: Bullpen runs inside a Docker container that also
hosts a separate application under development. The container exposes a second
proxied TCP port for that application. A Service worker lets the user start,
stop, and restart the hosted application from a Bullpen ticket, with the
ticket's own log pane as the live server log.

This document is the design spec. It covers concept, UI, configuration,
server-side lifecycle, the Bullpen-restart question, and a rough
implementation scope.

---

## Concept

A Service worker owns one subprocess per ticket. The ticket IS the service:

- The worker's state reflects the **process's** state (stopped, running,
  crashed), not a script's completion.
- Output is streamed live into the ticket's existing log pane and persisted to
  a durable file.
- Lifecycle transitions are user actions on the ticket, not separate tickets
  that happen to interact via PID files.

This replaces the "sack of scripts" pattern (one worker to start, one to stop,
one for status, coordinating through a PID file in user space) with a single
first-class worker type that handles supervision, kill semantics, and crash
detection once, correctly, for everyone.

---

## Configuration

Fields in the create-worker dialog, Service tab:

- **Command** (required) — a single shell-interpreted command line, e.g.
  `python3 hosted-app.py --port=$HOSTED_PORT`. Executed via `/bin/sh -c` on
  POSIX, `cmd.exe /c` on Windows.
- **Working directory** — relative to the workspace root. Same containment
  rules as Shell workers (no symlink escapes).
- **Environment** — key/value rows merged on top of a minimal inherited env.
  Two variables are auto-injected from the ticket:
  - `COMMIT` — first 7–40 hex run found in the ticket body, or empty.
  - `TICKET_ID` — the ticket's id.
- **Pre-start** (optional) — a shell command run to completion before the
  main command. Typical use: `git fetch && git checkout "$COMMIT"`. Non-zero
  exit aborts the start and the worker state becomes `crashed` with the
  pre-start output captured in the log.
- **Health check** (optional) — either an HTTP URL or a shell command. Polled
  on a configurable interval (default 5s) once the process is up. Drives a
  `healthy` / `unhealthy` sub-state on top of `running`.
- **On crash** — `stop` (default: stay down, surface the exit code) or
  `restart` (respawn with exponential backoff capped at 60s).
- **Start on boot** — if set, Bullpen starts this service when the Bullpen
  server itself starts (see [Bullpen-restart behavior](#bullpen-restart-behavior)).

No PID file, log path, or detach/nohup mechanics are exposed to the user.
Bullpen owns those.

---

## What the user sees

The ticket detail pane for a Service worker replaces the usual "run / output"
affordances with a supervision view:

- **Status chip** at top of the worker-output pane:
  `● running · healthy · pid 48213 · up 12m · commit a1b2c3d`
  The dot is green for healthy, yellow for running-but-not-yet-healthy, red
  for crashed, grey for stopped.
- **Three buttons**: **Start**, **Stop**, **Restart**. Enabled/disabled based
  on current state (e.g. Start is disabled while `running`, Stop is disabled
  while `stopped`).
- **Live log pane** — the same component Shell workers use for output. No new
  UI primitive.
- **Edit command** affordance — editing Command, Env, or Pre-start shows a
  "Restart to apply" hint rather than applying live.

The commit-hash-triggered restart flow is: the user pastes a new hash into the
ticket body (or edits the `COMMIT` env row), then clicks **Restart**. The
pre-start `git checkout "$COMMIT"` picks it up on the next spawn. No separate
"apply commit" ticket or worker.

---

## State machine

```
 stopped ──Start──▶ starting ──▶ running ──▶ (healthy | unhealthy)
    ▲                  │            │
    │                  ▼            ▼
    └── stopping ◀── Stop ──── Restart (= Stop then Start)
                                    │
                                    ▼
                                  crashed   (process exited without user Stop)
```

- `starting` covers Pre-start execution and the interval before the health
  check first succeeds.
- `healthy` / `unhealthy` only apply when a health check is configured.
- `crashed` is terminal from `running` when exit wasn't user-initiated. Crash
  policy (`stop` vs `restart`) governs what happens next automatically.

The ticket's own status column is orthogonal — the user can still put the
ticket in any column; the worker state is a property of the worker, not of
the ticket's position.

---

## Server-side design

One new class, `ServiceWorker`, held in the app's worker registry keyed by
ticket id. Suggested location: `server/service_worker.py`.

```python
class ServiceWorker:
    def __init__(self, ticket_id, config): ...
    def start(self): ...        # runs pre-start, spawns process
    def stop(self, timeout=5): ...   # SIGTERM pgid, wait, SIGKILL
    def restart(self): ...      # stop(); start()
```

### Spawn

- `subprocess.Popen(..., start_new_session=True)` so the child owns its own
  process group. This is the single mechanism that makes forked-child kill
  correctness free — it handles Flask debug reloaders, gunicorn worker pools,
  etc. without per-user workarounds.
- stdout + stderr merged, piped through a reader thread.

### Logging

Each line from the reader thread is written two places:

1. Appended to `.bullpen/logs/services/<ticket_id>.log` — durable, survives
   Bullpen restarts, available for tailing from a shell.
2. Emitted as a `service:log` Socket.IO event to subscribed clients for live
   tail in the ticket pane.

Log rotation is out of scope for v1 — size-cap truncation can be added later.

### Monitor

A wait-thread `self.process.wait()`s. On exit:

- Records exit code and wall-clock duration.
- If `stopping` → state becomes `stopped`.
- Otherwise → state becomes `crashed`; crash policy fires.

### Controls

Socket events the ticket UI dispatches:

- `service:start` `{ ticket_id }`
- `service:stop` `{ ticket_id }`
- `service:restart` `{ ticket_id }`

Events the server emits:

- `service:state` `{ ticket_id, state, pid, started_at, exit_code, commit }`
- `service:log` `{ ticket_id, line }`

### Stop semantics

`stop()` sends `SIGTERM` to the **process group** (`os.killpg(pgid, SIGTERM)`),
waits up to `stop_timeout` seconds (default 5), then `SIGKILL`s the group. The
group kill is why we set `start_new_session=True` at spawn time. Done once
here, not re-litigated per user.

### Health check

If configured, a scheduler thread runs the check every `health_interval`
seconds once state is `running`. HTTP checks treat any 2xx as healthy; shell
checks treat exit code 0 as healthy. Consecutive failures flip to `unhealthy`
after a configurable threshold (default 3).

---

## Bullpen-restart behavior

This is the one real design decision. The chosen policy is **re-adopt**:

1. On every `start()`, Bullpen appends/updates an entry in
   `.bullpen/services.json`:
   `{ ticket_id, pgid, log_path, command_hash, started_at }`.
2. On Bullpen startup, it reads that file and for each entry calls
   `os.killpg(pgid, 0)` to check liveness.
   - **Alive** → re-attach the log-file tail reader, mark state `running`,
     emit `service:state`. The user's service never blinked.
   - **Dead** → mark `stopped`, clear the entry. If the worker has
     **Start on boot** enabled, queue a `start()`.
3. On clean shutdown of Bullpen (SIGTERM to the server), services are **not**
   stopped. This is deliberate: Bullpen is a controller, not the service's
   parent-in-interest. Users who want the service to die with Bullpen can
   disable **Start on boot** and stop it explicitly.

Alternatives considered and rejected:

- **Cascade** (services die with Bullpen) — simple, but means every Bullpen
  code reload takes down the app under test. Bad ergonomics.
- **Double-fork reparent to PID 1** — strongest survival, but "stop Bullpen"
  not stopping services surprises users and complicates cleanup. Re-adopt
  gives the same survival in practice without the footgun.

The container must run with `--init` (or `tini` as entrypoint) so orphans are
reaped. This is already required by the Docker deployment; see
[docker.md](docker.md).

---

## Security model

Service workers inherit Shell worker's containment rules:

- Working directory must resolve inside the workspace root; symlink escapes
  rejected.
- Env starts from a minimal allowlist; user-supplied keys merge on top.
- Command is plaintext in the ticket config, same plaintext-storage warning
  as Shell.

One addition: Service workers can run for arbitrary durations, so CPU/memory
limits should be considered. v1 does not enforce limits; a follow-up can wire
`resource.setrlimit()` into the spawn path.

---

## Implementation scope (rough)

- `server/service_worker.py` — the class above, ~150 lines.
- Worker-type registration (`kind: "service"`) in the dispatcher that already
  routes Shell vs AI.
- Socket events: `service:start`, `service:stop`, `service:restart`,
  `service:state`, `service:log`. (`service:log` may be able to reuse the
  Shell log event format.)
- Ticket detail Vue component: status chip + 3 buttons + reuse of the
  existing log pane. No new primitives.
- `.bullpen/services.json` persistence and boot-time re-adopt in
  `create_app()`.
- Two new form fields in the create dialog: Command and Pre-start. Env,
  health check, and crash policy can land in a follow-up if scope pressure
  demands it.

Out of scope for v1:

- Log rotation / truncation.
- Resource limits (CPU/memory caps).
- Multiple services per ticket.
- Dependency ordering between services.

---

## Related docs

- [shell-worker.md](shell-worker.md) — the closest existing worker type;
  Service reuses its config containment, env model, and log pane UI.
- [worker-types.md](worker-types.md) — worker-type registry and dispatch.
- [docker.md](docker.md) — container requirements, including `--init`.
