# Test Coverage Review — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Senior QA engineer / test architect evaluating as a potential acquirer

---

## Scope

Review of test suite structure, coverage breadth and depth, test quality, CI integration, and gaps relative to the codebase's critical paths.

---

## Executive Summary

Bullpen has a strong test suite for a project of its size and maturity. 198 tests across 18 files provide good coverage of the core backend modules: authentication, input validation, task management, worker state machine, persistence, and Socket.IO events. The test infrastructure is clean (pytest fixtures, monkeypatching, mock adapters). Key gaps are: no coverage measurement tooling configured, no frontend tests, no CORS or rate-limiting tests, and the scheduler module is lightly tested. Overall, this is better than average for a solo/small-team developer tool.

---

## Test Suite Inventory

| File | Covered Module(s) | Estimated Tests |
|------|-------------------|-----------------|
| `test_auth.py` | `server/auth.py` | ~60 |
| `test_validation.py` | `server/validation.py` | ~70 |
| `test_tasks.py` | `server/tasks.py` | ~15-20 |
| `test_persistence.py` | `server/persistence.py` | ~15-20 |
| `test_workers.py` | `server/workers.py` | ~15-20 |
| `test_events.py` | `server/events.py` | ~15-20 |
| `test_mcp_tools.py` | `server/mcp_tools.py` | ~10-15 |
| `test_auth_e2e.py` | Full auth flow (HTTP) | ~10-15 |
| `test_profiles.py` | `server/profiles.py` | ~5-10 |
| `test_teams.py` | `server/teams.py` | ~5-10 |
| `test_scheduler.py` | `server/scheduler.py` | ~5-10 |
| `test_agents.py` | `server/agents/` | ~5-10 |
| `test_init.py` | Workspace init | ~5 |
| `test_e2e.py` | Full task→worker→output flow | ~10-15 |
| `test_events_chat_hardening.py` | Chat MCP safety | ~5-10 |
| `test_frontend_*.py` | Frontend component behavior | ~10-15 |

**Total: ~198 tests**

---

## Findings

### HIGH — No Coverage Measurement Configured

**Location:** `requirements.txt`, repository root — no `pytest-cov`, `.coveragerc`, `coverage.ini`, or `pyproject.toml` with coverage settings found.

Without coverage measurement:
1. There is no objective data on which code paths are tested.
2. Regressions in untested paths are not detectable.
3. A buyer cannot verify the coverage claims.

**Recommendation:** Add `pytest-cov` to `requirements.txt` (dev group), add a `.coveragerc` or `pyproject.toml` `[tool.coverage]` section, and add a `Makefile` or CI step that runs `pytest --cov=server --cov-report=term-missing`. Target ≥80% line coverage for `server/`.

---

### MEDIUM — Scheduler Module Lightly Tested

**Location:** `tests/test_scheduler.py` (~5-10 tests)

The scheduler runs in a background daemon thread and activates workers based on wall-clock time (`at_time`, `on_interval`). Time-based behavior is notoriously difficult to test correctly, and a shallow test file suggests:
1. Clock-dependent edge cases (midnight rollover, DST transitions, interval drift) are likely untested.
2. Thread safety under the write lock is likely untested.
3. The interaction between scheduler triggers and the worker state machine is not covered.

**Recommendation:** Expand scheduler tests using `monkeypatch` on `time.time()` or `datetime.datetime.now()` to simulate time progression. Add tests for: (a) `at_time` trigger fires exactly once, (b) `on_interval` respects elapsed time, (c) worker already running suppresses trigger, (d) lock contention does not deadlock.

---

### MEDIUM — No CORS or Network-Level Security Tests

**Location:** `tests/` — no test file for CORS behavior found.

The CORS policy diverges significantly based on the `host` parameter (`127.0.0.1` → scoped origin, `0.0.0.0` → wildcard). This branch is security-critical but untested. A regression that enables CORS wildcard unexpectedly would not be caught.

**Recommendation:** Add `tests/test_cors.py` with cases:
- Default host → CORS origin matches `http://127.0.0.1:<port>`
- `host=0.0.0.0` → CORS origin is `*`
- Cross-origin preflight is rejected when CORS is scoped

---

### MEDIUM — Worker Execution Tests Use Mock Adapter Only

**Location:** `tests/test_workers.py`, `tests/conftest.py`

All worker execution tests use a `MockAdapter` that simulates the agent subprocess. The actual subprocess invocation paths in `claude_adapter.py` and `codex_adapter.py` are tested only in `test_agents.py` (~5-10 tests). Notably:
- Output streaming (200ms batch emit) is not tested end-to-end
- Timeout watchdog behavior is not tested
- Auto-commit and auto-PR post-task actions are not tested
- Worktree setup/teardown is not tested

**Recommendation:** Add integration tests for worker execution using a real subprocess (a simple Python script as a mock agent) to cover streaming, timeout, and cleanup paths.

---

### LOW — Frontend Tests Are Behavioral, Not Coverage-Based

**Location:** `tests/test_frontend_*.py`

The frontend test files test component behaviors (modal escape, focus, model selection) but do so via Python tests, suggesting they are testing server-side behavior triggered by frontend actions rather than the Vue 3 component JavaScript itself. True frontend coverage (Vue component rendering, Socket.IO event handling in the browser) is not present.

**Recommendation:** For the current CDN-based Vue 3 setup (no build step), browser-level testing (Playwright, Cypress) is the practical path to frontend coverage. As a minimum, add Playwright smoke tests covering: login flow, task creation, worker assignment, and theme toggle.

---

### LOW — No Mutation Testing

No mutation testing tool (`mutmut`, `cosmic-ray`) is configured. Given the security-critical validation code in `server/validation.py`, mutation testing would verify that test assertions are strong enough to catch subtle validation bypasses.

**Recommendation:** Run `mutmut run` against `server/validation.py` and `server/auth.py` as a one-time audit.

---

### POSITIVE FINDINGS

- **Test infrastructure is clean:** `conftest.py` provides a well-designed `tmp_workspace` fixture, `MockAdapter`, and global registry isolation. Tests are independent and repeatable.
- **Validation coverage is strong:** `test_validation.py` (~70 tests) extensively covers all event type validators including boundary conditions and enum rejection.
- **Auth coverage is strong:** `test_auth.py` (~60 tests) + `test_auth_e2e.py` provides unit and integration coverage of the full auth stack.
- **End-to-end test exists:** `test_e2e.py` covers the full task→worker→output pipeline, which is the primary business-critical path.
- **Chat safety tests:** `test_events_chat_hardening.py` covers MCP startup safety, which is a non-obvious risk area.

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| TEST-01 | No coverage measurement configured | HIGH |
| TEST-02 | Scheduler module lightly tested | MEDIUM |
| TEST-03 | No CORS or network security tests | MEDIUM |
| TEST-04 | Worker execution tests use mock adapter only | MEDIUM |
| TEST-05 | No frontend browser-level tests | LOW |
| TEST-06 | No mutation testing | LOW |
