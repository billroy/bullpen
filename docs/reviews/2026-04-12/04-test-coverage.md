# Test Coverage Review — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Review of the test suite structure, coverage breadth, test quality, and gaps in coverage based on source code and test file inventory.

---

## Summary

Bullpen has a substantial test suite with 37 test files. Coverage is strongest in unit tests for server modules (auth, validation, persistence, tasks, workers, profiles) and weakest in integration/end-to-end flows and frontend component behavior. Several high-risk areas have dedicated test files; a few critical paths are not covered.

---

## Test File Inventory

| File | Subject | Type |
|------|---------|------|
| test_auth.py | Auth module (credential loading, CSRF, session) | Unit |
| test_auth_e2e.py | Full login/logout HTTP flow | Integration |
| test_cli_security.py | CLI arg injection prevention | Security unit |
| test_commits_api.py | Git commits API endpoints | Integration |
| test_e2e.py | Full app integration smoke tests | Integration |
| test_events.py | Socket.IO event handlers | Unit/Integration |
| test_events_chat_hardening.py | Chat streaming edge cases | Unit |
| test_agents.py | Agent adapter unit tests | Unit |
| test_mcp_tools.py | MCP stdio server | Unit |
| test_model_aliases.py | Model name normalization | Unit |
| test_persistence.py | File I/O, atomic writes, frontmatter | Unit |
| test_profiles.py | Profile CRUD | Unit |
| test_scheduler.py | Time-based scheduler | Unit |
| test_tasks.py | Task CRUD | Unit |
| test_teams.py | Team save/load | Unit |
| test_transfer.py | Worker transfer | Unit |
| test_usage.py | Token usage tracking | Unit |
| test_validation.py | Payload validation | Unit |
| test_workers.py | Worker state machine | Unit |
| test_init.py | Workspace initialization | Unit |
| test_socketio_cors.py | CORS origin allow/deny logic | Unit |
| test_frontend_*.py (17 files) | Frontend component structure/behavior | Structural (JS parse) |

---

## Findings

### HIGH — No test coverage for file API path traversal

**Files:** `server/app.py:349–404` (file_content, file_write endpoints)

The `/api/files/<path:filepath>` GET and PUT endpoints use `ensure_within()` to prevent path traversal. There are no tests in `test_e2e.py` or any other file that:
1. Attempt `../` traversal in the `filepath` parameter and verify a 403 response.
2. Attempt symlink traversal in the file tree.
3. Verify the 1MB write limit is enforced.

These are security-critical behaviors that should have regression tests.

---

### HIGH — No test for auth bypass via Socket.IO direct connection

**Files:** `server/app.py:444–468` (on_connect handler)

The `on_connect` handler accepts connections authenticated by either a session cookie OR the MCP token. There is no test that:
1. Verifies Socket.IO connections are rejected when auth is enabled and no credentials are provided.
2. Verifies that a valid MCP token but no session is accepted.
3. Verifies that an invalid MCP token is rejected.

`test_auth_e2e.py` covers HTTP login but not Socket.IO auth gating.

---

### MEDIUM — Agent adapter tests mock subprocess; no real agent invocation test

**Files:** `tests/test_agents.py`

Agent adapter tests use a `MockAdapter` (defined in `conftest.py`) that does not invoke real subprocesses. The `build_argv()` methods are tested for correct argument construction, but the MCP config temp file generation in `ClaudeAdapter._mcp_config()` and argument visibility risk for `GeminiAdapter` (prompt in argv) are not tested.

**Recommendation:** Add tests that call `build_argv()` on real adapter instances and assert: (1) no sensitive content in positional argv for Claude, (2) prompt NOT in argv for Gemini if the fix is applied, (3) temp MCP config file is valid JSON with correct schema.

---

### MEDIUM — Scheduler tests may not cover edge cases in time comparison

**Files:** `tests/test_scheduler.py`, `server/scheduler.py:72–85`

The scheduler uses simple string comparison (`HH:MM`) for trigger times without timezone handling. Tests should verify behavior around:
- Midnight crossing (23:59 → 00:00)
- DST transitions (local time shifts)
- System clock adjustments

If `test_scheduler.py` does not simulate these, the scheduler could silently miss or double-fire triggers.

---

### MEDIUM — Worker handoff depth limit not tested

**Files:** `server/workers.py` (`MAX_HANDOFF_DEPTH = 10`), `tests/test_workers.py`

Workers support chained handoffs where a completed task is routed to the next worker. The maximum depth is 10. A test should verify that at depth 10, handoff is refused gracefully (not silently dropped or causing a stack overflow/infinite loop).

---

### MEDIUM — Multi-workspace state isolation not end-to-end tested

**Files:** `server/workspace_manager.py`, `tests/test_e2e.py`

The WorkspaceManager supports multiple concurrent projects. Tests in `conftest.py` isolate the global registry, but there are no tests that create two workspaces, switch between them via Socket.IO, and verify that events/tasks in workspace A do not affect workspace B.

---

### LOW — Frontend tests are structural (AST/string parse), not behavioral

**Files:** `tests/test_frontend_*.py` (17 files)

The 17 frontend test files test Vue component structure by parsing JavaScript source code (checking for string patterns, function names, etc.). They do not:
- Run the application in a browser.
- Test actual DOM rendering or interaction.
- Use Playwright, Cypress, or headless browser automation.

This means regressions in click handlers, reactivity, and SocketIO event handling are not caught by the test suite.

---

### LOW — No test for `reconcile()` on startup crash recovery

**Files:** `server/app.py:557–600` (reconcile function)

`reconcile()` resets workers that were in "working" state when the server shut down (crash or kill). This is critical recovery logic. No test verifies that:
1. A layout with `state: "working"` workers is reset to "idle" after `reconcile()`.
2. Tasks assigned to those workers are set back to "blocked".

---

## Positive Observations

- `test_validation.py` provides thorough boundary and enum coverage.
- `test_persistence.py` tests atomic writes including failure cases.
- `test_socketio_cors.py` tests the CORS origin allow/deny logic directly.
- `conftest.py` properly isolates the global workspace registry per test.
- `test_auth.py` tests CSRF generation, validation, constant-time comparison behavior.
- `test_transfer.py` covers transfer error paths (busy worker, invalid workspace, etc.).

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| T1 | HIGH | No path traversal tests for file API |
| T2 | HIGH | No Socket.IO auth bypass / MCP token tests |
| T3 | MEDIUM | Agent adapter tests do not cover argv construction security |
| T4 | MEDIUM | Scheduler edge cases (midnight, DST) not tested |
| T5 | MEDIUM | Worker handoff depth limit not tested |
| T6 | MEDIUM | Multi-workspace isolation not end-to-end tested |
| T7 | LOW | Frontend tests are structural-only, not behavioral |
| T8 | LOW | `reconcile()` crash recovery not tested |
