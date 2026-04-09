# Data & Privacy Compliance Review — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Data privacy officer / compliance analyst evaluating as a potential acquirer

---

## Scope

Review of data collection, storage, processing, and deletion practices; encryption at rest and in transit; data residency; third-party data sharing; GDPR/CCPA applicability; and operator/user data rights.

---

## Executive Summary

In its current form (localhost single-user tool, no telemetry, no external data transmission), Bullpen has minimal data privacy risk. All data remains on the operator's local machine. The primary privacy considerations arise from the AI model integrations: task content (which may include source code, documentation, or other sensitive material) is sent to external AI providers (Anthropic, OpenAI) for processing. This is not disclosed in-product. The absence of at-rest encryption, no data deletion tooling, and no documented data handling policy are gaps relative to any commercial or enterprise deployment.

---

## Data Inventory

| Data Type | Storage Location | Encrypted at Rest | Transmitted To |
|-----------|-----------------|-------------------|----------------|
| Task titles, descriptions, bodies | `.bullpen/tasks/*.md` (plaintext) | No | AI provider (as part of prompt) |
| Worker expertise prompts | `.bullpen/layout.json` (plaintext) | No | AI provider (as part of prompt) |
| Workspace context prompts | `.bullpen/` (plaintext) | No | AI provider (as part of prompt) |
| Agent output (task results) | `.bullpen/tasks/*.md` (appended) | No | No |
| Worker execution logs | `.bullpen/logs/` (plaintext) | No | No |
| Auth credentials | `~/.bullpen/.env` (scrypt hash + plaintext username) | No (file-level, mode 0600) | No |
| Session keys | `~/.bullpen/secret_key` (plaintext hex) | No (file-level, mode 0600) | No |
| Workspace registry | `~/.bullpen/projects.json` (plaintext) | No | No |
| Team/profile configs | `.bullpen/teams/*.json`, `.bullpen/profiles/*.json` | No | No |
| Browser session cookie | Browser storage | N/A (HTTPS at reverse proxy) | No |

---

## Findings

### HIGH — Task Data Sent to AI Providers Without In-Product Disclosure

**Location:** `server/agents/claude_adapter.py`, `server/agents/codex_adapter.py`, `server/workers.py`

When a worker runs, the assembled prompt (including the task title, description, body, and workspace/bullpen context) is sent to the configured AI provider (Anthropic for Claude, OpenAI for Codex) as a subprocess invocation. This data transmission:
1. Is not disclosed in the UI or README
2. May include proprietary source code, business logic, credentials accidentally included in task descriptions, or personal data
3. Is subject to the AI provider's data retention and processing terms, which the operator may not have reviewed

**GDPR relevance:** If the workspace contains personal data (e.g., task descriptions referencing employees, customers, or user data), the operator becomes a data controller and the AI provider becomes a data processor. A data processing agreement (DPA) with the AI provider is required under GDPR Art. 28.

**Recommendation:**
1. Add a disclosure in the README and in the worker configuration UI: "Task content is sent to [AI provider] for processing per their privacy policy."
2. Add a link to Anthropic's and OpenAI's data processing terms.
3. Add a config option to exclude specific fields from the prompt (e.g., `exclude_from_prompt: [body]`).

---

### MEDIUM — No Encryption at Rest

**Location:** `.bullpen/` directory, `~/.bullpen/.env`

All task data, configuration, and agent output is stored as plaintext files. The `.env` file containing the password hash and session key is protected by Unix file permissions (mode 0600), but the task content is not.

On a multi-user system or a stolen laptop, `.bullpen/` contents are readable by anyone with filesystem access. For a tool that processes source code and business logic, this is meaningful exposure.

**Recommendation:** Document that sensitive workspaces should be stored on encrypted filesystems (FileVault on macOS, BitLocker on Windows, LUKS on Linux). For a future product offering, consider encrypting `.bullpen/` with a key derived from the user's password.

---

### MEDIUM — No Data Deletion or Export Tool

**Location:** `bullpen.py`, `server/tasks.py` — no `--delete-workspace`, `--export`, or GDPR right-to-erasure tooling found.

While the current product has no end users (it is operated by the developer themselves), a commercial product must support:
- Right to erasure (GDPR Art. 17): ability to delete all data associated with an account
- Data portability (GDPR Art. 20): ability to export data in a machine-readable format

**Recommendation:** Add `bullpen --export-workspace PATH` and `bullpen --delete-workspace` CLI commands for complete workspace data export and erasure.

---

### MEDIUM — Auth Credentials File Contains Plaintext Username

**Location:** `~/.bullpen/.env`

The `.env` file stores:
- `BULLPEN_USERNAME=<plaintext>`
- `BULLPEN_PASSWORD_HASH=<scrypt hash>`
- `BULLPEN_SECRET_KEY=<hex>`

The username is stored in plaintext. While a username is not typically considered sensitive, it is a piece of personally identifiable information (PII) that could be cross-referenced with other breach data.

**Recommendation:** This is low-risk but worth documenting. The username field does not need cryptographic protection, but operators should be advised not to use personal identifiers (email addresses, full names) as their Bullpen username.

---

### LOW — No Audit Log for Data Access

**Location:** `server/app.py`, `server/events.py` — no access logging found.

There is no record of:
- Which files were accessed via the Files tab
- Which tasks were read or modified
- Which agent executions occurred

For a tool that processes potentially sensitive source code and business data, an audit trail would be valuable for incident response and compliance.

**Recommendation:** Log all file access events and task mutations to a structured log with timestamp, event type, and resource identifier. Store in `.bullpen/logs/audit.log`.

---

### POSITIVE FINDINGS

- **No telemetry:** No usage data, crash reports, or analytics are collected or transmitted. Confirmed by reviewing all source files and network calls.
- **No external APIs called (except AI providers):** No third-party analytics, error tracking (Sentry), or feature flag services.
- **Password never stored in plaintext:** Werkzeug scrypt hash is used. The plaintext password is handled only in memory during the `--set-password` flow.
- **Session key protected:** `~/.bullpen/secret_key` is created with mode 0600 and contains only a random hex string.
- **No persistent session storage:** Sessions are stored in Flask's signed cookie (not a server-side session store), so there is no server-side session database to compromise.

---

## GDPR/CCPA Applicability Assessment

| Scenario | GDPR Applies? | CCPA Applies? |
|----------|-------------|---------------|
| Localhost, single developer, no personal data in tasks | No | No |
| Localhost, tasks contain employee/customer personal data | Yes (operator is controller) | Depends on state |
| Hosted service with registered users | Yes | Yes (if CA users) |

**Current product:** Likely falls into row 1 or 2 depending on the operator's use. Row 2 is the operator's responsibility to manage.

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| PRIV-01 | Task data sent to AI providers without in-product disclosure | HIGH |
| PRIV-02 | No encryption at rest for task data | MEDIUM |
| PRIV-03 | No data deletion or export tool | MEDIUM |
| PRIV-04 | Auth credentials file contains plaintext username | MEDIUM |
| PRIV-05 | No audit log for data access | LOW |
