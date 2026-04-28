# Test Coverage Review
*Bullpen — 2026-04-27*

## Executive Summary

Bullpen has a test suite that is unusually large and diverse for a project of its size: 818 collected tests across 80 test files covering backend logic, event handlers, MCP framing, security hardening, and frontend component behavior. The breadth is impressive. The gaps, however, are structural rather than incidental — no coverage measurement, no CI/CD pipeline, no integration tests against real AI provider processes, and a testing strategy for frontend that avoids actual browser execution. A buyer inheriting this codebase will need to invest in coverage tooling and a CI pipeline before they can confidently refactor or extend the system.

## Test Suite Overview

- **Total tests collected**: 818 (confirmed via `pytest --collect-only`)
- **Test files**: 80 Python files under `tests/`
- **Largest test files**: `test_workers.py` (2,259 lines), `test_events.py` (1,379 lines), `test_mcp_tools.py` (614 lines), `test_agents.py` (581 lines), `test_service_worker.py` (480 lines)
- **Frontend test files**: ~45 files prefixed `test_frontend_*`, each testing a specific UI component or behavior by reading and asserting on the raw JavaScript/CSS source text
- **Run command**: `python3 -m pytest tests/ -x -q` (no parallel execution configured)
- **Dependencies for testing**: only `pytest==9.0.3` — no coverage, mocking framework, or browser driver packages in `requirements.txt`

Overall assessment: strong unit and functional test coverage of backend concerns, with a creative (if limited) approach to frontend testing. The suite gives meaningful regression protection for the most critical paths.

## Coverage Analysis

### Well-tested areas

**Worker state machine** (`test_workers.py`, `test_worker_lifecycle.py`): The most complex module in the codebase gets the most test attention. Tests cover task assignment, retry backoff, SIGTERM/SIGKILL cleanup, process lifecycle, watch-column refill, worktree setup, auto-commit/PR, and the deferred-start mechanism.

**SocketIO event handlers** (`test_events.py`): Uses the Flask-SocketIO test client to drive real event dispatch. Tests cover task CRUD events, worker configure/start/stop, move and group operations, and the write-lock behavior.

**Security and hardening** (`test_shell_worker_hardening.py`, `test_events_chat_hardening.py`, `test_cli_security.py`, `test_files_api_html_security.py`): Secret-masking in shell output, BULLPEN_MCP_TOKEN redaction, HTML injection in file preview, command/env redaction for viewer context, and output artifact truncation all have dedicated tests. This is a significant strength.

**Auth** (`test_auth.py`, `test_auth_e2e.py`): Multi-user credential loading, login throttling, session handling, and end-to-end login flows are covered.

**MCP framing** (`test_mcp_tools.py`): JSON-RPC 2.0 message framing with Content-Length, tool dispatch, and error response formatting are tested.

**Persistence layer** (`test_persistence.py`): Atomic writes, frontmatter round-trips, `ensure_within` path traversal prevention, and slug generation.

**Validation** (`test_validation.py`): Field constraints, enum enforcement, payload size limits.

**Frontend components** (`test_frontend_*.py`): Each file asserts that specific string literals, CSS selectors, or JavaScript patterns are present in the built static files. Examples: asserting `'return \`BUSY ${this.elapsed}\`'` exists in `WorkerCard.js`, or that `.worker-card-output {` exists in `style.css`. This catches regressions in UI logic at a string level without needing a browser.

### Missing or thin coverage

**No code coverage measurement**: No `.coveragerc`, no `pytest-cov` in requirements. There is no way to know which lines of the 11,148-line server codebase are actually exercised. Dark corners in `app.py` (1,371 lines), `service_worker.py` (1,312 lines), and `usage.py` (449 lines) may have low effective coverage.

**No integration tests with real AI providers**: The subprocess execution path is tested exclusively through `MockAdapter` and `echo`-based adapters. Actual Claude/Codex/Gemini CLI integration is never exercised in tests. Bugs in argument assembly, output parsing, or streaming in the real adapters would not be caught.

**Frontend tests do not execute JavaScript**: The `test_frontend_*` approach asserts on source text. It catches missing features and removed code, but does not test runtime behavior, Vue reactivity, component props, user interaction flows, or browser rendering. A JavaScript error in a method body not captured by string assertion would be invisible.

**No load or concurrency tests**: `workers.py` uses threading locks (`_process_lock`, `_deferred_start_lock`). There are no tests that stress concurrent worker starts, simultaneous task assignments, or race conditions between retries and stops.

**No visual regression tests**: Theme selection, layout rendering, and drag-drop behavior are tested via string assertions only.

**No negative path testing for file API**: The export/import API (`test_export_import_api.py`) tests the happy path; zip-bomb protection constants are defined but adversarial ZIP tests appear minimal.

## Test Quality Assessment

**Fixtures and isolation**: The `conftest.py` `_isolate_global_registry` fixture (autouse) patches the global workspace registry to a temp directory, preventing cross-test pollution of `~/.bullpen/projects.json`. This is well-designed. Individual tests use `tempfile.TemporaryDirectory` for workspace isolation.

**MockAdapter**: A clean, minimal `AgentAdapter` subclass in `conftest.py` that uses `echo` as its subprocess. Reused consistently across worker and event tests.

**Test client pattern**: `test_events.py` uses Flask-SocketIO's `socketio.test_client()` for true event dispatch without spinning up a network socket. Helper functions `get_event()`, `get_all_events()`, and `_wait_for_event()` reduce boilerplate.

