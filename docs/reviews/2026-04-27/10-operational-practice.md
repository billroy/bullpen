# Operational Practice Review
*Bullpen — 2026-04-27*

## Executive Summary

Bullpen's operational posture reflects its origins as a developer-focused tool built for personal or small-team use. Deployment artifacts (Docker Compose, Fly.io, nginx, systemd) are provided and usable. However, the project has no CI/CD pipeline, no structured logging, no monitoring or alerting, no documented incident response process, no backup strategy for its flat-file data store, and no documented upgrade procedure. Secret management is basic but functional for single-machine deployments. For a buyer planning to run Bullpen as a business-critical service for multiple teams, the operational gap between current state and production-grade practice is significant and will require investment before or shortly after acquisition.

---

## CI/CD & Automation

No CI/CD pipeline exists. The `.github/workflows/` directory is absent from the repository. There is no automated build, test, lint, or deployment step triggered on push or pull request.

The test suite exists (`python3 -m pytest tests/ -x -q`) and is presumably run manually by developers. There is no enforcement that tests pass before a commit merges. There is no Makefile or task runner that standardizes common developer commands (install dependencies, run tests, build Docker image, run linter).

Deployment to each target (Fly.io, DigitalOcean, Docker) appears to be a manual, operator-driven process. Fly.io's `fly deploy` and Docker's `docker compose up` are the presumed mechanisms, but no deployment script, runbook, or automation wraps them.

**Risk:** Regressions can ship undetected. Deployments are not repeatable or auditable. Different environments may diverge in configuration silently.

---

## Monitoring & Observability

No monitoring or alerting infrastructure is configured. Specific gaps:

- **No health check endpoint** confirmed in `app.py`. Docker and Fly.io health checks cannot be configured without one, meaning the platform has no way to detect that the application has started successfully or is responding to requests.
- **No structured logging.** Python's default `logging` module is used without a structured formatter (JSON, logfmt). Log output is human-readable but not machine-parseable by log aggregators (Datadog, Loki, CloudWatch, etc.).
- **No metrics collection.** There is no Prometheus endpoint, no StatsD integration, and no application performance monitoring (APM) agent (New Relic, Datadog APM, OpenTelemetry). Request latency, error rates, active worker counts, and task throughput are invisible to operators.
- **No alerting.** Without metrics, there are no alert thresholds. An operator learns about an outage when a user reports it.
- **Fly.io cold-start behavior.** The deployment target hibernates containers. Cold-start latency is inherent to this configuration and is not surfaced to users or monitored.

**Risk:** Outages go undetected until user reports. Performance degradation is invisible. Capacity planning has no data foundation.

---

## Incident Response

No incident response process is documented. There is no runbook, no escalation path, no on-call rotation definition, and no post-mortem template in the repository.

Practical implications for a new owner:
- When the server goes down, the operator must know from memory (or reverse-engineer) how to restart it, where logs are, and how to verify recovery.
- There is no documented rollback procedure for a bad deployment.
- There is no definition of what constitutes a severity-1 incident versus a minor degradation.

The systemd service file (provided) gives automatic restart-on-failure for systemd deployments, which is a baseline mitigation. Docker Compose and Fly.io provide analogous restart policies. These are process-level safeguards, not incident response.

**Risk:** Mean time to recovery (MTTR) for incidents will be high for any operator not deeply familiar with the codebase.

---

## Backup & Recovery

No backup strategy is documented for `.bullpen/` data directories. The flat-file data store means all task history, worker configurations, workspace state, and token usage records live in a directory tree on the host filesystem. There is no:

- Automated backup schedule
- Backup destination defined (S3, remote filesystem, etc.)
- Retention policy
- Restore procedure documented or tested
- Point-in-time recovery capability
- Transactional consistency guarantee during backup (a live `rsync` of flat files may capture partial writes)

For a Fly.io deployment, the ephemeral nature of container storage makes this especially acute: a container restart or volume misconfiguration can result in permanent data loss.

**Risk:** A disk failure, accidental deletion, or cloud provider incident results in total, permanent data loss. There is no recovery path without prior operator action that is not documented.

---

## Secret Management

Secret management is basic but functional for single-machine deployments:

- Application credentials are stored in `~/.bullpen/.env` with mode 600 (owner-read-only). This is appropriate for a single-machine deployment.
- The MCP token is written to per-workspace `config.json` files and rotated at application start.
- No secrets are confirmed to be committed to the repository.
- Docker deployments use environment variable injection, which is a standard pattern.

Gaps:
- No secrets manager integration (AWS Secrets Manager, HashiCorp Vault, Doppler, etc.).
- No secret rotation policy or mechanism beyond the MCP token (which rotates on restart).
- No audit log of secret access.
- If `.env` is stored on a shared or cloud filesystem, mode 600 provides no protection against root-level access or filesystem snapshot exposure.

**Risk:** Acceptable for single-operator use; insufficient for multi-team, multi-operator, or regulated environments.

---

## Deployment & Release Process

Bullpen provides deployment artifacts for three targets: Docker Compose, Fly.io, and DigitalOcean with nginx + systemd. This coverage is good for a project of this maturity. However:

- **No documented release process.** There is no versioning scheme visible in the repository, no changelog, no tag-and-release workflow.
- **No upgrade procedure documented.** A buyer cannot find instructions for upgrading from version N to N+1, including any data migration steps needed for flat-file schema changes.
- **No blue-green or canary deployment support.** Upgrades are presumably in-place, meaning downtime during restarts.
- **No pre-deployment checklist.** Operators have no standardized set of checks to run before deploying a new version to production.
- **Docker image:** Uses `python3.12-slim` with Node 22, non-root user — these are good security practices.
- **Run command:** `python3 bullpen.py` for local; Docker and systemd wrap this appropriately.

**Risk:** Upgrades are undocumented and potentially data-destructive if flat-file formats change between versions. The buyer cannot know whether any pending version bump requires a data migration.

---

## Findings

### HIGH — No Health Check Endpoint

No `/health` or `/healthz` route is confirmed in `app.py`. Without a health check endpoint, Docker, Fly.io, Kubernetes, and load balancers cannot distinguish a running-but-broken application from a healthy one. Automatic restart-on-failure and traffic routing depend on this signal.

**Remediation:** Add a `GET /health` route that returns `200 OK` with a JSON body confirming the application is up and (optionally) that key dependencies are accessible. Effort: under 1 hour.

---

### HIGH — No Backup Strategy for Flat-File Data Store

All persistent data lives in `.bullpen/` directories with no backup automation, no restore procedure, and no consistency guarantee during live backup. A single disk failure or operator error results in permanent, total data loss.

**Remediation:** Implement automated backup to an off-host target (S3, Backblaze B2, or equivalent). A daily `tar | gzip | upload` cron job is a minimum viable baseline. Document restore procedure and test it. For Fly.io deployments, configure volume snapshots. Effort: 1–2 engineer-days to implement and document.

---

### HIGH — No CI/CD Pipeline

The repository has no automated test execution, no lint enforcement, and no automated deployment. Regressions can reach production undetected, and deployments are not repeatable.

**Remediation:** Add GitHub Actions (or equivalent) with at minimum: run `pytest` on pull request, lint with `flake8` or `ruff`, and optionally build and push a Docker image on merge to main. Effort: 1–2 engineer-days.

---

### MEDIUM — No Structured Logging

Log output uses Python's default logging format. Log lines are not parseable by standard log aggregation tools without custom parsing. Correlating events across a request lifecycle, identifying slow operations, or building dashboards from logs is not possible without significant post-processing.

**Remediation:** Configure a JSON log formatter (e.g., `python-json-logger`) as a drop-in replacement for the default formatter. Add request IDs to correlate log lines within a request. Effort: less than 1 engineer-day.

---

### MEDIUM — No Application Monitoring or Alerting

There are no metrics, no alerting thresholds, and no APM integration. Operators are blind to performance degradation, error rate spikes, and capacity exhaustion until a user reports a problem.

**Remediation:** At minimum, add a Prometheus metrics endpoint (`/metrics`) exposing request count, error count, active worker count, and task queue depth. Pair with a Grafana dashboard or integrate with a hosted service (Datadog, New Relic, Better Uptime for basic uptime alerting). Effort: 1–3 engineer-days depending on depth.

---

### MEDIUM — No Documented Upgrade or Rollback Procedure

There is no versioning scheme, no changelog, and no documented procedure for upgrading a running instance or rolling back a failed deployment. A buyer inherits operational risk from every future code change.

**Remediation:** Establish a semantic versioning scheme, maintain a CHANGELOG, and write a one-page upgrade runbook covering: pre-upgrade backup, in-place upgrade steps, post-upgrade verification, and rollback steps. Effort: 1 engineer-day to establish; ongoing discipline to maintain.

---

### LOW — Incident Response Not Documented

There is no runbook, no escalation path, and no post-mortem template. MTTR for incidents depends entirely on operator tribal knowledge.

**Remediation:** Write a one-page incident runbook covering: how to check if the service is up, where logs are, how to restart the service, how to identify and kill runaway worker subprocesses, and how to restore from backup. Effort: half an engineer-day.

---

### LOW — Secret Rotation Not Implemented Beyond MCP Token

API keys and credentials stored in `.env` have no rotation policy or mechanism. If a key is compromised, there is no automated path to rotate and redeploy.

**Remediation:** Document a manual rotation procedure for each secret type. For higher assurance, integrate a secrets manager that supports dynamic secrets or at least centralizes rotation. Effort: documentation is 1 hour; secrets manager integration is 1–3 engineer-days.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 3     |
| MEDIUM   | 3     |
| LOW      | 2     |

---

## Recommendations

1. **Before going live with any team:** Implement automated backup (HIGH), add a health check endpoint (HIGH, trivial effort), and configure restart-on-failure in the deployment target (most targets support this natively).

2. **Within first 30 days post-acquisition:** Add a CI pipeline (HIGH), structured logging (MEDIUM), and write the upgrade/rollback runbook (MEDIUM). These are table-stakes operational practices that will pay dividends on the first incident.

3. **Within first quarter:** Add application metrics and basic uptime alerting (MEDIUM). Even a free-tier uptime monitor (UptimeRobot, Better Uptime) watching the health endpoint is a material improvement over zero alerting.

4. **Ongoing:** Establish a versioning and changelog discipline before shipping any code change that modifies flat-file formats. A single undocumented schema change can silently corrupt task history for all workspaces.

5. **Due diligence item for buyer:** Ask the seller to demonstrate a full backup-and-restore cycle. If this cannot be demonstrated, assume no working backup exists and budget for potential data loss at acquisition handoff.
