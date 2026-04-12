# Operational Practice Review — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Review of CI/CD pipeline, deployment automation, monitoring, logging, error tracking, backup and recovery, and operational runbooks.

---

## Summary

Bullpen is currently operated as a local developer tool with no automated deployment, monitoring, or operational infrastructure. This is appropriate for a solo-developer tool but represents significant risk if the product moves toward shared team or hosted deployment.

---

## Findings

### HIGH — No CI/CD pipeline

**Files:** Repository root (verified: no `.github/workflows/`, `.circleci/`, `Jenkinsfile`, `Makefile` with CI targets, or similar)

There is no automated CI pipeline. No tests run on push or pull request. The only documented test command is:

```bash
python3 -m pytest tests/ -x -q
```

This must be run manually by the developer. Consequences:
- Regressions can ship undetected between manual test runs.
- No automated quality gate on the main branch.
- Contributors have no automated feedback on their changes.

**Recommendation:** Add a `.github/workflows/ci.yml` that runs pytest on every push and pull request. This is a <1 hour investment with high return.

---

### HIGH — No structured logging

**Files:** `server/app.py`, `server/workers.py`, `server/events.py`

The application uses `print(..., file=sys.stderr)` for diagnostic output and silently swallows exceptions in several critical paths. There is no structured logging (no `logging` module, no log levels, no log formatting, no log rotation). Consequences:
- Cannot filter by severity in production.
- No audit trail for auth events (login success/failure, session creation).
- No operational visibility into agent runs (start/end times, token counts, errors) beyond what is shown in the UI.

**Recommendation:** Replace all `print(...)` calls with `logging.getLogger(__name__)` at appropriate levels. Add a startup configuration that sets log level from an env var. Log auth events (login, logout, auth failure) at INFO level.

---

### HIGH — No backup or recovery mechanism for `.bullpen/` data

**Files:** `.bullpen/` directory structure

All persistent state (tasks, layout, config, profiles, teams, usage history) lives in `.bullpen/`. There is no:
- Automated backup.
- Export/import functionality.
- Recovery procedure documented for data loss.
- Verification that atomic writes survive power loss (fsync is not called after `os.replace`).

**Recommendation:** Add a `bullpen --export` command that creates a timestamped zip of `.bullpen/`. Document recovery procedures in `README.md`. Consider calling `os.fsync` in `atomic_write` for durability guarantees.

---

### MEDIUM — No health check endpoint

**Files:** `server/app.py` (no `/health` or `/ping` endpoint found)

Without a health check endpoint, there is no way to:
- Verify the server is responsive via automated monitoring.
- Configure a load balancer or container orchestrator to restart unhealthy instances.
- Check server health from a script or CI job.

**Recommendation:** Add `GET /health` returning `{"ok": true, "version": "..."}` with HTTP 200.

---

### MEDIUM — No process supervisor or auto-restart

**Files:** `bullpen.py`

Bullpen runs as a foreground process launched by `python3 bullpen.py`. There is no supervisor (systemd unit, launchd plist, PM2, or similar) to restart it on crash. A background agent run that causes an unhandled exception in the main thread would take down the entire server.

**Recommendation:** Provide a sample `systemd` unit file and/or launchd plist in `docs/` for users who want persistent deployment. Document that the server should be run under a process supervisor for non-local use.

---

### MEDIUM — Agent timeout is configurable but not enforced at the OS level

**File:** `server/workers.py`, `server/validation.py` (`agent_timeout_seconds` config key)

The `agent_timeout_seconds` config key controls how long a worker waits for an agent to complete. This timeout is implemented in application code (not via OS-level subprocess timeout). If the worker thread crashes or is blocked by the GIL, the timeout check may not run. The subprocess would continue running past the timeout.

**Recommendation:** Pass `timeout=agent_timeout_seconds` to the subprocess wait call as a hard OS-level timeout. Currently the subprocess is managed with explicit thread control, so verify the timeout is enforced at the `proc.wait()` call.

---

### MEDIUM — No error tracking or alerting

**Files:** All server modules

There is no integration with error tracking services (Sentry, Rollbar, etc.) or any alerting mechanism. Errors in worker threads, scheduler threads, or SocketIO handlers are either silently swallowed or printed to stderr. In a shared deployment, operators have no notification when the system enters an error state.

**Recommendation:** Add optional Sentry integration (configurable via env var) for error tracking. Even a simple email or webhook notification on worker failure would improve operational visibility.

---

### LOW — Server logs `mcp_token` indirectly

**File:** `server/app.py:162–165`

The MCP token is written to `config.json`. If `config.json` contents are ever logged (e.g., for debugging), the token would appear in logs. The token is a session secret and should be treated with the same care as passwords.

**Recommendation:** Ensure the MCP token is never included in log output. Add a scrubbing pattern to any future structured logging configuration.

---

### LOW — No documented upgrade procedure

**Files:** `README.md`, `requirements.txt`

The README documents installation but not upgrades. Users who `git pull` to update Bullpen have no guidance on:
- Whether `.bullpen/` data is forward-compatible.
- Whether `requirements.txt` dependencies changed and `pip install` needs to be re-run.
- Whether config schema changes require migration.

**Recommendation:** Add an `UPGRADING.md` or section in `README.md` documenting the upgrade procedure.

---

### LOW — `reconcile()` is the only crash recovery mechanism

**File:** `server/app.py:557–600`

On startup, `reconcile()` resets workers that were in "working" state to "idle" and marks their tasks as "blocked". This is the only crash recovery mechanism. It handles the case where the server was killed mid-run but does not handle:
- Partial task file writes (if `atomic_write` was interrupted mid-temp-file).
- Corrupted `layout.json` (no schema validation on load).
- Partially written worktrees from an interrupted `git worktree add`.

**Recommendation:** Add schema validation for `layout.json` on load. Add a `reconcile_worktrees()` step that checks for and cleans up orphaned git worktrees on startup.

---

## Positive Observations

- `atomic_write` (temp file + `os.replace`) provides crash-safe writes for individual files.
- `reconcile()` correctly handles the most common crash recovery scenario (worker in working state).
- Worker output is bounded (`MAX_OUTPUT_BUFFER = 500,000`) preventing runaway memory use.
- Auth credential file is created with `0o600` permissions.
- The `--no-browser` flag and configurable host/port make the tool adaptable to different deployment environments.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| OP1 | HIGH | No CI/CD pipeline |
| OP2 | HIGH | No structured logging — print-to-stderr only |
| OP3 | HIGH | No backup/recovery mechanism for `.bullpen/` data |
| OP4 | MEDIUM | No health check endpoint |
| OP5 | MEDIUM | No process supervisor or auto-restart guidance |
| OP6 | MEDIUM | Agent timeout not enforced at OS level |
| OP7 | MEDIUM | No error tracking or alerting |
| OP8 | LOW | MCP token must not appear in logs |
| OP9 | LOW | No documented upgrade procedure |
| OP10 | LOW | `reconcile()` does not clean up orphaned worktrees |
