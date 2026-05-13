# Technical Due Diligence Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Technical due diligence lead evaluating for strategic acquisition

---

## Executive Summary

Bullpen is a well-constructed, commercially deployable AI agent orchestration platform. It solves a real coordination problem (managing multiple AI coding agents across tasks) with a lightweight stack that minimizes operational overhead. The technical foundation is sound: Python/Flask backend, Vue 3 frontend, flat-file storage, Socket.IO for real-time sync. The product demonstrates production deployability with Docker, nginx, systemd, and Fly.io support. Key technical risks for an acquirer center on: the god-module architecture in workers.py (high-value code concentrated in one file), absence of formal CI/CD, an untested real-agent execution path in automated testing, and vendor dependency on three external AI CLIs (Anthropic, OpenAI, Google).

---

## Technology Assessment

### Stack Maturity and Appropriateness

| Component | Technology | Assessment |
|---|---|---|
| Web framework | Flask 3.1.3 | Mature, stable, widely supported. Correct choice for this I/O-bound workload. |
| Real-time | Flask-SocketIO 5.6.1 + eventlet | Stable. eventlet green-threading is an older concurrency model; asyncio migration would be a future consideration. |
| Frontend | Vue 3.5.33 (CDN, no build) | Progressive framework, correct version. No-build approach limits tooling but reduces operational complexity. |
| Storage | Flat files (frontmatter markdown) | Correct for single-user/small-team use. Becomes a bottleneck at scale (see 09-scalability.md). |
| Auth | Werkzeug PBKDF2 + sessions | Industry-standard implementation. |
| Testing | pytest 9.0.3 | Well-configured, 933 tests. |
| Deployment | Docker + nginx + systemd | Industry standard. Appropriate for the target market. |

### Vendor Dependencies and Risk

The most significant technical dependency risk is the integration with three AI CLI tools that are maintained by external companies:

1. **Claude Code CLI (Anthropic):** Core agent; most feature-rich integration. Bullpen's Claude adapter handles OAuth token refresh and MCP protocol integration. Risk: Anthropic CLI interface changes (has happened historically) break the adapter without warning.
2. **Codex CLI (OpenAI):** Second agent type. Risk: OpenAI deprecated the Codex API in 2023; the CLI appears to be a separate product. Interface stability needs verification.
3. **Gemini CLI (Google):** Third agent type. Least mature integration. Risk: Google has a history of product discontinuation.

Each adapter implements defensive parsing and retry logic, which reduces but does not eliminate interface change risk. The project has no automated contract tests against the real CLIs (see `04-test-coverage.md`).

---

## Findings

### HIGH — No formal CI/CD pipeline; all testing is manual/local

**Location:** Repository root — no `.github/workflows/`, no CI config of any kind

**Detail:** There is no automated CI pipeline. Tests are run manually with `pytest`. This means:

1. **No regression gate on merge:** A contributor can merge a change that breaks 50 tests without any automated notification.
2. **No reproducible test environment:** Test results are developer-machine-specific. A test that passes locally may fail in a different Python version, OS, or dependency version.
3. **No automated release process:** There is no build, tag, or publish workflow. Releases are presumably manual.
4. **Investor/acquirer concern:** The absence of CI is the most commonly cited technical debt item in acquisition due diligence. It signals that the team has not invested in engineering infrastructure.

**Recommendation:** Add a GitHub Actions workflow (`.github/workflows/ci.yml`) that:
- Runs `pytest` on Python 3.12 on every PR and push to main
- Reports coverage with `pytest-cov`
- Fails the check if coverage drops below threshold
- Runs `ruff check .` for lint

This is a 30–60 minute implementation with high signal value for due diligence.

---

### HIGH — Core execution logic is not covered by automated integration tests with real agents

**Detail:** The most commercially valuable capability — AI agents autonomously executing on tasks — is not verified by any automated test that uses real agent CLIs. The E2E test that would cover this is broken. All agent-execution tests use mock adapters. An acquirer cannot rely solely on the mock-based test suite to verify that the product's core value proposition works correctly with its primary dependency (Claude Code CLI).

**Recommendation:** Establish a manual smoke-test checklist that is executed before each release, covering: create task → assign to Claude worker → verify task execution → verify Socket.IO output streaming. Document this checklist in `docs/release-checklist.md`. In parallel, repair the E2E test suite.

---

### MEDIUM — eventlet concurrency model is a legacy choice

**Location:** `requirements.txt` (eventlet 0.41.0), `server/app.py` (eventlet monkey-patching)

