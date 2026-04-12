# Workplan — Bullpen Omnibus Review
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12
This is a read-only output document. Do not edit. Track completion in `docs/planning/todo.md` or via git commits.

---

## Prioritized Implementation Phases

Items are grouped into ~20-minute phases. HIGH-priority items appear first, MEDIUM second, LOW last. Within a phase, items are sequenced for logical dependency.

---

### Phase 1 — HIGH: Security & Auth (critical exposure)

**sec-enforce-nonlocal-auth**  · Priority: HIGH
Source: 01-security-audit.md — "HIGH — Auth disabled by default with no runtime warning to network listeners"
- Files: `server/app.py` (create_app, ~line 122–135), `bullpen.py`
- Changes: In `create_app()`, when `host != "127.0.0.1"` and `not auth.auth_enabled()`, print a prominent multi-line banner to stderr and optionally raise `SystemExit`. Add a `--require-auth` flag to CLI to make enforcement optional.
- Done when: Starting Bullpen with `--host 0.0.0.0` and no credentials configured prints a visible multi-line warning (or exits); no warning is shown for `127.0.0.1`.
- Commit: `security: warn (or block) when auth disabled and server bound to non-loopback address`

**sec-session-cookie-secure**  · Priority: HIGH
Source: 01-security-audit.md — "HIGH — `SESSION_COOKIE_SECURE=False` hard-coded"
- Files: `server/app.py` (~line 120)
- Changes: Replace `SESSION_COOKIE_SECURE=False` with a value derived from an env var (e.g., `BULLPEN_SECURE_COOKIES=1`) or by detecting `X-Forwarded-Proto: https` in a middleware. Default remains `False` for localhost.
- Done when: With `BULLPEN_SECURE_COOKIES=1` set, the `Set-Cookie` response header for the session cookie includes the `Secure` attribute; without the var it does not.
- Commit: `security: make SESSION_COOKIE_SECURE configurable for TLS-terminated deployments`

---

### Phase 2 — HIGH: Legal & IP (blocking for any distribution)

**legal-add-license-file**  · Priority: HIGH
Source: 02-legal-compliance.md — "HIGH — No LICENSE file in repository root"
Source: 03-brand-ip-audit.md — "HIGH — No LICENSE file or copyright notice"
Source: 12-license-audit.md — "HIGH — No LICENSE file — undefined terms for users and contributors"
- Files: `LICENSE` (new file at repository root), `bullpen.py` (optional copyright header)
- Changes: Create `LICENSE` with MIT or Apache 2.0 text and copyright year/owner. Optionally add `# Copyright (c) 2026 <owner>` to `bullpen.py`.
- Done when: `ls LICENSE` at repository root returns the file; file contains a recognized SPDX license identifier and copyright statement.
- Commit: `legal: add MIT LICENSE file`

**legal-add-usage-disclosure**  · Priority: HIGH
Source: 02-legal-compliance.md — "HIGH — No terms of service or usage policy"
- Files: `README.md`, optionally `static/login.html`
- Changes: Add a "Provider Usage Terms" section to `README.md` referencing Anthropic, Google, and OpenAI acceptable use policies. If multi-user auth is enabled, optionally surface a disclosure on the login page.
- Done when: `README.md` contains a section describing provider terms obligations and links to Anthropic, Google, and OpenAI usage policy pages.
- Commit: `docs: add AI provider usage policy disclosure to README`

---

### Phase 3 — HIGH: CI/CD (quality gate)

**ops-add-cicd-pipeline**  · Priority: HIGH
Source: 06-tech-due-diligence.md — "HIGH — No CI/CD pipeline"
Source: 10-operational-practice.md — "HIGH — No CI/CD pipeline"
- Files: `.github/workflows/ci.yml` (new file)
- Changes: Create a GitHub Actions workflow that runs `python3 -m pytest tests/ -x -q` on every push and pull request to `main`. Include Python version matrix (3.10, 3.11, 3.12).
- Done when: A push to any branch triggers the Actions workflow; `pytest` results appear in the GitHub PR checks panel.
- Commit: `ops: add GitHub Actions CI workflow running pytest`

---

### Phase 4 — HIGH: Test Coverage (security-critical gaps)