**Internal API access**: Tests import and call private functions (`_load_layout`, `_assemble_prompt`, `_on_agent_success`, `_processes`) directly. This is pragmatic for a codebase without a clean public API boundary but makes tests brittle to internal refactors.

**Test naming**: Test names are descriptive and read as specifications (`test_worker_card_shows_elapsed_and_tokens_for_current_task`). The `test_frontend_*` file naming convention makes test scope immediately clear.

**Thread synchronization in tests**: `test_workers.py` includes `_wait_for_worker_threads()` — a polling loop that waits for daemon threads to finish writes. This is necessary given the threaded execution model but introduces timing sensitivity.

**No parametrization for edge cases**: Most tests are single-scenario. `pytest.mark.parametrize` is used sparingly, leaving many boundary conditions (e.g., max-length strings, empty arrays, concurrent operations) untested.

## CI/CD Integration

There is no CI/CD pipeline in this repository. Specifically:

- No `.github/workflows/` directory
- No `Makefile` with test targets
- No `tox.ini`, `noxfile.py`, or equivalent
- No Docker-based test environment defined for test isolation
- No pre-commit hooks configured

Tests are run manually via `python3 -m pytest tests/ -x -q`. There is no automated check that tests pass before merging code changes. This is a significant operational gap for any team taking over the codebase.

## Findings

### HIGH — No code coverage measurement

No `pytest-cov` is installed and no `.coveragerc` exists. The project has 11,148 lines of server Python across 22+ modules. Without coverage data, it is impossible to determine which lines are exercised, which branches are taken, or where the effective coverage percentage lies. High-value modules like `service_worker.py` (1,312 lines) and `usage.py` (449 lines) may have very low effective coverage despite passing tests.

**Impact**: Refactoring or extending untested code paths carries hidden risk. A buyer cannot make informed decisions about code confidence without this data.

### HIGH — No CI/CD pipeline

No automated test execution on commit or pull request. Any contributor can push breaking changes that pass local linting but fail tests. In an AI agent management tool where correctness of worker lifecycle and security hardening matters, this is a critical gap.

**Impact**: Regressions ship silently. Code confidence depends entirely on developer discipline.

### MEDIUM — Frontend tests do not execute JavaScript

The `test_frontend_*` suite asserts on raw source text rather than executing JavaScript in a browser or headless engine. Vue reactivity, computed properties, watchers, and user interaction flows are not exercised. A runtime JavaScript error in any component method would be undetected unless the failing string happens to be one of the asserted literals.

**Impact**: UI regressions in behavior (as opposed to presence of code) are invisible to the test suite.

### MEDIUM — No real AI provider integration tests

All agent execution tests use `MockAdapter` with `echo`. The Claude, Codex, and Gemini adapters are not tested against their actual CLI tools. Argument assembly bugs, output streaming edge cases, and error classification (`is_non_retryable_provider_error`) for real provider error messages cannot be validated without real or recorded subprocess output.

**Impact**: Provider-specific bugs may only surface in production.

### MEDIUM — Timing-sensitive tests in worker suite

`test_workers.py` includes polling loops (`_wait_for_worker_threads`) and `time.sleep()` calls to synchronize with daemon threads. On heavily loaded CI machines (common in cloud runners), these may produce flaky failures. There is no retry mechanism or explicit timeout reporting for flaky tests.

**Impact**: CI reliability will be lower than local reliability. False failures erode trust in the suite.

### LOW — No parametrized boundary testing

Validation constraints (`MAX_TITLE = 500`, `MAX_TAGS = 20`, `MAX_TAG_LEN = 50`) are defined but boundary values (exactly at limit, one over) are not systematically parametrized. The `test_validation.py` file tests the happy path and a few error cases but does not use `pytest.mark.parametrize` to sweep boundary conditions.

**Impact**: Off-by-one errors in validation could pass the test suite.

### LOW — No mutation testing

With no mutation testing configured (e.g., `mutmut` or `cosmic-ray`), it is unknown whether the test suite actually catches logic inversions or off-by-one changes in production code. This is a lower priority than coverage measurement but relevant for evaluating test quality confidence.

**Impact**: The test suite may be less effective at catching bugs than the raw test count implies.

### LOW — pytest-only runtime dependency

`requirements.txt` lists only `pytest==9.0.3` for testing, pinned to a specific version. This means `pytest-cov`, `pytest-asyncio`, `pytest-xdist` (for parallel runs), and `responses` (for HTTP mocking) are all absent. Adding them later requires dependency management work and potential version conflicts with the pinned packages.

**Impact**: Operational friction for expanding the test suite.

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 2     |
| MEDIUM   | 3     |
| LOW      | 3     |

## Recommendations

1. **Add pytest-cov immediately** and run with `--cov=server --cov-report=html` to establish a baseline. Target 70% line coverage as a first milestone, with 80% for `workers.py` and `events.py`.

2. **Add a GitHub Actions workflow** (or equivalent) that runs `pytest tests/ -x -q` on every push and pull request. A minimal `.github/workflows/test.yml` is a one-hour investment with high ongoing value.

3. **Add a headless browser test layer** using Playwright or Selenium for at least the critical user flows: creating a task, starting a worker, observing output. The existing `test_frontend_*` pattern is a useful complement but not a substitute.

4. **Record real provider output fixtures** for at least one AI adapter and write integration-level tests that parse them through the full output-handling pipeline without live network access.

5. **Replace timing-sensitive polling loops** in worker tests with event-driven synchronization (threading.Event) where possible to reduce flakiness in CI.

6. **Add parametrized boundary tests** for all validation constants in `test_validation.py`.
