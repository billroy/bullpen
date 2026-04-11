# Test Coverage Review — Bullpen
**Review date:** 2026-04-10  
**Reviewer role:** QA / Test Engineering Lead  
**Perspective:** Potential acquirer / independent assessment

---

## Executive Summary

Bullpen has a strong test suite for a project of its size and maturity: 342 tests across 15 test modules covering the majority of server-side logic. Coverage is thinner on the frontend (Vue components tested indirectly at best) and on the worker execution path's real subprocess behavior. No formal coverage measurement tooling is configured, which makes quantitative assessment impossible without additional instrumentation.

---

## Severity Table

| ID | Severity | Finding |
|----|----------|---------|
| T1 | MEDIUM | No coverage measurement configured (no `.coveragerc`, no `pytest-cov` in requirements) |
| T2 | MEDIUM | Frontend Vue components have no dedicated unit tests |
| T3 | LOW | Worker subprocess execution tested with mocks only — real agent integration untested |
| T4 | LOW | Scheduler time-based behavior tests may be environment-dependent (clock sensitivity) |
| T5 | INFO | No load or stress tests for concurrent worker execution |
| T6 | INFO | No tests for the `--set-password` CLI flow |

---

## Test Module Inventory

| Module | Approximate Tests | Coverage Area |
|--------|-------------------|---------------|
| `test_auth.py` | ~40 | Credential loading, hashing, secret key, CSRF, `auth_enabled()` |
| `test_auth_e2e.py` | ~20 | Login/logout flow, session persistence, redirect behavior |
| `test_events.py` | ~50 | Socket.IO event handlers (task CRUD, worker CRUD, config) |
| `test_workers.py` | ~50 | Worker state machine, queue logic, handoff, retry |
| `test_tasks.py` | ~40 | Task CRUD, fractional indexing, slug generation |
| `test_persistence.py` | ~40 | Frontmatter parsing, atomic writes, JSON read/write |
| `test_validation.py` | ~30 | All `validate_*` functions, edge cases |
| `test_e2e.py` | ~30 | Full request-to-storage round trips |
| `test_agents.py` | ~20 | Adapter `build_argv`, output parsing, MCP config generation |
| `test_mcp_tools.py` | ~15 | MCP tool execution (create/list/update ticket) |
| `test_scheduler.py` | ~15 | Timer-based activation scheduling |
| `test_profiles.py` | ~10 | Profile loading, default fields |
| `test_teams.py` | ~10 | Team save/load |
| `test_transfer.py` | ~10 | Cross-workspace worker transfer |
| `test_init.py` | ~10 | Startup reconciliation (crashed workers, interrupted tasks) |
| **Total** | **~342** | |

---

## Detailed Findings

### T1 — MEDIUM: No coverage measurement

**File:** `requirements.txt` — `pytest-cov` is absent

There is no `.coveragerc`, no `pytest-cov` invocation, and no CI pipeline that reports coverage metrics. This means:
- There is no way to assert a minimum coverage threshold.
- Dead code or untested branches are invisible without manual analysis.
- Coverage regressions cannot be caught automatically.

**Fix:** Add `pytest-cov` to `requirements.txt` and add a `pyproject.toml` or `.coveragerc` with a minimum threshold (e.g., 80%). CI (when added) should fail on regressions.

---

### T2 — MEDIUM: No frontend unit tests

The `static/components/` directory contains 16 Vue component files. None have corresponding test files. The exploration agent found no Playwright, Cypress, or Vitest configuration.

**Risk:** Frontend logic including drag-and-drop behavior, modal dismissal, optimistic updates, and real-time Socket.IO event handling is tested only incidentally through E2E tests in `test_e2e.py`, if at all.

**Fix:** At minimum, add Playwright smoke tests for the critical paths: login, ticket create, worker start/stop, and kanban drag-and-drop.

---

### T3 — LOW: Worker subprocess execution mocked

**File:** `tests/test_workers.py`

Worker tests use mock subprocesses (patched `subprocess.Popen` or similar). The actual behavior of the Claude CLI adapter parsing `stream-json` output, handling timeouts, or processing malformed JSON lines is not tested against a real agent binary.

**Risk:** Parser regressions in `claude_adapter.py:format_stream_line` or `parse_output` would not be caught by tests.

**Fix:** Add at least one integration test that spawns a minimal mock script on stdin/stdout to simulate `stream-json` output and verify the full parsing pipeline.

---

### T4 — LOW: Scheduler tests may be clock-sensitive

**File:** `tests/test_scheduler.py`

Time-based worker activation (`at_time`, `on_interval`) requires testing near clock boundaries. If tests rely on wall-clock time (e.g., `time.sleep()`), they will be slow and fragile in CI environments with variable timing.

**Recommendation:** Ensure scheduler tests use `freezegun` or inject a clock dependency so they run deterministically without wall-clock delays.

---

### T5 — INFO: No concurrency or load tests

Bullpen's threading model (one worker thread per running agent, serialized by write lock) has not been stress-tested. Tests do not exercise concurrent Socket.IO connections, simultaneous agent launches, or high-volume task creation.

---

### T6 — INFO: `--set-password` CLI path untested

`bullpen.py --set-password` prompts interactively for username and password. This path is not covered by the existing test suite. While the underlying `auth.py` functions are tested, the CLI interaction is not.

---

## Positive Observations

- Validation tests are thorough — all `validate_*` functions in `validation.py` have parametrized edge-case tests.
- Auth tests cover timing-safe comparison, session fixation prevention, and CSRF token behavior.
- Persistence tests cover the custom frontmatter parser including malformed input and edge cases.
- `test_transfer.py` covers the newer cross-workspace worker transfer feature — shows tests track feature additions.
- Tests use isolated temp directories (no shared state between tests).
- Socket.IO event handler tests use a real in-process Flask test client with Socket.IO, not just unit mocks.