**test-add-file-api-traversal-tests**  · Priority: HIGH
Source: 04-test-coverage.md — "HIGH — No test coverage for file API path traversal"
- Files: `tests/test_e2e.py` or new `tests/test_file_api.py`
- Changes: Add tests that: (1) send `GET /api/files/../etc/passwd` and assert HTTP 400/403; (2) send `PUT /api/files/../escape` and assert rejection; (3) send a body >1MB to the file write endpoint and assert 413/400.
- Done when: `pytest tests/test_file_api.py -v` passes and the three cases (traversal GET, traversal PUT, oversized body) all produce non-2xx status codes.
- Commit: `test: add path traversal and size limit tests for file API`

**test-add-socketio-auth-tests**  · Priority: HIGH
Source: 04-test-coverage.md — "HIGH — No test for auth bypass via Socket.IO direct connection"
- Files: `tests/test_auth_e2e.py` or new `tests/test_socketio_auth.py`
- Changes: Add tests that: (1) connect to Socket.IO with auth enabled and no credentials → verify disconnect/error; (2) connect with a valid MCP token and no session → verify connection accepted; (3) connect with an invalid MCP token → verify rejection.
- Done when: `pytest tests/test_socketio_auth.py -v` passes and covers all three auth scenarios.
- Commit: `test: add Socket.IO auth bypass and MCP token acceptance tests`

---

### Phase 5 — HIGH: Scalability (task loading)

**scale-paginate-task-list**  · Priority: HIGH
Source: 09-scalability.md — "HIGH — Full task list loaded on every client connect — O(n) over task count"
- Files: `server/tasks.py` (list_tasks), `server/app.py` (load_state), `static/app.js` or `static/components/`
- Changes: Add `offset` and `limit` parameters to `list_tasks()`. Update `load_state` to send an initial paginated batch (e.g., 100 tasks). Add frontend lazy-loading when the task list scrolls near the bottom.
- Done when: With 200 tasks in `.bullpen/tasks/`, the state:init Socket.IO event sends ≤100 tasks; subsequent tasks are fetched on scroll. `list_tasks(limit=50, offset=0)` returns 50 tasks and `list_tasks(limit=50, offset=50)` returns the next 50.
- Commit: `perf: paginate task list loading to avoid O(n) on state:init`

**scale-stream-output-to-file**  · Priority: HIGH
Source: 09-scalability.md — "HIGH — Worker output buffered in memory — 500KB per worker"
- Files: `server/workers.py` (output streaming loop)
- Changes: Write worker output incrementally to a per-task log file (e.g., `.bullpen/tasks/<slug>.log`) instead of accumulating in an in-memory buffer. Stream the log file to the frontend via a tailing read or socket emit. Retain the in-memory buffer only as a send queue, not as the source of truth.
- Done when: After an agent run completes, a `.bullpen/tasks/<slug>.log` file exists with the full output; the in-memory buffer variable is flushed/cleared and does not grow proportionally to output length.
- Commit: `perf: stream worker output to per-task log file instead of in-memory buffer`

---

### Phase 6 — MEDIUM: Security (hardening)

**sec-restrict-mcp-config-permissions**  · Priority: MEDIUM
Source: 01-security-audit.md — "MEDIUM — MCP token stored plaintext in `.bullpen/config.json`"
- Files: `server/app.py` (~line 162–165), `server/persistence.py` (atomic_write)
- Changes: After writing `config.json`, call `os.chmod(path, 0o600)`. Or add a `mode` parameter to `atomic_write` and pass `0o600` for config.json writes.
- Done when: After server startup, `stat -f %Lp .bullpen/config.json` (macOS) or `stat -c %a .bullpen/config.json` (Linux) returns `600`.
- Commit: `security: restrict .bullpen/config.json permissions to 0o600`

**sec-fix-next-url-encoding**  · Priority: MEDIUM
Source: 01-security-audit.md — "MEDIUM — `next` redirect parameter not URL-encoded in `require_auth`"
- Files: `server/auth.py` (~line 313–316)
- Changes: Replace `f"?next={next_url}"` with `f"?next={urllib.parse.quote(next_url, safe='/')}"`. Import `urllib.parse` if not already imported.
- Done when: A request to a path containing `&` or `=` characters (e.g., `/page?foo=bar`) redirects to `/login?next=%2Fpage%3Ffoo%3Dbar` (properly encoded).
- Commit: `security: URL-encode the next parameter in require_auth redirect`

