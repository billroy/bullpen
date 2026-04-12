# Legal and Regulatory Compliance Review — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Review of licensing obligations, open-source dependency compliance, AI model usage terms, data handling practices, and documentation for a developer tool that orchestrates AI CLI agents (Claude, Codex, Gemini).

---

## Findings

### HIGH — No LICENSE file in repository root

**Files:** Repository root (verified: no `LICENSE`, `LICENSE.md`, `LICENSE.txt`, or `COPYING` file exists)

The repository ships no license. Without an explicit license, copyright law in most jurisdictions treats the code as "all rights reserved" by default. If this project is or will be distributed publicly (GitHub, pip, etc.), contributors and users have no legal basis to use, modify, or redistribute it. All open-source dependencies assume their downstream users comply with their own license terms, which typically require a compatible upstream license.

**Recommendation:** Add a `LICENSE` file before any public distribution. MIT or Apache 2.0 are compatible with all current runtime dependencies.

---

### HIGH — No terms of service or usage policy

**Files:** Repository root, `static/index.html`, `static/login.html`

Bullpen orchestrates third-party AI services (Anthropic Claude, Google Gemini, OpenAI Codex). Each provider's API terms impose obligations on the operator:

- **Anthropic (Claude):** Usage policies prohibit certain content categories and require operators to implement safeguards when the API is exposed to end users.
- **Google (Gemini):** Terms of Service include acceptable use policies.
- **OpenAI (Codex):** Usage policies apply to API consumption.

The product ships no operator-facing terms of service or end-user agreement. If deployed in a multi-user context (shared team server), users have no documented understanding of the AI provider constraints that apply to their use.

**Recommendation:** Add a brief `USAGE.md` or link to each provider's terms from the login/auth flow when multi-user mode is active.

---

### MEDIUM — GDPR / data residency: task content sent to third-party AI providers

**Files:** `server/workers.py`, `server/agents/claude_adapter.py`, `server/agents/gemini_adapter.py`, `server/agents/codex_adapter.py`

When a worker processes a task, the full task body (title, description, and full Markdown body) is assembled into a prompt and passed to the AI provider CLI. If task content contains personal data (names, emails, code with embedded credentials, client information), this data is transmitted to third-party servers. 

The product provides no:
- Warning or disclosure to users that task content will be sent to AI providers.
- Mechanism to exclude sensitive tasks from AI processing.
- Data processing agreement (DPA) integration point.

This is a compliance gap under GDPR (Art. 28 — processor obligations), CCPA, and similar frameworks if the tool is used in a professional/enterprise context.

**Recommendation:** Add a disclosure in the README and optionally in the UI that task content is transmitted to the configured AI provider. Document which provider is used for each worker.

---

### MEDIUM — Expertise prompt and task body stored without data classification

**Files:** `server/persistence.py`, `.bullpen/tasks/`

Tasks are stored as Markdown files in `.bullpen/tasks/`. The expertise prompt (per-worker system prompt) is stored in `layout.json`. Neither storage location enforces or documents data classification. Users may inadvertently embed API keys, credentials, or PII in task descriptions or expertise prompts.

**Recommendation:** Add a note in the README that `.bullpen/` should be excluded from git via `.gitignore` (it currently is not automatically excluded) and should not contain credentials.

---

### LOW — `.bullpen/` not in `.gitignore` by default

**File:** `.gitignore` (verified absent from repository root)

There is no `.gitignore` file in the repository root (search performed). If a user initializes Bullpen in a git repository, `.bullpen/config.json` (which contains the MCP token), `layout.json` (which contains expertise prompts and worker configuration), and task files (which may contain sensitive content) could be inadvertently committed to git.

**Recommendation:** Add a `.gitignore` to the repository that excludes `.bullpen/` and documents this recommendation.

---

### LOW — No data retention or deletion mechanism

**Files:** `server/tasks.py`, `.bullpen/tasks/`

Tasks accumulate indefinitely in `.bullpen/tasks/`. Archived tasks move to `.bullpen/tasks/archive/` but are never deleted. There is no purge mechanism, retention policy, or TTL. Under GDPR's right-to-erasure and data minimization principles, this is a gap if personal data is stored in tasks.

**Recommendation:** Provide a documented procedure for purging archived tasks and consider a configurable retention policy.

---

## Positive Observations

- All dependencies (Flask, Werkzeug, Flask-SocketIO, eventlet, pytest) are permissively licensed (BSD, MIT, Apache 2.0) — no GPL contamination.
- Auth credentials are hashed (Werkzeug pbkdf2), not stored in plaintext.
- The product does not make outbound network calls itself — AI provider communication is entirely delegated to the provider's own CLI tools, which have their own auth flows.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| L1 | HIGH | No LICENSE file |
| L2 | HIGH | No terms of service / provider usage policy disclosure |
| L3 | MEDIUM | Task content sent to AI providers without disclosure |
| L4 | MEDIUM | No data classification for task storage |
| L5 | LOW | `.bullpen/` not excluded by `.gitignore` |
| L6 | LOW | No data retention or deletion mechanism |
