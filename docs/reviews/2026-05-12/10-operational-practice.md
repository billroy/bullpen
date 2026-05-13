# Operational Practice Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Site reliability engineer / DevOps lead evaluating for acquisition

---

## Executive Summary

Bullpen has solid deployment infrastructure for its target profile (single-host, self-managed). Docker, DigitalOcean nginx+systemd, and Fly.io deployment scripts are provided and functional. The database-less architecture substantially reduces operational complexity — there are no migrations, no connection pool management, and no backup restoration procedures beyond filesystem copy. The key operational gaps are: no CI/CD pipeline (all testing and releases are manual), no structured logging or log aggregation, no metrics collection or alerting, and no documented runbook for common operational scenarios. These gaps are acceptable for a small-team developer tool but represent real acquisition risk if a buyer plans to operate Bullpen as a managed service.

---

## Findings

### HIGH — No CI/CD pipeline; all testing is manual

**Location:** Repository root — no `.github/workflows/`, no CI configuration of any kind

**Detail:** There is no automated pipeline to run tests, enforce quality gates, or produce release artifacts on pull request or merge. This means:

1. A broken change can be merged to `main` without triggering any automated test failure.
2. There is no reproducible build environment — test results are machine-specific.
3. There is no automated release process — releases are manual (Docker push, deploy script run by hand).
4. There is no deployment gate: test failure does not block deploy.

For an acquirer evaluating operational maturity, the absence of CI is the single most commonly flagged gap in technical due diligence. It signals that engineering infrastructure investment is below the bar expected for a production service.

**Recommendation:** Add a GitHub Actions workflow at `.github/workflows/ci.yml` that:
- Runs `pytest -x -q` on Python 3.12 on every push to `main` and every pull request
- Reports coverage with `pytest-cov` and fails below 70% line coverage
- Runs `ruff check .` for lint
- Estimated effort: 2–4 hours

---

### HIGH — No structured logging; log output is unqueryable

**Location:** `server/app.py`, `server/workers.py` — Flask/Python logging to stderr

**Detail:** Application logs are emitted to stderr as plain text. There is no structured logging (JSON fields for log level, timestamp, component, event, user, workspace ID). Operational consequences:

1. Alerts cannot be written against log patterns (no log aggregation or filtering by field).
2. Debugging a production incident requires grepping raw log text, which is fragile.
3. Audit trail for security events (login failures, auth bypasses, agent starts) is not queryable.
4. Log correlation across requests is impossible (no request ID or trace ID in log output).

**Recommendation:** Adopt structured logging using Python's `logging` module with a JSON formatter (e.g., `python-json-logger`). Emit at minimum these fields per log line: `timestamp`, `level`, `component`, `event`, `workspace_id`, `worker_id` (where applicable), `duration_ms` (for slow operations). Route logs to stdout for Docker (captured by container runtime) and systemd (captured by journald).

---

### MEDIUM — No metrics collection or alerting

**Detail:** There are no application-level metrics exported in any format (Prometheus, StatsD, CloudWatch, etc.). Key operational metrics that are currently unobserved include:

- Worker start rate / completion rate / failure rate
- Agent execution latency percentiles (p50, p95, p99)
- Task queue depth per workspace
- Socket.IO connection count
- File write operation latency
- Active worktree count
- Memory and CPU utilization per agent subprocess

Without these metrics, it is impossible to:
- Set SLOs (service level objectives) for agent execution time
- Detect degraded performance before users report it
- Capacity plan for host resources
- Trigger alerts on error rate spikes

**Recommendation:** Add a `/api/metrics` endpoint that emits a Prometheus-compatible text format with the key counters and gauges listed above. This endpoint can be scraped by Prometheus or simply polled by a simple monitoring script. Alternatively, integrate `flask-prometheus-metrics` (MIT licensed) with minimal configuration.

---

### MEDIUM — No documented runbook for common operational scenarios

**Detail:** There are detailed deployment guides in `docs/` (Docker, DigitalOcean, Fly.io) but no operational runbook covering:

1. How to restart Bullpen and restore in-flight worker state
2. How to recover from a corrupted `layout.json`
3. How to safely migrate a workspace to a new host
4. How to rotate the MCP authentication token
5. How to revoke a user's credentials without downtime
6. How to diagnose a worker that is stuck in "working" state
7. How to free a stale git worktree