**sec-gemini-prompt-stdin**  · Priority: MEDIUM
Source: 01-security-audit.md — "MEDIUM — Gemini prompt passed as CLI argument (visible in `ps aux`)"
- Files: `server/agents/gemini_adapter.py` (~line 76)
- Changes: If the Gemini CLI supports stdin input, remove `--prompt <text>` from argv and write the prompt to the process's stdin. If stdin is not supported, write the prompt to a named temp file, pass the file path, and delete the file after the process is spawned.
- Done when: `ps aux | grep gemini` during an active Gemini run does not show the task prompt text in the argument list.
- Commit: `security: pass Gemini prompt via stdin/tempfile instead of CLI argument`

**sec-mcp-token-compare-digest**  · Priority: LOW
Source: 01-security-audit.md — "LOW — Token comparison for MCP auth uses `==` not `secrets.compare_digest`"
- Files: `server/app.py` (~line 457)
- Changes: Replace `token != expected` with `not secrets.compare_digest(token, expected)`.
- Done when: The MCP auth check in `on_connect` uses `secrets.compare_digest`; grep for `compare_digest` in `app.py` returns a match.
- Commit: `security: use secrets.compare_digest for MCP token comparison`

---

### Phase 7 — MEDIUM: Code Quality (large module decomposition)

**refactor-extract-chat-module**  · Priority: HIGH
Source: 05-code-quality.md — "HIGH — `events.py` is 973 lines with deeply nested `_run_chat()` function"
- Files: `server/events.py`, new `server/chat.py`
- Changes: Extract the `_run_chat` function and its retry/MCP startup logic into `server/chat.py`. `events.py` retains only Socket.IO handler registration; `chat.py` exports a `run_chat(...)` function callable independently.
- Done when: `wc -l server/events.py` shows fewer than 500 lines; `server/chat.py` exists; `pytest tests/ -x -q` passes.
- Commit: `refactor: extract chat run logic from events.py into server/chat.py`

**refactor-extract-worker-submodules**  · Priority: HIGH
Source: 05-code-quality.md — "HIGH — `workers.py` is 1,108 lines mixing too many concerns"
- Files: `server/workers.py`, new `server/runner.py`, new `server/git_ops.py`
- Changes: Extract subprocess streaming into `server/runner.py`; extract auto-commit/PR logic into `server/git_ops.py`. `workers.py` becomes a state machine that imports from these modules.
- Done when: `wc -l server/workers.py` shows fewer than 600 lines; `server/runner.py` and `server/git_ops.py` exist; `pytest tests/ -x -q` passes.
- Commit: `refactor: split workers.py into runner.py and git_ops.py submodules`

**quality-fix-validate-config-types**  · Priority: MEDIUM
Source: 05-code-quality.md — "MEDIUM — `validate_config_update` passes raw values through without type checking"
- Files: `server/validation.py` (~line 229–242)
- Changes: Add per-key type coercion/validation for `agent_timeout_seconds` (int), `max_prompt_chars` (int), and `auto_commit` (bool) in `validate_config_update`. Raise `ValidationError` on wrong type.
- Done when: Sending `{"agent_timeout_seconds": "pwned"}` to the config update endpoint returns HTTP 400; `{"agent_timeout_seconds": 30}` succeeds.
- Commit: `fix: add type validation for numeric and boolean config keys`

**quality-log-swallowed-exceptions**  · Priority: MEDIUM
Source: 05-code-quality.md — "MEDIUM — Silent exception swallowing in several critical paths"
- Files: `server/app.py` (~line 581–583), `server/workers.py` (OSError catch blocks)
- Changes: Replace bare `except Exception: pass` and `except OSError: pass` with `except Exception as e: logging.getLogger(__name__).error("reconcile error: %s", e)` (and similar for workers).
- Done when: Triggering an error in `reconcile()` (e.g., by corrupting layout.json) produces a log line to stderr; no silent swallowing occurs.
- Commit: `fix: log exceptions in reconcile() and worktree cleanup instead of swallowing`

---

### Phase 8 — MEDIUM: Operational Practice

