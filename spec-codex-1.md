# Spec Review Comments (codex-1)

## Scope of This Review
Focused on:
- Functional completeness
- Architecture and security risks
- Test framework and validation plan

## Findings (Ordered by Severity)

### 1) [High] Worker lifecycle and queue progression are underspecified
- **Spec refs:** `spec.md:247-251`, `spec.md:111-116`, `spec.md:224-230`
- **Issue:** The spec defines how a task starts, but not deterministic behavior after completion/failure when `task_queue` has multiple items. It is unclear whether workers auto-advance to next queued task in all activation modes, or only for `on_queue`.
- **Risk:** Inconsistent implementations and race bugs (workers stuck in `IDLE` with queued work, or unexpectedly auto-running in `manual`).
- **Comment:** Add a state machine for worker execution (`IDLE -> WORKING -> IDLE/BLOCKED`) with explicit queue-dequeue rules per activation mode.

### 2) [High] Queue ownership model conflicts with kanban drag behavior
- **Spec refs:** `spec.md:105-107`, `spec.md:226-230`, `spec.md:249`, `spec.md:400`
- **Issue:** Tasks can be moved freely across kanban columns while also being queued on workers. No canonical source-of-truth is defined when these diverge (e.g., task moved to `done` while still in `task_queue`).
- **Risk:** Orphaned queue references, duplicate processing, and data corruption in `layout.json` vs ticket frontmatter.
- **Comment:** Define invariants and reconciliation rules (for example: ticket frontmatter is canonical, worker queues are derived and repaired on load).

### 3) [High] Missing concurrency control for file-backed state
- **Spec refs:** `spec.md:344-345`, `spec.md:510-513`, `spec.md:424`, `spec.md:430`
- **Issue:** Last-write-wins is acceptable for UX, but there is no write-serialization/versioning strategy for concurrent socket events writing the same markdown/JSON files.
- **Risk:** Lost updates, partial writes, malformed files under multi-tab edits or rapid event bursts.
- **Comment:** Require atomic writes + per-entity revision checks (or server-side single-writer queue) and reject stale updates with resync.

### 4) [High] CLI invocation examples are vulnerable unless shell execution is explicitly forbidden
- **Spec refs:** `spec.md:320-330`, `spec.md:334`
- **Issue:** Prompt content is user/task-controlled. If implementation follows string interpolation with shell execution, prompt/arg injection is possible.
- **Risk:** Command injection on local machine.
- **Comment:** Specify that agent calls must use subprocess argv arrays with `shell=False`, strict executable allowlist, and escaped logging.

### 5) [High] HTML/Markdown rendering model has XSS and local attack surface
- **Spec refs:** `spec.md:468-477`, `spec.md:474`, `spec.md:179-187`
- **Issue:** Spec supports rendered markdown and rendered HTML preview, plus agent output appended into markdown. Sanitization/sandbox rules are not defined.
- **Risk:** Script injection in UI from task content, agent output, or workspace files.
- **Comment:** Add mandatory sanitization policy (allowlist renderer), `iframe sandbox` for HTML preview, and explicit ban on executing inline scripts/events.

### 6) [High] Socket event trust boundary is undefined
- **Spec refs:** `spec.md:441-458`, `spec.md:548-549`
- **Issue:** No auth is in scope, but server-side validation requirements are not documented. Any local client can emit arbitrary payloads (`task:update`, `prompt:update`, `worker:configure`).
- **Risk:** Path traversal, malformed state injection, denial-of-service via oversized payloads.
- **Comment:** Define schema validation for every event, max payload sizes, allowed field whitelist, and workspace path boundary checks.

### 7) [Medium] Critical lifecycle edge cases are unspecified
- **Spec refs:** `spec.md:253`, `spec.md:455`, `spec.md:197`, `spec.md:447`
- **Issue:** Behavior is missing for:
  - removing a worker with active/queued tasks
  - resizing grid smaller than occupied slots
  - loading a team while workers are running
  - deleting a task currently assigned/running
- **Risk:** Undefined UX and inconsistent persistence outcomes.
- **Comment:** Add explicit preconditions and operator confirmations with deterministic migration behavior.

