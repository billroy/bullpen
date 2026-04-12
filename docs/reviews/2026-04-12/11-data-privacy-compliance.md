# Data & Privacy Compliance Review — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Review of data collection, storage, processing, transmission, and deletion practices against GDPR, CCPA, and general privacy engineering principles.

---

## Summary

Bullpen is a local-first tool that stores data on the user's filesystem. It does not have a cloud backend. Its primary privacy risks arise from: (1) task content being transmitted to third-party AI providers, (2) task files potentially containing personal data without any safeguards, and (3) the absence of data classification, retention policies, or deletion mechanisms.

---

## Data Inventory

| Data Type | Where Stored | Transmitted To |
|-----------|-------------|----------------|
| Task titles, descriptions, bodies | `.bullpen/tasks/*.md` | AI provider CLI (when processed by worker) |
| Worker expertise prompts | `.bullpen/layout.json` | AI provider CLI (as system prompt) |
| Auth credentials (hashed) | `~/.bullpen/.env` | Never transmitted |
| Flask SECRET_KEY | `~/.bullpen/.env` | Never transmitted |
| MCP token | `.bullpen/config.json` | Main server (local socket only) |
| Token usage data | `.bullpen/tasks/*.md` (history field) | Never transmitted |
| Server host/port | `.bullpen/config.json` | Never transmitted |
| Session data | Flask session (signed cookie) | Browser only |
| Worker profiles | `.bullpen/profiles/*.json` | AI provider CLI (as expertise prompt) |

---

## Findings

### HIGH — Task content transmitted to third-party AI providers without explicit user consent or disclosure

**Files:** `server/workers.py`, `server/agents/*.py`

When a worker processes a task, the full task body (assembled as a prompt) is passed to the Claude, Gemini, or Codex CLI tool. This data is transmitted to Anthropic, Google, or OpenAI's servers respectively. Users are not notified at the point of task creation or worker assignment that their task content will be sent to an external AI provider.

Under GDPR Article 13, data subjects must be informed about the purposes and recipients of processing at the time data is collected. If any task contains personal data (names, contact information, code with credentials), this constitutes an unnotified cross-border data transfer to a third party.

**Recommendation:** Add a disclosure in the UI when a worker is assigned to a task, indicating which AI provider will receive the task content. Add a note in the README documenting this data flow.

---

### HIGH — No data deletion mechanism for task content

**Files:** `server/tasks.py`, `.bullpen/tasks/`

Tasks are never automatically deleted. Archive moves tasks to `.bullpen/tasks/archive/` but retains all data indefinitely. Under GDPR Article 17 (Right to Erasure) and the principle of data minimization (Article 5(1)(e)), data should not be retained longer than necessary.

**Recommendation:** Implement a delete function that permanently removes task files (not just archives them). Provide a bulk-delete or export-then-delete workflow for archived tasks.

---

### MEDIUM — Auth credentials in `~/.bullpen/.env` protected only by filesystem permissions

**Files:** `server/auth.py:81–108`

The `.env` file containing hashed passwords and the Flask SECRET_KEY is created with `0o600` permissions. This is correct for POSIX systems. However:
- On Windows, `os.chmod(path, 0o600)` is documented as a no-op for most permission bits.
- If the user runs Bullpen as root (not recommended but possible), `0o600` root-owned files are still readable by root.
- There is no encryption at rest for the credential file.

**Recommendation:** Document that running as root is unsupported. For Windows deployments, add a note that filesystem permissions do not apply and auth security is limited.

---

### MEDIUM — Token usage history stored indefinitely in task files

**Files:** `server/usage.py`, `.bullpen/tasks/*.md` (history field in frontmatter)

Every agent run appends a usage entry to the task's `history` field containing: timestamp, provider, model, token counts. This data accumulates without bound. While token counts are not personally identifiable, the timestamps create a behavioral log of when the user worked and for how long.

**Recommendation:** Add a configurable retention limit for usage history entries (e.g., keep last 100 entries per task). Document that usage history is stored locally only.

---

### MEDIUM — `.bullpen/` directory may be committed to git

**Files:** Repository root (verified: no `.gitignore` file)

There is no `.gitignore` at the project root. If a developer initializes Bullpen in an existing git repository and does not add `.bullpen/` to their `.gitignore`, the following data may be inadvertently committed:
- Task bodies (potentially containing PII, credentials, internal information).
- `config.json` (containing MCP token).
- `layout.json` (containing expertise prompts which may contain project-specific instructions).
- `profiles/` (custom AI system prompts).

**Recommendation:** Add a `.gitignore` to the repository root that includes `.bullpen/`. Display a startup warning if `.bullpen/` is not in the workspace's `.gitignore`.

---

### LOW — Session cookie lacks `Secure` flag

**File:** `server/app.py:120`

`SESSION_COOKIE_SECURE=False` is hard-coded. If Bullpen is deployed with TLS (via reverse proxy), the session cookie will still be transmitted without the `Secure` flag, allowing it to be sent over HTTP connections in some browser contexts. This is a data security issue for authenticated sessions.

---

### LOW — Chat session history not cleared after session end

**File:** `server/events.py` (chat session state management)

Live Agent Chat sessions accumulate message history in `_chat_sessions` (module-level dict). This history persists in memory for the lifetime of the server process. Chat messages that contain sensitive information (API keys, internal data) remain accessible in memory indefinitely.

**Recommendation:** Implement TTL-based expiry for inactive chat sessions. Document that chat history is in-memory only and is lost on server restart.

---

### LOW — No privacy policy or data processing documentation

**Files:** Repository root, `static/login.html`

There is no privacy policy, data processing agreement (DPA), or data processing documentation. For organizational deployments or any use involving personal data, this is required under GDPR Article 30 (Records of Processing Activities).

**Recommendation:** Add a `PRIVACY.md` to the repository that documents what data Bullpen collects, where it stores it, what it transmits, and how it can be deleted.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| DP1 | HIGH | Task content transmitted to AI providers without disclosure |
| DP2 | HIGH | No data deletion mechanism (GDPR right to erasure) |
| DP3 | MEDIUM | Credential file permissions not enforced on Windows |
| DP4 | MEDIUM | Usage history grows unbounded |
| DP5 | MEDIUM | No `.gitignore` protecting `.bullpen/` from accidental commit |
| DP6 | LOW | Session cookie lacks `Secure` flag |
| DP7 | LOW | Chat session history not TTL-expired |
| DP8 | LOW | No privacy policy or data processing documentation |