**Detail:** Flask-SocketIO with eventlet uses green threads (cooperative multitasking via monkey-patching standard library I/O). While this works correctly, the Python ecosystem has moved toward asyncio as the standard asynchronous concurrency model. eventlet's monkey-patching can cause subtle incompatibilities with libraries that assume standard threading semantics, particularly newer async-first libraries. Flask-SocketIO also supports asyncio (via `async_mode='asgi'` with `uvicorn`), which is the preferred modern approach.

**Recommendation:** This is not an immediate blocker. Note it as future technical debt. A migration from eventlet to asyncio/uvicorn would improve compatibility with the modern Python async ecosystem but is a non-trivial change requiring regression testing.

---

### MEDIUM — Flat-file storage creates operational complexity at scale

**Detail:** (Cross-references `09-scalability.md`) The `.bullpen/tasks/` directory stores each task as a separate file. At small scale (10–500 tasks), this is fast and operationally simple. At larger scale, issues emerge:

1. `os.listdir()` performance degrades on large directories
2. Concurrent writes require file-level locking (already implemented) but do not scale to distributed deployments
3. No atomic multi-task transactions (e.g., "move all tasks from column A to column B" is multiple separate file writes)
4. Backup and migration require file system operations, not database dumps

**Recommendation:** The current flat-file approach is correct and sufficient for the target use case (single-team, single-host). Document the scalability boundaries clearly (e.g., "tested and performant up to 1,000 tasks per workspace"). If a multi-host or large-team product line is planned, scope a SQLite migration (SQLite is file-based, requires no server, and provides ACID transactions).

---

### MEDIUM — No versioned API or backward compatibility guarantee for Socket.IO events

**Location:** `server/events.py`

**Detail:** The Socket.IO event names and payload schemas constitute the product's internal API. There is no versioning (e.g., no `v1:task:create`), no API changelog, and no forward/backward compatibility mechanism. If a future version changes the payload schema for `task:create`, any client running the old frontend code against the new server will silently fail or behave incorrectly. This is particularly relevant for scenarios where multiple browser tabs are open during a server restart.

**Recommendation:** Document the current event schema as `SOCKET_EVENTS.md`. For future changes, implement a `version` field in the server-hello event so the client can detect version mismatches and prompt the user to refresh. A full versioned API is not required yet, but schema documentation is.

---

### LOW — Python version pinning is informal

**Location:** `requirements.txt`, `Dockerfile`

**Detail:** The Dockerfile specifies Python 3.12, but `requirements.txt` does not pin Python version, and there is no `.python-version` file (pyenv) or `pyproject.toml` specifying the required Python version range. Developers running Python 3.10 or 3.11 may encounter subtle differences (e.g., `is_relative_to()` was added in 3.9; some f-string syntax was added in 3.12).

**Recommendation:** Add a `.python-version` file specifying `3.12` (for pyenv users) and a `python_requires = ">=3.12"` in a `pyproject.toml`. This prevents accidental use on older Python versions.

---

### LOW — No dependency pinning strategy (requirements.txt uses floating versions for some deps)

**Location:** `requirements.txt`

**Detail:** If `requirements.txt` uses unpinned or loosely-pinned versions (e.g., `Flask>=3.0` rather than `Flask==3.1.3`), a new installation on a different machine may pull different versions, leading to environment drift. The exploration found specific versions mentioned (Flask 3.1.3, eventlet 0.41.0) which suggests some pinning, but a `requirements.lock` file or `pip-compile`-generated lockfile would guarantee reproducible environments.

**Recommendation:** Generate a `requirements.lock` file using `pip-compile` (from `pip-tools`) and commit it to the repository. Use the lockfile in the Dockerfile (`pip install -r requirements.lock`). Keep `requirements.txt` as the human-readable source of intent and `requirements.lock` as the reproducible installation manifest.

---

## Technology Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AI CLI interface change breaks adapters | HIGH | HIGH | Contract tests, version pins, adapter abstraction |
| eventlet incompatibility with future lib | MEDIUM | MEDIUM | asyncio migration roadmap |
| Flat-file storage bottleneck at scale | LOW (for target use) | HIGH (for scale) | Document boundaries; SQLite path planned |
| No CI → regression escapes to main | MEDIUM | MEDIUM | Add GitHub Actions CI |
| E2E test broken | CERTAIN | MEDIUM | Fix or rewrite with mock agent |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 4 |
| LOW | 2 |
