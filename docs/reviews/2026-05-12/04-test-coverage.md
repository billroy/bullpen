# Test Coverage Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Senior QA engineer / test architect evaluating for acquisition

---

## Executive Summary

Bullpen has an unusually comprehensive test suite for a project of its size and stage: 933 tests across 87 files covering unit, integration, and frontend behavioral tests. Core business logic (task CRUD, worker state transitions, input validation, authentication, MCP auth) is well-covered. The primary gaps are: no code coverage measurement tooling configured, the E2E test suite is broken and untrusted, no performance/load tests exist, and the frontend tests rely on a headless simulation approach rather than browser automation. These are material gaps for a production-grade product but represent achievable remediation work.

---

## Findings

### HIGH — No code coverage measurement or enforcement

**Location:** `pytest.ini` (or `pyproject.toml`) — no coverage plugin configured; no `.coveragerc`; no coverage gate in CI

**Detail:** Despite 933 tests, there is no mechanism to measure or enforce code coverage. Without coverage data, it is impossible to know which lines, branches, and paths are actually exercised by the test suite. A high test count can mask low coverage if tests are concentrated on happy paths. Given the critical security and state-management code in `workers.py` (2,975 lines), `events.py` (1,763 lines), and `app.py` (1,419 lines), unmeasured coverage is a significant risk.

**Recommendation:** Add `pytest-cov` to `requirements.txt` and configure a minimum coverage gate (recommend ≥80% line coverage, ≥70% branch coverage). Add `--cov=server --cov-report=term-missing --cov-fail-under=80` to the default pytest invocation. Generate an HTML coverage report for detailed inspection.

---

### HIGH — E2E test suite broken (sandbox environment issue)

**Location:** `tests/test_e2e.py` — OSError on test collection or subprocess launch

**Detail:** The single E2E test file (`TestHappyPath`) fails with an OSError, likely a sandbox or subprocess privilege issue in the test environment. This means the end-to-end flow — create ticket → assign to worker → execute agent → verify output — is not verified by any automated test. The E2E test is the only test that exercises the full system integration (Flask + Socket.IO + subprocess agent execution), which is the most complex and highest-risk path in the application.

**Recommendation:** Diagnose and fix the OSError in `test_e2e.py`. If the issue is sandbox-specific (e.g., the test environment blocks subprocess spawning), use a mock agent adapter for the E2E flow rather than a real agent CLI, documenting that real-agent integration requires manual verification. The E2E test must be green before any release.

---

### MEDIUM — No performance or load tests

**Detail:** There are no tests that measure throughput, latency, or resource utilization under load. Key load scenarios that are unverified include:

1. Multiple simultaneous workers executing (subprocess resource pressure)
2. Rapid Socket.IO event bursts (e.g., 100 `task:create` calls/second)
3. Large workspace with 1,000+ tasks (file enumeration, frontmatter parsing time)
4. Streaming large agent output through Socket.IO (backpressure, memory)
5. Concurrent workspace access from multiple browser clients

**Recommendation:** Add a load test suite using `locust` or `pytest-benchmark`. At minimum, benchmark: task list load time at 500/1000/5000 tasks, Socket.IO event handling throughput, and worker startup latency. Set regression thresholds.

---

### MEDIUM — Frontend tests use Python-based simulation, not browser automation

**Location:** `tests/test_frontend_*.py`

**Detail:** Frontend tests are implemented as Python tests that simulate component behavior without a real browser. While this is valuable for testing component logic in isolation, it does not catch:

- CSS regressions (components hidden due to style changes)
- DOM interaction bugs (drag-drop, focus management)
- WebSocket reconnection behavior
- Cross-browser compatibility issues
- Rendering differences between Vue 3 CDN and expected behavior

There is no Playwright, Puppeteer, Selenium, or Cypress suite. The "frontend test" label may create false confidence about UI correctness.

**Recommendation:** Add a minimal Playwright test suite covering: login flow, task creation via UI, worker configuration modal, and Kanban drag-drop. These 4–5 tests would catch the most common regression classes in the UI. Mark the existing Python frontend tests as "component behavior" tests in their descriptions to clarify their scope.

---

### MEDIUM — No contract/integration tests for agent CLI interfaces

**Location:** `server/agents/claude_adapter.py`, `codex_adapter.py`, `gemini_adapter.py`

**Detail:** The agent adapters spawn real CLI subprocesses. The test suite uses mock adapters for most integration tests, which is correct for unit/integration isolation. However, there are no contract tests that verify the expected CLI interface (argument format, output stream format, exit codes) against the actual CLI binaries. When an upstream CLI changes its interface (e.g., Anthropic updates `claude` CLI argument syntax), the adapters break silently in production.

**Recommendation:** Add a CLI contract test file that, when the real CLI is available, verifies: `claude --version` succeeds, the expected argument flags exist, and the output format matches the adapter's parser expectations. This test can be skipped in CI environments without the CLI installed (using `pytest.mark.skipif`).

---

### LOW — No mutation testing

**Detail:** The test suite has many assertions but does not use mutation testing (e.g., `mutmut`) to verify that tests would actually fail if the code were subtly incorrect. Given the security-sensitive nature of validation logic (path traversal checks, input sanitization), mutation testing on `server/validation.py` and `server/persistence.py` would provide high confidence that the checks are both present and correctly exercised.

**Recommendation:** Run `mutmut run` on `server/validation.py` and `server/persistence.py`. Target ≥90% mutation kill rate for security-critical modules.

---

### LOW — No explicit test for secret redaction correctness

**Location:** `server/workers.py` (shell output redaction), `tests/`

**Detail:** The secrets redaction logic (filtering env-var values from shell worker output) is not explicitly tested with known patterns. A test that:
1. Sets known env vars (e.g., `MY_SECRET_TOKEN=abc123`)
2. Runs a shell worker that echoes those vars
3. Asserts the value is absent from the streamed output

…would provide direct verification of this security control.

**Recommendation:** Add `test_shell_worker_redacts_secrets.py` with the scenario above. Include edge cases: value appears in the middle of a line, value appears twice, two different secret vars in the same output.

---

## Coverage Assessment by Module

| Module | Test Files | Confidence |
|---|---|---|
| `server/validation.py` | `test_validation.py` | HIGH |
| `server/auth.py` | `test_auth_*.py` | HIGH |
| `server/persistence.py` | `test_persistence.py` | MEDIUM |
| `server/tasks.py` | `test_tasks_*.py` | MEDIUM |
| `server/workers.py` | `test_workers_*.py` | MEDIUM (state machine complex) |
| `server/events.py` | `test_events_*.py` | MEDIUM |
| `server/app.py` | `test_app.py` | MEDIUM |
| `server/mcp_auth.py` | `test_mcp_auth.py` | MEDIUM |
| `server/agents/*.py` | `test_agents.py` (mock-based) | LOW (no contract tests) |
| `static/` (JS) | `test_frontend_*.py` | LOW (no browser automation) |
| Full system integration | `test_e2e.py` | NONE (broken) |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 4 |
| LOW | 2 |
