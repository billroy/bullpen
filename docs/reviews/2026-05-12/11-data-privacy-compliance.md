# Data & Privacy Compliance Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Data protection officer / privacy compliance counsel evaluating for acquisition

---

## Executive Summary

Bullpen's data posture is favorable for a self-hosted developer tool. By design, it stores no personal data beyond authentication credentials and whatever content the operator and their agents write to task tickets. There is no telemetry, no analytics pipeline, no third-party data sharing, and no cloud sync. The privacy exposure is minimal in the self-hosted model. However, the product's authentication system and multi-user design mean it is architected to handle personal data (usernames, passwords, session tokens), and the compliance infrastructure for doing so responsibly — privacy policy, data subject request process, retention policies, encryption at rest — is absent. These gaps become material the moment the product is offered as a hosted service.

---

## Data Inventory

| Data Category | Where Stored | Sensitivity | Current Controls |
|---|---|---|---|
| Username + password hash | `~/.bullpen/.env` (mode 600) | HIGH | PBKDF2-SHA256 hash; file restricted |
| Session tokens | Flask session cookie (server-side secret) | HIGH | HttpOnly; SameSite=Lax; Secure only if BULLPEN_PRODUCTION=1 |
| MCP auth token | `.bullpen/config.json` (not mode 600) | MEDIUM | Not file-restricted; per-workspace |
| Task ticket content | `.bullpen/tasks/*.md` (no file restrictions) | MEDIUM | No encryption at rest |
| Agent execution logs | `.bullpen/logs/` (no file restrictions) | MEDIUM | No encryption at rest; no retention policy |
| Worker configuration | `.bullpen/layout.json` | LOW | No sensitive data by design |
| Usage/token metrics | Per-ticket `usage:` frontmatter field | LOW | No PII |

---

## Findings

### HIGH — No privacy policy or data handling documentation for multi-user deployments

**Detail:** Bullpen supports multi-user authentication (multiple username/password pairs via `BULLPEN_USERS_JSON`). When deployed for a team, it processes the personal data of those team members (at minimum: usernames, login events, session activity). GDPR Article 13 requires a privacy notice at the point of data collection. CCPA requires a privacy policy for covered California businesses.

In the self-hosted model, the operator bears primary responsibility as the data controller. However, Bullpen (as the data processor) should provide:
1. Documentation of what personal data is processed and how
2. Guidance for operators on fulfilling data subject rights (access, deletion, portability)
3. A `PRIVACY.md` in the repository that self-hosters can reference when creating their own privacy notice

**Recommendation:** Create `PRIVACY.md` at the repository root documenting: what data Bullpen collects (auth credentials, session state, operator-created ticket content, agent logs), how it is stored (local filesystem only, no cloud sync by default), how to delete a user's data (delete their entry from `.env`), and what an operator must disclose to their team members. This does not require legal counsel for the self-hosted case — it is a factual description of the system's behavior.

---

### HIGH — Task content and agent logs have no encryption at rest

**Detail:** Task tickets (`.bullpen/tasks/*.md`) and agent execution logs (`.bullpen/logs/`) are stored as plaintext files with no filesystem-level encryption. These files may contain:

- Proprietary source code discussed in task descriptions
- Security-sensitive information pasted into task bodies (API keys, credentials, internal URLs)
- Agent conversation logs containing confidential business logic

If the host is compromised, or if another user on a shared host has filesystem access, this content is fully readable. This is standard behavior for developer tools but represents a privacy risk for sensitive use cases.

**Recommendation:** Document this clearly in the README and `PRIVACY.md`: task content is stored unencrypted on the host filesystem. For sensitive deployments, recommend host-level full-disk encryption (LUKS, FileVault, BitLocker). Bullpen does not need to implement application-level encryption to address this — operator guidance is sufficient.

---

### MEDIUM — Session cookies are insecure unless `BULLPEN_PRODUCTION=1` is explicitly set

**Location:** `server/auth.py`, `server/app.py`

**Detail:** The `Secure` cookie attribute — which prevents cookie transmission over unencrypted HTTP — is only applied when `BULLPEN_PRODUCTION=1` is set. An operator who deploys Bullpen behind an HTTPS reverse proxy without setting this flag will serve session cookies that can be captured over HTTP if any redirect or mixed-content path is reachable. This is a known and documented failure mode (the auth system correctly requires `BULLPEN_PRODUCTION=1` for production) but the default is insecure.