**ops-add-structured-logging**  · Priority: HIGH
Source: 10-operational-practice.md — "HIGH — No structured logging — print-to-stderr only"
- Files: `server/app.py`, `server/workers.py`, `server/events.py`, `server/auth.py`
- Changes: Replace `print(..., file=sys.stderr)` calls with `logging.getLogger(__name__)` at appropriate levels. Add `logging.basicConfig(level=os.environ.get("BULLPEN_LOG_LEVEL", "INFO"))` in `bullpen.py`. Log auth events (login, logout, auth failure) at INFO level.
- Done when: Starting Bullpen with `BULLPEN_LOG_LEVEL=DEBUG` produces structured log lines with timestamps and level names; no bare `print(...)` calls remain in server modules (grep confirms).
- Commit: `ops: replace print-to-stderr with structured logging module`

**ops-add-backup-export**  · Priority: HIGH
Source: 10-operational-practice.md — "HIGH — No backup/recovery mechanism for `.bullpen/` data"
- Files: `bullpen.py` (CLI), new `server/export.py`
- Changes: Add a `bullpen --export [output-path]` CLI subcommand that creates a timestamped zip of `.bullpen/`. Document recovery steps in `README.md`.
- Done when: Running `python3 bullpen.py --export /tmp/backup.zip` creates a valid zip file containing all `.bullpen/` contents; `README.md` contains an "Export & Recovery" section.
- Commit: `ops: add --export subcommand for .bullpen/ backup`

**ops-add-health-endpoint**  · Priority: MEDIUM
Source: 06-tech-due-diligence.md — "MEDIUM — No health check endpoint"
Source: 10-operational-practice.md — "MEDIUM — No health check endpoint"
- Files: `server/app.py`
- Changes: Add `GET /health` route returning `{"ok": True, "version": __version__}` with HTTP 200. No auth required.
- Done when: `curl http://localhost:5173/health` returns HTTP 200 and JSON body containing `"ok": true`.
- Commit: `ops: add GET /health endpoint for load balancer and monitoring`

**ops-add-gitignore**  · Priority: MEDIUM
Source: 02-legal-compliance.md — "LOW — `.bullpen/` not in `.gitignore` by default"
Source: 11-data-privacy-compliance.md — "MEDIUM — `.bullpen/` directory may be committed to git"
- Files: `.gitignore` (new file at repository root)
- Changes: Create `.gitignore` containing `.bullpen/`, `*.pyc`, `__pycache__/`, `.env`, and `*.egg-info/`.
- Done when: `git status` after creating `.bullpen/` in a fresh repo does not show `.bullpen/` as an untracked file.
- Commit: `ops: add .gitignore excluding .bullpen/ and Python build artifacts`

---

### Phase 9 — MEDIUM: Data & Privacy

**data-add-provider-disclosure-ui**  · Priority: HIGH
Source: 11-data-privacy-compliance.md — "HIGH — Task content transmitted to AI providers without disclosure"
Source: 02-legal-compliance.md — "MEDIUM — GDPR / data residency: task content sent to third-party AI providers"
- Files: `static/components/WorkerCard.js` or task assignment flow, `README.md`
- Changes: Add a tooltip or disclosure note in the worker assignment UI indicating which AI provider will receive the task content. Add a "Data Processing" section to `README.md` documenting that task content is sent to the configured AI provider.
- Done when: `README.md` contains a "Data Processing" section with provider disclosure; the UI shows which provider a worker uses when a task is assigned.
- Commit: `data: add disclosure when task content is transmitted to AI provider`

**data-add-task-delete**  · Priority: HIGH
Source: 11-data-privacy-compliance.md — "HIGH — No data deletion mechanism (GDPR right to erasure)"
- Files: `server/tasks.py`, `server/events.py`, `server/app.py` (API route), `static/` (delete button)
- Changes: Add a permanent delete function to `tasks.py` that removes the `.md` file (not just archives it). Expose via a Socket.IO event or REST endpoint. Add a "Delete permanently" option in the task detail panel.
- Done when: Permanently deleting a task removes its `.md` file from `.bullpen/tasks/` and `.bullpen/tasks/archive/`; the task no longer appears after state:init.
- Commit: `data: add permanent task deletion for GDPR right-to-erasure compliance`

