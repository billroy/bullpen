# Security Review Response — claude-1

Date: 2026-04-08
Reviewer: Claude (reviewing codex-1 findings)
Scope: Validation of codex-1 security review findings; prioritized remediation plan

## Validation Summary

All 12 source-level claims in the codex-1 review were verified against current code. Every cited line number and code pattern is accurate. The review is thorough, well-structured, and the severity ratings are reasonable with a few adjustments noted below.

### Severity Assessment Adjustments

| # | codex-1 Rating | Adjusted | Rationale |
|---|---------------|----------|-----------|
| 1 | Critical | **Critical** | Agree. 0.0.0.0 + CORS * + no auth = full remote control. This is the single most important fix. |
| 2 | High | **Medium** | Cross-workspace broadcast is a confidentiality issue, but in single-user MVP there's only one user. Becomes High at multi-user. |
| 3 | High | **High** | Path traversal is exploitable now. Trivial fix (slug regex + ensure_within). |
| 4 | High | **High** | Same class as #3 — arbitrary path from client to register_project expands blast radius. |
| 5 | High | **Medium-High** | Inconsistent validation is real but lower exploitability in single-user context. The config:update handler blindly merging all keys is the worst part. |
| 6 | Medium | **Medium** | Symlink loops are a real availability risk. Low effort to fix. |
| 7 | Medium | **Low-Medium** | SRI matters but the threat is CDN compromise or network MITM, not direct attack. Worth fixing but not urgent for localhost use. |
| 8 | Medium | **Low** | Error message leakage is minimal risk when attacker already has full socket access (issue #1). Fix alongside #1. |
| 9 | Medium | **Medium** | Slot collision bug is real. Affects correctness even in single-user multi-workspace scenarios. |
| 10 | Medium | **Medium** | Permissive agent flags are by-design for the MVP use case (single developer trusting their own agents). Should become configurable before broader use. |

### Section B (Multi-User Blockers): Deferred

All 10 architectural blockers are valid observations. None are actionable for the single-user MVP phase. They are correctly categorized as phase-blocking for multi-user/multi-host deployment. No changes to their assessment.

### Section C (Positive Findings): Confirmed

The existing controls (ensure_within for tasks/files, atomic writes, argv execution, markdown HTML disabled, iframe sandbox) are genuine and well-implemented. The codebase has a solid security baseline — the gaps are at the perimeter, not in the core data handling.

---

## Prioritized Remediation Plan

### Tranche 1: Lock the Front Door (do first, ~1-2 hours)

These eliminate remote exploitation by default. All are small, low-risk changes.

| Fix | Issue | Change |
|-----|-------|--------|
| 1a | #1 Critical | `bullpen.py`: change `host="0.0.0.0"` to `host="127.0.0.1"`, add `--host` CLI flag for explicit override |
| 1b | #1 Critical | `server/app.py`: change `cors_allowed_origins="*"` to same-origin default (derive from host/port) |
| 1c | #3 High | `server/profiles.py`, `server/teams.py`: add slug regex validation (`^[a-zA-Z0-9_-]+$`) and `ensure_within()` check on derived paths |
| 1d | #4 High | `server/events.py` `project:add`: validate path is an existing directory, apply `os.path.realpath()`, reject paths outside a configurable root or require explicit allowlist |

**Why this order:** 1a+1b close the network perimeter. Without those, all other fixes can be bypassed by any LAN client or malicious webpage. 1c+1d close the two path traversal vectors that exist even for a local attacker.

### Tranche 2: Harden Inputs (next session, ~2-3 hours)

Systematic input validation and correctness fixes.

| Fix | Issue | Change |
|-----|-------|--------|
| 2a | #5 Medium-High | `server/events.py` `config:update`: whitelist allowed config keys instead of blind merge |
| 2b | #5 Medium-High | Add schema validation to `layout:update`, `worker:add`, `worker:move`, `team:save`, `team:load` events — extend existing `server/validation.py` patterns |
| 2c | #9 Medium | `server/workers.py`: change `_processes` key from `slot_index` to `(workspace_id, slot_index)` tuple |
| 2d | #6 Medium | `server/app.py` file tree walker: add `os.path.islink()` guard, max depth cap (e.g., 10), max node cap (e.g., 5000) |

### Tranche 3: Low-Hanging Fruit (batch with other work)

Low-effort improvements worth including when touching nearby code.

| Fix | Issue | Change |
|-----|-------|--------|
| 3a | #8 Low | `server/events.py`: replace `str(e)` in generic Exception handler with static message; log detail server-side |
| 3b | #2 Medium | `server/events.py`, `server/workers.py`: use Socket.IO rooms per workspace_id for emit scoping (prep for multi-user) |
| 3c | #7 Low-Medium | `static/index.html`: add SRI `integrity` + `crossorigin="anonymous"` attributes to all CDN script/link tags |

### Deferred (not actionable for MVP)

These are noted but not scheduled:

- **#10 Permissive agent flags** — by-design for single-developer MVP. Revisit when adding user-configurable worker profiles. The `--dangerously-skip-permissions` and `--approval-mode full-auto` flags are the intended operating mode for an unattended agent orchestrator. The remediation is to make these configurable per-worker rather than hardcoded, which aligns with the worker configuration feature already in the spec.
- **All Section B blockers** (auth, tenancy, CSRF, production server, distributed persistence, sandboxing, audit trail, rate limiting, supply chain pinning, git policy) — these are architectural requirements for multi-user/multi-host and should be designed holistically rather than patched incrementally.

---

## Notes

- The codex-1 review mentions 37 test failures. All test failures must be remediated as part of this work bundle — test health is a prerequisite for confidence in security fixes.
- The existing `ensure_within()` function in `server/persistence.py` is well-implemented and should be reused for the profile/team path fixes (Tranche 1c).
- The `server/validation.py` module already has good patterns for schema validation — Tranche 2b should extend these patterns rather than introducing new validation approaches.
