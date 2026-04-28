# Data & Privacy Compliance Review
*Bullpen — 2026-04-27*

---

## Executive Summary

Bullpen is a locally-deployed AI agent team manager. Its primary data flow is: a human operator creates tickets containing task descriptions, those tickets are assembled into prompts and sent to third-party AI providers (Anthropic Claude, OpenAI Codex, Google Gemini), and the resulting outputs are stored in flat files on the local filesystem. From a data privacy perspective, the application's exposure profile is determined almost entirely by what content the operator puts into tickets and worker configurations, because all of that content is transmitted verbatim to one or more AI provider APIs.

The codebase currently has no data retention policy, no deletion workflow, no explicit user consent mechanism for AI processing, and no personal-data inventory or data-flow documentation. For a single-user personal tool these omissions are acceptable; for a multi-user team deployment subject to GDPR, CCPA, or enterprise data governance requirements, they represent material compliance gaps that a buyer will need to address before deploying at scale.

Encryption at rest is absent: all workspace data (tickets, worker configurations, usage statistics) lives in plaintext flat files under `.bullpen/`. Credentials are hashed and the `.env` file is permission-restricted (`chmod 600`), but task content, agent outputs, and MCP tokens are stored without encryption. For deployments handling sensitive business data or personally identifiable information this is a significant gap.

---

## Data Inventory

### Credentials and Authentication Secrets
- **What:** Username(s), PBKDF2-HMAC-SHA256 password hash(es), Flask `SECRET_KEY`, per-workspace MCP authentication tokens.
- **Where:** `~/.bullpen/.env` (mode 600), `.bullpen/config.json` in each workspace.
- **Sensitivity:** High. The `.env` file is appropriately permission-restricted; `config.json` is not (see Findings).

### Ticket / Task Content
- **What:** Ticket titles, markdown descriptions, status, priority, type, tags, assignment history, AI agent output appended to ticket body, token-usage accounting fields, timestamps.
- **Where:** `.bullpen/tasks/<id>.md` flat files (frontmatter + markdown body). Archived tasks move to `.bullpen/archive/`.
- **Sensitivity:** Varies. Tickets routinely contain business logic descriptions, code context, requirements, bug reports, and sometimes inadvertent PII (names, email addresses, internal URLs, API endpoints).

### Worker Configurations
- **What:** Worker name, agent type, model selection, expertise/system prompt, trust mode, activation schedule, git auto-commit/auto-PR settings, custom shell commands.
- **Where:** `.bullpen/layout.json`.
- **Sensitivity:** Medium. Expertise prompts can contain internal domain knowledge; shell worker command strings can contain environment-specific paths and inline credentials if carelessly written.

### Agent Process Output
- **What:** Full stdout/stderr of AI agent CLI invocations, streamed to the UI and stored in ticket bodies upon completion.
- **Where:** Ticket `.md` files (appended to body on task completion), in-memory while the task runs.
- **Sensitivity:** Potentially high. Agent output can contain code, diffs, API responses, or accidentally surfaced secrets from the workspace.

### Usage / Token Accounting
- **What:** Per-task token counts (input, cached-input, output, reasoning, total) and wall-clock task duration.
- **Where:** Frontmatter of each `.bullpen/tasks/<id>.md` file.
- **Sensitivity:** Low. Aggregate usage data, no PII.

### Git Metadata
- **What:** Commit hashes, author names, commit subjects, commit bodies, file diffs — surfaced via `/api/commits` and `/api/commits/<hash>/diff`.
- **Where:** Git history of the workspace repository; not stored separately by Bullpen.
- **Sensitivity:** Medium. Commit metadata can contain author real names and email addresses (via `git log --format=%an`). Diffs can contain sensitive code.

### Login / Session State
- **What:** `authenticated` boolean, `username`, CSRF token — stored in Flask signed session cookies (client-side).
- **Where:** Browser cookie, signed with `SECRET_KEY`.
- **Sensitivity:** Medium. The cookie is signed but not encrypted; its payload is base64-decodable and reveals the stored username.

### Export Archives
- **What:** Full snapshots of workspace `.bullpen/` directories (all tickets, layout, profiles, config minus sensitive runtime fields).
- **Where:** Generated on demand, downloaded as ZIP, not retained server-side.
- **Sensitivity:** High. A workspace export is a complete data dump including all ticket content.

### Third-Party AI Provider Data (Anthropic, OpenAI, Google)
- **What:** The full assembled prompt including task title, description, agent expertise prompt, workspace context files, and prior ticket output. Responses returned by the provider API.
- **Where:** Transmitted over HTTPS to provider APIs during agent runs; stored in ticket bodies upon completion. No local cache of raw API payloads.
- **Sensitivity:** High. Whatever appears in a ticket is sent to the configured AI provider. This includes any PII or confidential business data in ticket descriptions.