---

### Phase 10 — MEDIUM: Architecture

**arch-introduce-service-layer**  · Priority: HIGH
Source: 08-architecture.md — "HIGH — No service layer — business logic coupled to Socket.IO transport"
- Files: new `server/services/` directory, `server/events.py`, `server/workers.py`
- Changes: Create `server/services/task_service.py` and `server/services/worker_service.py` extracting business logic (task CRUD, worker state transitions) callable without Socket.IO context. Event handlers become thin wrappers.
- Done when: `server/services/task_service.py` exists; `create_task(workspace, data)` can be called from a unit test without importing `socketio`; `pytest tests/ -x -q` passes.
- Commit: `refactor: introduce service layer to decouple business logic from Socket.IO transport`

**arch-per-workspace-locks**  · Priority: HIGH
Source: 08-architecture.md — "HIGH — Shared module-level write_lock is a single serialization point"
Source: 09-scalability.md — "HIGH — Single write_lock serializes all concurrent worker state updates"
- Files: `server/locks.py`, `server/workspace_manager.py`, `server/workers.py`, `server/events.py`
- Changes: Replace the single global `write_lock` with a per-workspace lock stored in `WorkspaceState`. All callers that acquire `write_lock` must acquire the workspace-specific lock instead.
- Done when: `server/locks.py` does not export a global lock; `WorkspaceState` has a `write_lock` attribute; `pytest tests/ -x -q` passes.
- Commit: `refactor: replace global write_lock with per-workspace locks`

---

### Phase 11 — MEDIUM: Technical Due Diligence

**td-pin-cli-versions**  · Priority: HIGH
Source: 06-tech-due-diligence.md — "HIGH — Complete dependence on third-party CLI tools for core functionality"
- Files: `README.md`, new `docs/DEPENDENCIES.md`, `server/agents/claude_adapter.py`, `server/agents/gemini_adapter.py`, `server/agents/codex_adapter.py`
- Changes: Add minimum CLI version constants to each adapter (e.g., `MIN_CLAUDE_VERSION = "1.0"`). Add startup detection that warns if the detected CLI version is below the minimum. Document minimum versions in `DEPENDENCIES.md`.
- Done when: Starting Bullpen with an outdated Claude CLI prints a warning to stderr; `DEPENDENCIES.md` lists minimum CLI versions for all three providers.
- Commit: `ops: add minimum CLI version detection and documentation for agent dependencies`

**td-add-version-number**  · Priority: LOW
Source: 06-tech-due-diligence.md — "LOW — No version number or release tracking"
- Files: `bullpen.py`, new `pyproject.toml`
- Changes: Add `__version__ = "0.1.0"` to `bullpen.py`. Create a minimal `pyproject.toml` with `[project]` metadata (name, version, python_requires). Expose `--version` flag in the CLI.
- Done when: `python3 bullpen.py --version` prints `bullpen 0.1.0`; `pyproject.toml` exists with a `[project]` table.
- Commit: `chore: add version number and pyproject.toml package metadata`

---

### Phase 12 — MEDIUM: Test Coverage (additional gaps)

**test-agent-argv-construction**  · Priority: MEDIUM
Source: 04-test-coverage.md — "MEDIUM — Agent adapter tests mock subprocess; no real adapter argv tests"
- Files: `tests/test_agents.py`
- Changes: Add tests on real adapter instances (not MockAdapter) that call `build_argv()` and assert: (1) prompt text does not appear in positional argv for Claude; (2) MCP config temp file is valid JSON; (3) after the Gemini fix, prompt is not in argv for GeminiAdapter.
- Done when: `pytest tests/test_agents.py -v` passes with the new tests; tests assert specific argv content.
- Commit: `test: add argv construction and MCP config tests for real agent adapters`

**test-handoff-depth-limit**  · Priority: MEDIUM
Source: 04-test-coverage.md — "MEDIUM — Worker handoff depth limit not tested"
- Files: `tests/test_workers.py`
- Changes: Add a test that simulates 10 sequential handoffs and verifies the 11th handoff is refused gracefully (task state set to error or blocked, not dropped silently).
- Done when: `pytest tests/test_workers.py::test_handoff_depth_limit -v` passes.
- Commit: `test: add test verifying MAX_HANDOFF_DEPTH=10 is enforced gracefully`

