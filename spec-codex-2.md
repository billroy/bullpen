# Spec Review Comments (codex-2)

## Scope of This Review
Focused on:
- Functional completeness
- Architecture and security risks
- Test framework and validation plan

## Assessment Snapshot
The updated spec is materially stronger than the prior revision. It now includes explicit sections for worker state machine behavior, persistence consistency, security validation, and a concrete test strategy. Most previously critical gaps are addressed.

Remaining comments are primarily about **internal consistency conflicts** and a few unresolved edge cases that can still cause implementation divergence.

## Findings (Ordered by Severity)

### 1) [High] Contradiction: worker failure end-state is both `BLOCKED` and `IDLE`
- **Spec refs:** `spec.md:331-333`, `spec.md:636`
- **Issue:** The state machine says a max-retry error transitions `WORKING -> BLOCKED` and that `BLOCKED` workers do not auto-advance. Retry Policy says final failure moves task to Blocked but worker returns to `IDLE` and evaluates queue.
- **Risk:** Different implementations will either halt the worker or continue queue processing, producing inconsistent behavior.
- **Comment:** Pick one canonical behavior and align all sections. Recommended MVP behavior: task moves to `blocked`, worker returns to `IDLE`, and queue progression follows activation mode.

### 2) [High] Contradiction: stop/timeout path conflicts with disposition rules
- **Spec refs:** `spec.md:336`, `spec.md:331`, `spec.md:424`, `spec.md:685`
- **Issue:** Queue progression says stop/timeout tasks are “disposed per disposition,” while state/error sections say timeout moves task to Blocked.
- **Risk:** Timeout or stop may incorrectly route to `review/done/worker:*` in some implementations.
- **Comment:** Separate outcomes explicitly:
  - success -> disposition
  - timeout -> blocked (no disposition)
  - stop -> define one policy (blocked vs assigned/cancelled) and apply consistently.

### 3) [High] Codex invocation remains implementation-blocking open issue
- **Spec refs:** `spec.md:410-418`, `spec.md:788`
- **Issue:** Normative example uses stdin (`--prompt -`), but open issues acknowledge this may not be supported.
- **Risk:** Core Codex worker path may fail at runtime on first implementation.
- **Comment:** Move this from “open issue” to normative requirement now: adapter must probe capability at startup and choose stdin or temp-file path mode deterministically.

### 4) [Medium] Startup reconciliation does not define deterministic queue order rebuild
- **Spec refs:** `spec.md:346-350`, `spec.md:620`, `spec.md:651-653`
- **Issue:** Queue arrays are derived from tickets, but startup rebuild only says “match assigned_to.” This does not preserve manual queue reorder semantics unless ordering key is explicitly mapped.
- **Risk:** Queue order drift after restart.
- **Comment:** Define rebuild order rule (e.g., sort assigned tasks by ticket `order`, then `created_at`, then slug).

### 5) [Medium] Activation mode enum mismatch (`on_assignment` vs `on_drop`)
- **Spec refs:** `spec.md:230`, `spec.md:247`
- **Issue:** Card body references `on assignment`, but config defines `on_drop`, `on_queue`, `manual`.
- **Risk:** UI/backend enum mismatch bugs.
- **Comment:** Normalize to one enum label everywhere (`on_drop`).

### 6) [Medium] Security control requires default gitignore file but initialization omits it
- **Spec refs:** `spec.md:581-587`, `spec.md:718`
- **Issue:** Log sensitivity requires `.bullpen/logs/` be gitignored by default, but first-time initialization does not create `.bullpen/.gitignore`.
- **Risk:** Sensitive logs are committed accidentally.
- **Comment:** Add explicit init step creating `.bullpen/.gitignore` with `logs/`.

### 7) [Medium] Missing reconciliation rules for invalid watch/disposition targets
- **Spec refs:** `spec.md:102`, `spec.md:248-249`, `spec.md:663-668`
- **Issue:** Columns are customizable and teams replace layouts, but behavior is undefined when `watch_column` no longer exists or `disposition=worker:{slot}` points to an absent worker.
- **Risk:** Workers stuck in WAITING, silent task drops, or misrouted handoffs.
- **Comment:** Add validation and fallback policy on config change/load (e.g., invalidate to `manual` + disposition `review` with warning).

### 8) [Medium] Agent process trust boundary is still implicit
- **Spec refs:** `spec.md:425`, `spec.md:744`
- **Issue:** Agents can modify workspace files with local user permissions; no sandbox or denylist controls are defined.
- **Risk:** Prompt-influenced destructive edits across the workspace.
- **Comment:** Add explicit trust model and guardrails (at minimum: optional read-only mode, allowed-path prefixes, and pre-run confirmation for auto-edit agents).

### 9) [Low] Test strategy omits persistence compatibility/versioning tests
- **Spec refs:** `spec.md:752-775`
- **Issue:** Excellent coverage for transitions/security, but no tests for loading older/newer `.bullpen` file shapes.
- **Risk:** Future spec evolution breaks existing workspaces.
- **Comment:** Add config/layout/profile schema-version tests with compatibility fixtures.

## Functional Completeness Recommendations
1. Resolve the worker-state contradictions (failure and stop/timeout paths) in one canonical lifecycle table.
2. Define deterministic queue rebuild ordering during startup reconciliation.
3. Add validation/fallback semantics for stale `watch_column` and `disposition` references.
4. Convert Codex stdin uncertainty into a required adapter capability-detection behavior.

## Architecture & Security Recommendations
1. Add init requirement for `.bullpen/.gitignore` creation.
2. Document explicit trust boundaries for agent-driven file edits and optional safety modes.
3. Keep schema validation strict and reject (not silently strip) unknown mutation keys where feasible.

## Test Framework Plan Comments
The added test framework is strong and release-oriented. Remaining gap:
1. Add persistence schema compatibility tests (forward/backward load) to prevent regressions in long-lived workspaces.

## Suggested Spec Edits (Concise)
- Update `Worker State Machine` + `Retry Policy` to remove contradictory end-state behavior.
- Update queue progression text to clearly distinguish success, timeout, and stop.
- Add startup queue rebuild sorting rule.
- Add `.bullpen/.gitignore` creation step in first-time initialization.
- Add watch/disposition target revalidation rules on config/team/grid changes.
- Move Codex stdin support from open issue to normative adapter behavior.