---

## Findings

### HIGH — Ticket content is transmitted to AI providers without user consent controls

**Description:** When a worker picks up a task, the full ticket content (title, description, body, linked workspace file content) is assembled into a prompt and sent to whichever AI provider the worker is configured for (Anthropic, OpenAI, or Google). There is no per-task consent prompt, no data-classification gate, no option to exclude specific tickets from AI processing, and no warning to the user that the content will leave the local environment. Multi-user deployments could result in one user's ticket content being processed by an AI provider without that user's knowledge.

**Location:** `server/agents/*.py` adapters; `server/workers.py` prompt assembly.

**Impact:** Non-compliance with GDPR Article 13/14 (transparency about processing), Article 6 (lawful basis for processing), and CCPA disclosure requirements in multi-user contexts. Enterprise customers with data-residency requirements may be unable to use Bullpen at all without this gate.

**Recommendation:** Display a workspace-level disclosure that AI providers will process ticket content. Provide a per-worker or per-ticket "do not send to AI" flag. Document which providers receive which data categories in a privacy notice.

---

### HIGH — No encryption at rest for task content and agent output

**Description:** All task files, layout configuration, and agent outputs are stored as plaintext files under the workspace's `.bullpen/` directory. Only the credential file (`.env`) has restricted permissions; task content is readable by any process running as the same OS user, or by any user with filesystem access to the workspace.

**Location:** All files under `.bullpen/tasks/`, `.bullpen/archive/`, `.bullpen/layout.json`.

**Impact:** On a shared host, a server compromise, or a stolen disk image, all ticket content (which may include business-confidential information or PII) is immediately readable without any cryptographic barrier.

**Recommendation:** Evaluate at-rest encryption options: filesystem-level encryption (LUKS, FileVault, or BitLocker depending on OS), application-level encryption of task bodies using a key derived from the user's password, or integration with a secrets manager. At minimum, set `chmod 700` on the `.bullpen/` directory.

---

### HIGH — No data retention policy or automatic deletion of archived tasks

**Description:** Completed tasks are moved to `.bullpen/archive/` but never automatically purged. There is no configurable retention period, no TTL on archived tickets, and no documented procedure for deletion. Over time the archive accumulates all historical task content including any PII or confidential data that appeared in tickets.

**Location:** `server/tasks.py` (archive logic); no scheduler or cleanup routine found.

**Impact:** Indefinite retention of potentially sensitive data is a GDPR violation (Article 5(1)(e) storage limitation principle) and conflicts with most enterprise data governance policies. Right-to-erasure requests (GDPR Article 17) cannot be fulfilled without a manual filesystem search.

**Recommendation:** Add a configurable retention period for archived tasks (e.g. 90 days default). Implement an automatic purge job in the scheduler. Provide an administrative "delete all data for user X" workflow.

---

### MEDIUM — No right-to-erasure or data portability workflow

**Description:** Bullpen has no in-application mechanism to identify all data associated with a specific user and delete or export it. In single-user mode this is acceptable; in multi-user mode (where multiple users can have separate accounts), it is not possible to determine which tickets were created by or assigned to a specific user without manual filesystem inspection.

**Location:** No user-attribution metadata in task frontmatter; no API endpoint for user-scoped data export or deletion.

**Impact:** GDPR Articles 17 (erasure) and 20 (portability) cannot be fulfilled in a multi-user deployment without manual operator intervention.

**Recommendation:** Add a `created_by` field to task frontmatter populated at creation time. Implement an admin API endpoint that returns all tasks attributable to a given username. Expose a per-user data export (separate from workspace export) and a deletion workflow.

---

### MEDIUM — Session cookie payload reveals username without encryption

**Description:** Flask's default session implementation signs cookies with the `SECRET_KEY` but does not encrypt them. The `username` stored in the session is base64-decodable by anyone who obtains the cookie value (e.g. from browser storage, network capture, or logs).

**Location:** `server/auth.py` lines 309–316 (session population); Flask itsdangerous cookie serialization.

**Impact:** In scenarios where session cookies are logged or captured (e.g. proxy logs, browser sync), usernames are disclosed. For a single-user personal tool this is low risk; in a corporate deployment username disclosure can facilitate targeted attacks.

**Recommendation:** Enable Flask-Talisman or switch to server-side sessions (Flask-Session with a Redis or filesystem backend) so only an opaque session ID is stored in the cookie. Alternatively, accept the risk and ensure `SESSION_COOKIE_SECURE=True` is always set in production.

---

### MEDIUM — Workspace export archives include all task content with no redaction

**Description:** The `/api/export/workspace` and `/api/export/all` endpoints create ZIP archives containing the complete `.bullpen/` directory for one or all workspaces, including all task files, profiles, and layout. The export deliberately strips `server_host`, `server_port`, and `mcp_token` from `config.json` (`_portable_config()`), but makes no attempt to scrub PII or sensitive content from task bodies.