**test-reconcile-crash-recovery**  · Priority: LOW
Source: 04-test-coverage.md — "LOW — No test for `reconcile()` on startup crash recovery"
- Files: `tests/test_e2e.py` or new `tests/test_reconcile.py`
- Changes: Add a test that creates a layout with a worker in `working` state, calls `reconcile()`, and asserts the worker is reset to `idle` and its task is set to `blocked`.
- Done when: `pytest tests/test_reconcile.py -v` passes; `reconcile()` is verified to reset stuck workers.
- Commit: `test: add crash recovery test for reconcile() resetting working-state workers`

---

### Phase 13 — MEDIUM: Accessibility (Level A failures)

**a11y-add-keyboard-task-assignment**  · Priority: HIGH
Source: 07-accessibility.md — "HIGH — Drag-and-drop has no keyboard alternative (WCAG 2.1.1)"
- Files: `static/components/KanbanTab.js`, `static/components/TaskCard.js`
- Changes: Add a keyboard-accessible action for task assignment: pressing Enter or Space on a selected task opens a modal/dropdown listing available workers; selecting a worker assigns the task. Add `role="button"` and `tabindex="0"` to task cards.
- Done when: A keyboard-only user can assign a task to a worker without using a mouse; the assign flow is accessible from the keyboard in all major browsers.
- Commit: `a11y: add keyboard alternative for task assignment (WCAG 2.1.1)`

**a11y-add-skip-nav-link**  · Priority: HIGH
Source: 07-accessibility.md — "HIGH — No skip navigation link (WCAG 2.4.1)"
- Files: `static/index.html`
- Changes: Add `<a href="#main-content" class="skip-link">Skip to main content</a>` as the first child of `<body>`. Add `id="main-content"` to the main app container. Add CSS to show the skip link only on focus.
- Done when: Pressing Tab as the first keyboard action on the page focuses a "Skip to main content" link; activating it moves focus to the main content region.
- Commit: `a11y: add skip navigation link (WCAG 2.4.1)`

**a11y-add-aria-roles**  · Priority: HIGH
Source: 07-accessibility.md — "HIGH — No ARIA roles/labels on interactive elements"
- Files: `static/components/LeftPane.js`, `static/components/WorkerCard.js`, `static/components/TaskDetailPanel.js`
- Changes: Add `role="button"` to clickable `<div>` elements. Add `aria-label` to icon-only buttons. Add `role="grid"` to the worker grid, `role="gridcell"` to individual worker slots.
- Done when: Running axe or similar on a live instance reports no "interactive element has no accessible name" violations for the main navigation and worker grid.
- Commit: `a11y: add ARIA roles and labels to worker grid and navigation elements`

---

### Phase 14 — LOW: License & Brand

**legal-add-trademark-disclaimer**  · Priority: MEDIUM
Source: 03-brand-ip-audit.md — "MEDIUM — Third-party AI provider trademarks used without disclaimer"
- Files: `README.md`
- Changes: Add a "Trademarks" section to `README.md`: "Bullpen is not affiliated with or endorsed by Anthropic, Google, or OpenAI. Claude, Gemini, and Codex are trademarks of their respective owners."
- Done when: `README.md` contains the trademark disclaimer section.
- Commit: `legal: add trademark disclaimer for Claude, Gemini, and Codex in README`

**legal-add-notices-file**  · Priority: LOW
Source: 03-brand-ip-audit.md — "LOW — No NOTICE/ATTRIBUTION file for dependencies"
Source: 12-license-audit.md — "LOW — No NOTICE/ATTRIBUTIONS file for dependency attribution"
- Files: new `NOTICES/` directory or `NOTICE.md` at repository root
- Changes: Create `NOTICE.md` listing all direct dependencies, their versions (from requirements.txt), their license identifiers, and the websocket-client NOTICE text (required by Apache 2.0 for binary distributions).
- Done when: `NOTICE.md` exists at repository root; it lists flask, flask-socketio, werkzeug, websocket-client, eventlet, and all frontend CDN deps with SPDX license IDs.
- Commit: `legal: add NOTICE.md with dependency attribution`