Under GDPR Article 32, processors must implement "appropriate technical measures" to ensure security of processing. An insecure-by-default session cookie configuration is not compliant for a commercial offering.

**Recommendation:** Auto-detect HTTPS context by checking `X-Forwarded-Proto: https` (via Flask's `ProxyFix`) and apply `SESSION_COOKIE_SECURE=True` automatically when HTTPS is detected, removing the operator's manual responsibility. Add a startup warning log when non-localhost binding is detected and `BULLPEN_PRODUCTION` is unset.

---

### MEDIUM — MCP token stored in world-readable `config.json`

**Location:** `.bullpen/config.json`

**Detail:** The MCP authentication token is written to `config.json`, which does not receive the same `chmod 600` treatment as `~/.bullpen/.env`. On a multi-user host, any user with read access to the workspace directory can read the MCP token and impersonate an MCP agent. The token grants write access to the task management system (create, update tickets), which could be abused to manipulate task history or inject malicious content.

**Recommendation:** Move the MCP token from `config.json` to `~/.bullpen/secrets.json` (already mode 600) keyed by workspace ID. Store only a reference token ID in `config.json`. Alternatively, apply `chmod 600` to `config.json` at creation time in `server/init.py`.

---

### MEDIUM — No data retention policy or automated data deletion

**Detail:** Task tickets and agent logs accumulate indefinitely. There is no:
1. Configurable retention period after which completed/archived tasks are automatically purged
2. Log file rotation or maximum log size enforcement
3. Mechanism for a user to request deletion of their data (data subject access request support)

For a self-hosted tool, long-lived data accumulation is a low-risk operational issue. For a hosted service, indefinite retention without a policy violates GDPR Article 5(1)(e) (storage limitation principle) and creates liability when storage grows without bound.

**Recommendation:** Add a `data_retention_days` configuration option (default: no retention limit for self-hosted; recommended: 90 days for hosted). Add a background cleanup job that archives tasks older than the retention period and purges logs older than the limit. Implement a "delete my data" admin endpoint that removes all data associated with a given username.

---

### LOW — Login failure logging uses in-memory store only; no persistent audit trail

**Location:** `server/app.py` — `login_failures` in-memory dict

**Detail:** Login failure tracking (for throttling) is stored in memory. This means:
1. Failed login attempts are not persistently logged — if the server restarts, the failure history is lost.
2. There is no audit trail of who attempted to authenticate from what IP address at what time.
3. An attacker who triggers a server restart resets the login throttle.

Under GDPR Article 32 and general security logging requirements, authentication events (success and failure) should be logged persistently.

**Recommendation:** Write structured log lines for login success, login failure, and account lockout events. These go to stderr/journald in production. For audit trail purposes, this is sufficient — no separate audit log file is required if the process logs are persisted.

---

### LOW — No documented data subject rights procedure

**Detail:** GDPR Articles 15–22 grant data subjects the right to access, correct, delete, and port their data. For Bullpen deployed for a team, team members are data subjects. There is no documentation describing how an operator can:
1. Retrieve all data associated with a specific user (for a Subject Access Request)
2. Delete a user's account and associated data (for a Right to Erasure request)
3. Export a user's data in a portable format

In practice, deleting a user from `.env` removes their authentication data. Task content is not attributed to individual users in the data model (tasks belong to workspaces, not users), which limits erasure obligations. But this should be documented.

**Recommendation:** Include a "Data Subject Rights" section in `PRIVACY.md` explaining: (1) what user-linked data Bullpen stores (auth credentials only), (2) how to delete it (remove from `.env`), and (3) that task content is workspace-scoped and not user-attributable.

---

## Regulatory Readiness Summary

| Regulation | Self-Hosted Status | Hosted Service Status |
|---|---|---|
| GDPR | Low risk (operator is controller; minimal PII) | NOT READY — no privacy policy, no retention policy |
| CCPA | Low risk (B2B developer tool) | NOT READY — no privacy policy |
| SOC 2 Type II | N/A (no audit trail, no controls framework) | NOT READY |
| HIPAA | N/A (no health data) | N/A |
| COPPA | N/A (not a consumer app for minors) | N/A |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 3 |
| LOW | 2 |