**Location:** `server/app.py` lines 672–765 (`_export_workspace_zip_bytes`, `_export_all_zip_bytes`).

**Impact:** A user who downloads a workspace export and shares it (e.g. with a support engineer or on a public forum for troubleshooting) inadvertently shares all historical ticket content. In a multi-user environment, one user can export another user's task data if they share workspace access.

**Recommendation:** Add a warning on the export UI noting that the archive contains all task content. Consider a "sanitised export" option that omits task bodies. In multi-user mode, scope exports to the requesting user's accessible data only.

---

### MEDIUM — Git author data (real names) exposed via unauthenticated-like API surface

**Description:** `/api/commits` returns `author` (the git author name string, from `%an`) for each commit. While the endpoint is protected by `@require_auth`, git author names are real names and constitute PII under GDPR in many interpretations. There is no opt-out or pseudonymisation mechanism.

**Location:** `server/app.py` lines 494–533.

**Impact:** In a team deployment, any authenticated user can enumerate the names of all commit authors in the workspace repository. This may conflict with internal pseudonymisation policies.

**Recommendation:** Document the author-name disclosure in the privacy notice. Provide a configuration option to omit or hash author names in the commits API response.

---

### LOW — MCP token stored in world-readable `config.json`

**Description:** The per-workspace MCP token (a `secrets.token_urlsafe(32)` value) is written to `.bullpen/config.json`, which inherits default filesystem permissions (typically `644`). While the token is a bearer credential for MCP connections rather than user data, its presence in a broadly readable file is a secret-management deficiency.

**Location:** `server/mcp_auth.py` lines 54–55.

**Impact:** Local-user disclosure of a machine-authentication credential. Low PII impact; higher integrity risk (see security audit).

**Recommendation:** Apply `chmod 600` to `config.json` or store the MCP token in a separate permission-restricted file.

---

### LOW — No documented data-flow map for AI provider data sharing

**Description:** There is no in-codebase or in-documentation specification of which data fields are included in prompts sent to each AI provider, what the provider's data retention policy is, or whether the provider uses submitted data for model training. Different providers (Anthropic, OpenAI, Google) have materially different data usage terms.

**Location:** No `PRIVACY.md` or equivalent; no per-provider data-sharing disclosure.

**Impact:** Operators deploying Bullpen in regulated environments cannot demonstrate compliance with GDPR Article 28 (processor agreements) or CCPA business-purpose disclosure without this information.

**Recommendation:** Add a `PRIVACY.md` or a section in `README.md` documenting: what data is sent to each provider, links to each provider's data processing addendum, and how to configure which provider is used per worker.

---

### LOW — Usage/token metrics stored indefinitely in task frontmatter

**Description:** Token counts and task durations are recorded in each task's frontmatter and persist in the archive. While these fields contain no direct PII, they do reveal the volume of AI processing performed on each ticket, which can be used to infer sensitivity or business activity patterns.

**Location:** `server/usage.py`; task frontmatter fields `input_tokens`, `output_tokens`, `task_time_ms`.

**Impact:** Minimal in isolation; relevant in aggregation for a privacy-conscious operator.

**Recommendation:** Include usage metrics in the retention/deletion scope of the data retention policy recommended above.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 3     |
| MEDIUM   | 4     |
| LOW      | 3     |

---

## Recommendations

Listed in priority order:

1. **[HIGH] Add AI processing disclosure and consent controls** — Before content is sent to an AI provider, display a clear disclosure and provide a per-worker or per-ticket opt-out. This is the foundational requirement for GDPR/CCPA compliance in multi-user deployments.
2. **[HIGH] Implement data retention and automatic archival purge** — Add a configurable retention TTL for archived tasks and a scheduler-driven purge. Document and implement a right-to-erasure workflow.
3. **[HIGH] Evaluate encryption at rest** — Apply at minimum `chmod 700` to the `.bullpen/` directory; evaluate application-level or filesystem-level encryption for task content.
4. **[MEDIUM] Add per-user data attribution, portability, and erasure endpoints** — Tag tasks with `created_by` at creation time; implement admin API endpoints for user-scoped export and deletion.
5. **[MEDIUM] Publish a data-flow and privacy notice** — Document which fields are sent to each AI provider, the provider's DPA links, and Bullpen's own data handling practices.
6. **[MEDIUM] Restrict workspace exports to authenticated user's data scope** — In multi-user mode, prevent one user from exporting another user's tasks.
7. **[LOW] Restrict `config.json` permissions** — Apply `chmod 600` to protect the MCP token and any future secrets written alongside workspace configuration.
8. **[LOW] Switch to server-side sessions** — Eliminate username disclosure from client-side cookie payload by using opaque session IDs.