**legal-pin-cdn-versions**  · Priority: MEDIUM
Source: 12-license-audit.md — "MEDIUM — Vue.js and Lucide Icons loaded without version pinning from CDN"
- Files: `static/index.html`
- Changes: Pin Vue 3 to an exact version (e.g., `vue@3.4.21`) and Lucide Icons to an exact version. Regenerate SRI integrity hashes for each. Verify all CDN `<script>` tags have `integrity` and `crossorigin` attributes.
- Done when: All `<script>` tags in `static/index.html` reference exact version URLs; `integrity=` attribute is present on each; `vue@3` (unpinned) no longer appears.
- Commit: `sec: pin Vue.js and Lucide Icons to exact CDN versions with SRI hashes`

---

### Phase 15 — LOW: Operational Hardening

**ops-add-process-supervisor-docs**  · Priority: MEDIUM
Source: 10-operational-practice.md — "MEDIUM — No process supervisor or auto-restart"
- Files: `docs/deploy.md` (new or existing), or `README.md`
- Changes: Add a sample `systemd` unit file and launchd plist to `docs/` for users who want persistent deployment. Document in `README.md` that a process supervisor is recommended for non-local use.
- Done when: `docs/deploy.md` exists and contains both a systemd unit and launchd plist example for running Bullpen as a persistent service.
- Commit: `docs: add systemd and launchd examples for persistent Bullpen deployment`

**ops-add-upgrade-guide**  · Priority: LOW
Source: 10-operational-practice.md — "LOW — No documented upgrade procedure"
- Files: `README.md` or new `UPGRADING.md`
- Changes: Add an "Upgrading" section documenting: (1) pull latest, (2) re-run `pip install -r requirements.txt`, (3) any schema migration steps, (4) notes on `.bullpen/` forward compatibility.
- Done when: `UPGRADING.md` or the `README.md` upgrade section exists and covers the three upgrade steps.
- Commit: `docs: add upgrade guide for Bullpen version updates`

**ops-reconcile-worktrees**  · Priority: LOW
Source: 10-operational-practice.md — "LOW — `reconcile()` does not clean up orphaned worktrees"
- Files: `server/app.py` (reconcile function, ~line 557–600)
- Changes: Add a `reconcile_worktrees()` step in `reconcile()` that runs `git worktree list --porcelain`, identifies worktrees not associated with any active worker, and prunes them with `git worktree prune`.
- Done when: After a server crash that left an orphaned worktree, restarting Bullpen removes the orphaned worktree; `git worktree list` shows only active worktrees.
- Commit: `ops: add orphaned worktree cleanup to reconcile() on startup`

---

### Phase 16 — LOW: Accessibility & UX polish

**a11y-aria-live-streaming**  · Priority: MEDIUM
Source: 07-accessibility.md — "MEDIUM — No `aria-live` regions for streaming output"
- Files: `static/components/WorkerFocusView.js`, `static/components/LiveAgentChatTab.js`
- Changes: Wrap streaming output containers with `<div aria-live="polite" aria-atomic="false">`. Verify that each token/chunk append does not replace the entire container (which would cause excessive screen reader announcements).
- Done when: A screen reader announces new agent output lines as they appear in the worker focus view; the aria-live attribute is present in the rendered DOM.
- Commit: `a11y: add aria-live regions for streaming worker output and chat`