The backup JSON created on `layout.json` write (`layout.json.backup`) addresses corruption recovery, but this mechanism is not documented in any operator-facing guide.

**Recommendation:** Create `docs/operations-runbook.md` covering the scenarios above. Each scenario should include symptoms, diagnosis steps, and remediation commands. This document is essential for a managed service handoff.

---

### MEDIUM — No health check beyond HTTP 200

**Location:** `server/app.py` — `/health` endpoint returns 200 with no diagnostic data

**Detail:** The `/health` endpoint exists and is useful for container orchestrators (Kubernetes liveness probes, Docker healthcheck). However, it only returns HTTP 200 — it does not validate that the application's internal subsystems are functional:

1. Socket.IO server is accepting connections
2. Workspace storage directory is writable
3. Scheduler thread is alive
4. Pending task queue is not deadlocked

A shallow health check may return 200 while the application is in a degraded state that prevents workers from executing.

**Recommendation:** Add a deep health check at `/health/detailed` that validates: workspace directory writable (write + delete a test file), scheduler thread alive (check thread `.is_alive()`), Socket.IO server accepting connections (check internal state). Return JSON with per-subsystem status and an aggregate `status: ok|degraded|critical`.

---

### MEDIUM — Backup strategy relies on manual filesystem copy or export API

**Detail:** The only documented backup mechanisms are:
1. The `layout.json.backup` automatic file (single-version, overwritten on each write)
2. The `/api/export/workspace` ZIP export endpoint

Neither provides:
- Scheduled, automated backups
- Backup retention (N copies, N days)
- Off-host backup (to S3, GCS, Dropbox)
- Backup integrity verification (the ZIP can be created but its contents are not verified)
- Point-in-time recovery

For a commercial deployment, the absence of automated off-host backups is a significant operational risk.

**Recommendation:** Add a configurable backup cron option to the Docker entrypoint or systemd service that periodically calls the export API and copies the resulting ZIP to a configurable destination (local path, S3 bucket, remote SSH host). Document this in `docs/backup.md`.

---

### LOW — Agent CLI versions in Docker image are not pinned

**Location:** `Dockerfile` — `npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli`

**Detail:** The three agent CLI packages are installed from npm at Docker build time without version pins. Each Docker build may install a different CLI version, making it impossible to reproduce a known-good environment. CLI interface changes (see `06-tech-due-diligence.md`) could break agent adapters silently when a new image is built.

**Recommendation:** Pin each CLI to a specific version in the Dockerfile (e.g., `@anthropic-ai/claude-code@1.x.y`). Update the pinned versions deliberately as part of the release process, not automatically on each build.

---

### LOW — `BULLPEN_PRODUCTION=0` is the default in Dockerfile

**Location:** `Dockerfile` — `ENV BULLPEN_PRODUCTION=0`

**Detail:** The Dockerfile sets `BULLPEN_PRODUCTION=0` as the default environment variable. An operator who builds and deploys the Docker image without explicitly overriding this variable will run in non-production mode (insecure session cookies, relaxed origin checks). This is a documentation/discoverability risk — the operator must know to set this variable.

**Recommendation:** Add a clear warning comment in the Dockerfile next to the `BULLPEN_PRODUCTION=0` line, and add a startup check that logs a prominent `WARNING: BULLPEN_PRODUCTION=0 — session cookies are not secure` message when the flag is unset and the server is bound to a non-localhost address.

---

## Operational Maturity Assessment

| Area | Current State | Gap |
|---|---|---|
| CI/CD | None | HIGH — blocks production reliability |
| Structured logging | Plain-text stderr | HIGH — unqueryable in production |
| Metrics | None | MEDIUM — no observability |
| Alerting | None | MEDIUM — no proactive incident detection |
| Runbook | Partial (deploy guides only) | MEDIUM — no incident response docs |
| Backup | Manual export only | MEDIUM — no automated off-host backup |
| Health check | Shallow (HTTP 200) | MEDIUM — does not detect degraded state |
| Deployment scripts | Good (Docker, DO, Fly.io) | LOW — complete for target use case |
| Dependency pinning | Partial (Python pinned; npm unpinned) | LOW — npm CLIs should be pinned |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 5 |
| LOW | 2 |