### 8) [Medium] Retry semantics are incomplete
- **Spec refs:** `spec.md:251`, `spec.md:521-522`
- **Issue:** Retries are defined numerically but not behaviorally (backoff strategy, same prompt vs augmented prompt, output/history handling per attempt).
- **Risk:** Non-repeatable behavior and noisy ticket logs.
- **Comment:** Specify retry policy (attempt counter, jitter/backoff, history entry format, final failure criteria).

### 9) [Medium] Task ordering is not implementable as written
- **Spec refs:** `spec.md:168`, `spec.md:67`, `spec.md:248`
- **Issue:** `order` is included, but insertion/reordering algorithm (fractional indexing / lexicographic generation) is unspecified while features depend on “oldest ticket” and queue ordering.
- **Risk:** Incompatible implementations and unstable ordering across clients.
- **Comment:** Define one ordering algorithm and tie-breakers (`created_at`, slug).

### 10) [Medium] Logging may leak sensitive content
- **Spec refs:** `spec.md:364-366`, `spec.md:334`, `spec.md:310-315`
- **Issue:** Logs and ticket outputs may include secrets from prompts, source files, or agent output.
- **Risk:** Sensitive data committed to git or exposed in UI.
- **Comment:** Add guidance: redact known secret patterns, keep `logs/` out of git by default, and provide output retention controls.

### 11) [Medium] Profile/model catalog is brittle against CLI drift
- **Spec refs:** `spec.md:246`, `spec.md:557`
- **Issue:** Static model lists in UI conflict with known CLI churn.
- **Risk:** Broken worker configuration when models are renamed/removed.
- **Comment:** Move model catalog to adapter capability discovery with graceful fallback and validation on save.

### 12) [Low] MVP claims conflict on file editing posture
- **Spec refs:** `spec.md:473`, `spec.md:551`
- **Issue:** Viewer says source files are read-only, while Codex `--auto-edit` can mutate workspace files.
- **Risk:** Operator expectation mismatch (changes happen outside viewer edit affordances).
- **Comment:** Clarify that direct source edits are agent-driven only in MVP and must be reviewed in external tools.

## Functional Completeness Recommendations
1. Add a formal worker/task state machine appendix.
2. Define canonical storage invariants between ticket files and `layout.json`.
3. Specify lifecycle behavior for destructive operations (delete/remove/resize/team-switch) during active work.
4. Define deterministic ordering algorithm and queue selection rules.
5. Add restart/recovery semantics: on server reboot, how running tasks are reconciled.

## Architecture & Security Recommendations
1. Add a strict event schema contract and validation layer.
2. Require safe process execution (`shell=False`, argv list, executable allowlist).
3. Add output and preview sanitization requirements for markdown/HTML.
4. Enforce filesystem boundaries (`realpath` checks, symlink handling) for Files tab and agent operations.
5. Introduce atomic file write strategy with revision checks.

## Test Framework Plan (Missing in Spec)

### Proposed Stack
- **Backend unit/integration:** `pytest` + `pytest-asyncio` (if async) + Flask-SocketIO test client.
- **Contract tests:** JSON-schema validation tests for each socket event payload.
- **E2E/UI:** Playwright driving browser with a fake agent adapter.
- **Fixtures:** Temp workspace factory creating `.bullpen/` trees and sample task/profile/layout files.

### Minimum Test Matrix
1. **State transitions:** all task status transitions, including retry/timeout/stop paths.
2. **Concurrency:** dual-client conflicting edits, rapid drag/drop, simultaneous worker completions.
3. **Persistence robustness:** atomic write, crash mid-write, restart recovery.
4. **Security:** XSS payloads in markdown/html, event payload fuzzing, path traversal and symlink escape attempts.
5. **Agent adapter:** stdout/stderr capture, timeout, non-zero exit, truncation behavior.
6. **Compatibility:** ingest of beans-compatible tickets missing bullpen extension fields.

### Release Gates
- No High-severity failures in security/transition/concurrency suites.
- Deterministic replay of event traces in CI.
- E2E happy path: create task -> assign -> run -> review -> done.

## Suggested Spec Additions (Concise)
- Add `## Worker State Machine` section.
- Add `## Event Validation and Security` section.
- Add `## Persistence Consistency Rules` section.
- Add `## Test Strategy and Acceptance Gates` section.