**a11y-modal-focus-management**  · Priority: MEDIUM
Source: 07-accessibility.md — "MEDIUM — Modal dialogs lack focus management and `aria-modal`"
- Files: `static/components/TaskCreateModal.js`, `static/components/WorkerConfigModal.js`, `static/components/ColumnManagerModal.js`
- Changes: On modal open: move focus to first focusable element inside the modal. Implement focus trap (Tab/Shift-Tab cycles within the modal). Add `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing to modal title. On modal close: return focus to the element that opened it.
- Done when: Opening any modal moves focus inside it; Tab does not escape the modal; closing the modal returns focus to the trigger element.
- Commit: `a11y: implement ARIA dialog pattern with focus trap for all modals`

**a11y-toast-alerts**  · Priority: LOW
Source: 07-accessibility.md — "LOW — Toast notifications not announced to screen readers"
- Files: `static/components/ToastContainer.js`
- Changes: Add `role="alert"` to the toast container element (or wrap in `aria-live="assertive"`).
- Done when: Adding `role="alert"` to the toast container and verifying a screen reader announces the toast text when it appears.
- Commit: `a11y: add role=alert to toast container for screen reader announcements`

**a11y-prefers-color-scheme**  · Priority: LOW
Source: 07-accessibility.md — "LOW — No `prefers-color-scheme` auto-detection"
- Files: `static/app.js`
- Changes: On first load (no saved theme preference), detect `window.matchMedia('(prefers-color-scheme: dark)')` and set the theme to "dark" or "light" accordingly.
- Done when: A new user with OS dark mode enabled sees the dark theme by default without manual selection; a user with light mode sees the light theme.
- Commit: `a11y: auto-detect prefers-color-scheme for default theme selection`

---

### Phase 17 — LOW: Data Privacy & Compliance

**data-limit-usage-history**  · Priority: MEDIUM
Source: 11-data-privacy-compliance.md — "MEDIUM — Usage history grows unbounded"
- Files: `server/usage.py`, `server/persistence.py`
- Changes: After appending a new usage entry, trim the `history` list to the last 100 entries (or a configurable `max_history_entries` config key). Write the trimmed list back.
- Done when: After 101 agent runs on a single task, its `history` frontmatter field contains exactly 100 entries (the oldest is dropped).
- Commit: `data: cap per-task usage history to 100 entries to prevent unbounded growth`

**data-add-privacy-doc**  · Priority: LOW
Source: 11-data-privacy-compliance.md — "LOW — No privacy policy or data processing documentation"
- Files: new `PRIVACY.md` at repository root
- Changes: Create `PRIVACY.md` documenting: what data Bullpen collects, where it stores it (`.bullpen/` flat files), what is transmitted to AI providers, how to delete data (task delete), and that no data is sent to a Bullpen cloud service.
- Done when: `PRIVACY.md` exists at repository root; it covers all four data inventory categories from the data-privacy review.
- Commit: `docs: add PRIVACY.md documenting data collection and processing`

**data-chat-session-ttl**  · Priority: LOW
Source: 11-data-privacy-compliance.md — "LOW — Chat session history not TTL-expired"
- Files: `server/events.py` (chat session state, `_chat_sessions` dict)
- Changes: Add a background cleanup that removes entries from `_chat_sessions` that have been idle for more than 1 hour (configurable). Store the last-activity timestamp alongside each session.
- Done when: A chat session that has had no activity for 1 hour is removed from `_chat_sessions`; the memory it occupied is freed. Verified via a test that advances a mock clock.
- Commit: `data: add TTL-based expiry for inactive live agent chat sessions`

---

## Additional Reviews Recommended for Next Cycle

1. **Performance profiling under load** — Instrument a 10-worker concurrent run and measure actual lock contention times, file I/O latency, and SocketIO event delivery latency. The scalability review's estimates are theoretical; a profiling run would confirm whether the bottlenecks are real at current usage levels.

2. **Dependency security scan** — Run `pip audit` or `safety check` against the installed dependency tree to identify known CVEs. No dependency audit was performed in this cycle.

3. **Eventlet interaction audit** — `eventlet` is in `requirements.txt` but `async_mode="threading"` is used. Determine whether eventlet is imported anywhere in the call path (it monkey-patches stdlib) and either remove it from dependencies or document why it is present.

4. **Frontend behavioral testing** — The 17 frontend test files test JavaScript structure, not behavior. A Playwright or Cypress integration test suite for the golden paths (create task, assign to worker, view output, complete) would close the behavioral coverage gap identified in the test coverage review.

5. **Windows compatibility audit** — The `os.chmod(0o600)` pattern used for credential files is a no-op on Windows. A Windows compatibility review would identify all POSIX-specific assumptions in the codebase.

---

## Session Restart Prompt

> Continue the analysis pack. Read `docs/analysis-pack.md` for task instructions. Then check `docs/reviews/` to find the most recent OUTPUT_DIR (highest version for today, or today's base folder). List its contents. Write any reviews from the 12-review list that are not yet present. When all 12 reviews exist, write or complete workplan.md. Do NOT create a new versioned folder — you are resuming an in-progress run, not starting a new one.
