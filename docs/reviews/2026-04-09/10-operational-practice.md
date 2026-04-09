# Operational Practice Review — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Site reliability / DevOps engineer evaluating as a potential acquirer

---

## Scope

Review of deployment practices, monitoring, logging, incident response, backup and recovery, configuration management, and operational documentation.

---

## Executive Summary

Bullpen is a developer tool designed for local use with minimal operational overhead — this is appropriate and intentional. The operational gaps identified here are gaps relative to a production deployment scenario, not against the current localhost use case. The most significant operational gaps are the absence of any CI/CD pipeline, no structured logging or monitoring, no backup mechanism, and no deployment documentation beyond the README quick start. An acquirer operating Bullpen as a hosted service would need to build a full operational stack from scratch.

---

## Findings

### HIGH — No CI/CD Pipeline

**Location:** Repository root — no `.github/workflows/`, `.circleci/`, `.gitlab-ci.yml`, or equivalent found.

There is no automated pipeline to:
- Run tests on push or PR
- Enforce linting or formatting
- Build and publish a release artifact
- Scan dependencies for vulnerabilities

This means code quality is enforced only by developer discipline. Regressions are only caught when tests are run manually.

**Recommendation:** Add a GitHub Actions workflow with at minimum:
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: pytest
```

---

### HIGH — No Structured Logging or Log Rotation

**Location:** `server/*.py`, `.bullpen/logs/`

Worker execution is logged to `.bullpen/logs/` (one file per execution). Application-level events (startup, auth failures, errors) appear to use Python's `logging` module or `print()` without:
1. Structured format (JSON or key=value) for machine parsing
2. Log rotation (logs grow indefinitely)
3. Log level configuration (no `--debug` flag)
4. Request/response logging middleware

**Recommendation:**
1. Configure Python `logging` with a `RotatingFileHandler` in `bullpen.py` at startup.
2. Add a `--log-level` CLI argument (debug/info/warning/error).
3. Use a structured log format (JSON lines) for all application-level events.
4. Add a log entry for every auth attempt (success/failure with IP).

---

### MEDIUM — No Health Check Endpoint

**Location:** `server/app.py` — no `/health` or `/ping` route found.

A health check endpoint is the minimal requirement for:
1. Process supervisors (systemd `ExecStartPre`, Docker `HEALTHCHECK`)
2. Load balancer health checks
3. Monitoring systems

Without it, the only way to verify Bullpen is running is to make a full application request.

**Recommendation:** Add a `GET /health` route that returns `{"status": "ok", "version": "x.y.z"}` with no authentication required.

---

### MEDIUM — No Backup Mechanism for Task Data

**Location:** `.bullpen/tasks/`, `.bullpen/config.json`, `.bullpen/layout.json`

All task data, configuration, and workspace state is stored in the `.bullpen/` directory on the local filesystem. There is no:
1. Automatic backup (cron, git auto-commit, rsync)
2. Export functionality
3. Recovery documentation

Data loss via accidental `rm -rf .bullpen/`, disk failure, or OS corruption has no recovery path.

**Note:** The auto-commit feature (optional) provides partial protection by committing task changes to the workspace git repo. However, this only covers task files, not config/layout.

**Recommendation:**
1. Document the recommended backup strategy in `docs/` (e.g., include `.bullpen/` in git, or use Time Machine/rsync).
2. Add an `export` command (`bullpen --export path/to/backup.zip`) that archives `.bullpen/` to a zip file.

---

### MEDIUM — Process Lifecycle Not Documented for Production

**Location:** `docs/` — no deployment guide beyond README quick start

The README documents `python3 bullpen.py --workspace ...` for development use. For a production/persistent deployment, users need documentation on:
1. Running as a system service (systemd unit file)
2. Configuring a reverse proxy (nginx/Caddy example)
3. TLS termination (referenced in `docs/login.md` but not shown concretely)
4. Environment variable configuration
5. Upgrading (stopping the service, updating code, restarting)

**Recommendation:** Add `docs/deployment.md` covering at minimum: systemd service setup, nginx reverse proxy config with TLS, and upgrade procedure.

---

### LOW — No Dependency Vulnerability Scanning

**Location:** `requirements.txt`, CI (absent)

There is no automated scanning (Dependabot, Snyk, `pip-audit`) to detect known CVEs in dependencies. Given the small dependency set, manual monitoring is feasible, but it is not documented as a practice.

**Recommendation:** Enable GitHub Dependabot alerts for the repository. Add `pip-audit` to the CI pipeline.

---

### LOW — No Version Number in the Application

**Location:** `bullpen.py`, `server/app.py` — no `__version__` or version constant found.

The application has no programmatic version identifier. This means:
1. Users cannot report which version they are running.
2. Upgrade documentation cannot reference specific version numbers.
3. A `GET /health` endpoint (once added) cannot return the version.

**Recommendation:** Add `__version__ = "0.1.0"` to `bullpen.py` (or a `pyproject.toml` version field) and expose it via the health endpoint and `bullpen --version` flag.

---

### POSITIVE FINDINGS

- **Atomic file writes prevent partial state corruption:** The `atomic_write()` abstraction means the application cannot be caught in a partially-written state by a crash or signal.
- **Worker timeout watchdog:** Agent subprocesses are killed after `agent_timeout_seconds` (default 600s), preventing zombie processes from accumulating.
- **Startup validation:** The `WorkspaceManager` reconciles workspace state at startup, removing invalid workspace registrations gracefully.

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| OPS-01 | No CI/CD pipeline | HIGH |
| OPS-02 | No structured logging or log rotation | HIGH |
| OPS-03 | No health check endpoint | MEDIUM |
| OPS-04 | No backup mechanism for task data | MEDIUM |
| OPS-05 | Process lifecycle not documented for production | MEDIUM |
| OPS-06 | No dependency vulnerability scanning | LOW |
| OPS-07 | No version number in the application | LOW |
