# Implementation Plan — Worktree Lifetime

**Created:** 2026-04-23
**Source:** [worktree-cleanup.md](/Users/bill/aistuff/bullpen/docs/worktree-cleanup.md)

---

## Objective

Implement the agreed worktree model with the smallest coherent change set:

- a worktree belongs to one worker run
- durable Git outputs are written to ticket frontmatter
- successful worktree-backed runs always delete their worktree
- failures in setup, Git actions, metadata persistence, or cleanup block the
  ticket
- reconcile cleans up stale worktree debris but does not infer higher-level Git
  lifecycle

This plan intentionally excludes:

- automatic branch deletion
- worktree reuse
- worktree retention UI
- PR/branch lifecycle modeling beyond `branch_name`, `commit_hash`, and `pr_url`

---

## Current Code Surfaces

### Worker lifecycle

- [`server/workers.py`](/Users/bill/aistuff/bullpen/server/workers.py)
  - `_run_ai_worker()`
  - `_setup_worktree()`
  - `_auto_commit()`
  - `_auto_pr()`
  - `_on_agent_success()`
  - `_on_agent_error()`
  - `stop_worker()`
  - `yank_from_worker()`
  - `_processes` runtime registry / `SubprocessRunner`

### Ticket persistence

- [`server/tasks.py`](/Users/bill/aistuff/bullpen/server/tasks.py)
  - `read_task()`
  - `update_task()`
  - archive helpers

### Startup reconcile

- [`server/app.py`](/Users/bill/aistuff/bullpen/server/app.py)
  - `reconcile()`

### Existing tests

- [`tests/test_workers.py`](/Users/bill/aistuff/bullpen/tests/test_workers.py)
- [`tests/test_events.py`](/Users/bill/aistuff/bullpen/tests/test_events.py)
- [`tests/test_tasks.py`](/Users/bill/aistuff/bullpen/tests/test_tasks.py)

---

## Implementation Shape

The first implementation should introduce a small worktree helper module rather
than spreading Git filesystem logic across `workers.py` and `app.py`.

Recommended new module:

- [`server/worktrees.py`](/Users/bill/aistuff/bullpen/server/worktrees.py)

Recommended responsibilities:

- derive branch name and worktree path from `task_id`
- create a fresh worktree for a run
- remove a worktree for a run
- optionally prune stale worktree directories / stale Git worktree registry
- keep all `git worktree` subprocess details in one place

This keeps `workers.py` focused on run state transitions rather than Git path
mechanics.

---

## Tranche 1 — Foundations And Helper Extraction

**Goal:** Create a single place for worktree operations and define the runtime
data needed by later tranches.

### T1.1 Add `server/worktrees.py`

Create helpers along these lines:

- `branch_name_for_task(task_id) -> str`
- `worktree_path(bp_dir, task_id) -> str`
- `setup_worktree(workspace, bp_dir, task_id) -> dict`
- `remove_worktree(workspace, bp_dir, task_id) -> None`
- `reconcile_worktrees(workspace, bp_dir) -> list[str]`

`setup_worktree()` should return enough data for later phases, for example:

```python
{
    "branch_name": "bullpen/<task_id>",
    "path": "<abs path>",
}
```

### T1.2 Move `_setup_worktree()` callers to the new helper

- Replace direct `git worktree add` logic in [`server/workers.py`](/Users/bill/aistuff/bullpen/server/workers.py)
- Keep behavior identical for now: create a fresh branch + worktree for the run

### T1.3 Define runtime ownership fields for active runs

Extend the `_processes` entry in [`server/workers.py`](/Users/bill/aistuff/bullpen/server/workers.py)
to optionally carry:

- `worktree_path`
- `branch_name`
- `uses_worktree`

This runtime bookkeeping is needed so cleanup can happen in:

- success path
- error path
- stop/yank path

### T1.4 Tests

Add tests for:

- branch name/path derivation
- worktree creation through the new helper
- worktree removal through the new helper
- stale path handling remains explicit and non-overwrite

Recommended test location:

- add a focused `TestWorktrees` section in
  [`tests/test_workers.py`](/Users/bill/aistuff/bullpen/tests/test_workers.py)
  or a new `tests/test_worktrees.py`

**Checkpoint:** targeted worktree tests green.

---

## Tranche 2 — Success Path Finalization

**Goal:** Make the happy path match the spec exactly.

### T2.1 Persist Git metadata to ticket frontmatter

On successful worktree-backed AI runs, write these fields to the ticket when
available:

- `branch_name`
- `commit_hash`
- `pr_url`

Use existing `task_mod.update_task()`; no schema migration is needed.

### T2.2 Enforce finalization order in `_on_agent_success()`

Restructure the worktree-backed success path in
[`server/workers.py`](/Users/bill/aistuff/bullpen/server/workers.py) so it
follows the agreed order:

1. append worker output
2. run configured Git actions
3. persist Git metadata
4. remove the worktree
5. apply final disposition

Important consequence:

- disposition must not happen before cleanup succeeds

### T2.3 Apply the same rule to non-PR worktree runs

If a run used a worktree and:

- created a commit only, or
- used a worktree without creating any commit/PR

then the worktree still gets removed on success.

### T2.4 Keep non-worktree behavior unchanged

Workers with `use_worktree: false` should keep their current lifecycle except
for any refactoring needed to share the finalization flow cleanly.

### T2.5 Tests

Add tests for:

- successful worktree-backed run writes `branch_name`
- successful auto-commit writes `commit_hash`
- successful auto-PR writes `pr_url`
- successful worktree-backed run removes the worktree before disposition lands
- successful non-PR worktree-backed run also removes the worktree

Recommended files:

- [`tests/test_workers.py`](/Users/bill/aistuff/bullpen/tests/test_workers.py)

**Checkpoint:** success-path tests green.

---

## Tranche 3 — Failure And Cancellation Cleanup

**Goal:** Ensure the worktree is treated as run-owned runtime state outside the
happy path too.

### T3.1 Cleanup on `_on_agent_error()`

For worktree-backed runs, `_on_agent_error()` should attempt worktree cleanup
before final blocking state is committed.

If cleanup itself fails:

- the ticket still ends in `blocked`
- the failure cause appended to the ticket should include the cleanup failure

This keeps the "any exception in this path blocks the ticket" rule intact.

### T3.2 Best-effort cleanup on explicit stop/yank

`stop_worker()` and `yank_from_worker()` should use the runtime worktree fields
from `_processes` to attempt immediate cleanup when a running worktree-backed
run is cancelled.

Recommendation for first pass:

- do best-effort cleanup on stop/yank
- do not invent a second success model for cancelled runs
- rely on reconcile as the backstop for any leftover debris

This keeps cancellation behavior compatible while still honoring the new
ephemeral worktree boundary.

### T3.3 Ensure runtime entries are detached cleanly

Audit the `finally` blocks in `_run_agent()` and `_run_shell()` so worktree
ownership data does not outlive the run entry itself.

### T3.4 Tests

Add tests for:

- worktree setup failure blocks cleanly
- cleanup failure during `_on_agent_success()` blocks and prevents disposition
- cleanup failure during `_on_agent_error()` still results in blocked ticket
- stop/yank on a running worktree-backed task attempts cleanup

Recommended files:

- [`tests/test_workers.py`](/Users/bill/aistuff/bullpen/tests/test_workers.py)

**Checkpoint:** failure/cancellation tests green.

---

## Tranche 4 — Startup Reconcile

**Goal:** Clean up stale runtime debris without creating a second worktree
lifespan model.

### T4.1 Add narrow reconcile helper

In [`server/worktrees.py`](/Users/bill/aistuff/bullpen/server/worktrees.py),
implement a narrow reconcile pass that:

- lists `.bullpen/worktrees`
- compares with `git worktree list`
- removes clearly stale directories when safe
- prunes stale Git worktree registry entries when appropriate
- returns notes/messages for logging or future surface area

### T4.2 Call reconcile from startup

Extend [`server/app.py`](/Users/bill/aistuff/bullpen/server/app.py)
`reconcile()` to invoke the worktree reconcile helper after ticket/queue
reconcile, using the workspace root derived from `bp_dir`.

Keep this limited:

- no branch deletion
- no PR inference
- no attempt to reconstruct ticket state from leftover worktrees

### T4.3 Archive behavior

No archive-specific Git changes are required in the first implementation.

Reason:

- successful runs should already have removed their worktrees
- cancelled/crashed leftovers are handled by reconcile
- automatic branch cleanup is out of scope

### T4.4 Tests

Add tests for:

- stale worktree directory removed by reconcile
- stale Git registry entry pruned or reported cleanly
- reconcile does not mutate unrelated ticket branch/PR metadata

Recommended files:

- new `tests/test_worktrees.py` or additions to
  [`tests/test_workers.py`](/Users/bill/aistuff/bullpen/tests/test_workers.py)
  plus a small startup integration test if needed

**Checkpoint:** reconcile tests green.

---

## Tranche 5 — Audit And Guard Rails

**Goal:** Close the loop around defaults and regression risks.

### T5.1 Audit merge-style workers and examples

Confirm that built-in profiles, examples, and docs do not imply that merge
workers should rely on prior coding worktrees.

Likely targets:

- [`profiles/code-merger.json`](/Users/bill/aistuff/bullpen/profiles/code-merger.json)
- any example worker configs in docs/tests

### T5.2 Regression test matrix

Before considering the work complete, run a focused matrix covering:

- worktree-backed AI success with no commit
- worktree-backed AI success with auto-commit
- worktree-backed AI success with auto-commit + auto-PR
- worktree-backed AI failure
- explicit stop/yank of running worktree-backed task
- startup reconcile of stale worktree debris
- merge worker path with `use_worktree: false`

---

## Risks And Recommendations

### Risk 1: Finalization becomes too interleaved inside `_on_agent_success()`

Recommendation:

- extract small helpers for:
  - Git action execution
  - metadata persistence
  - worktree cleanup

but do not over-generalize the first pass.

### Risk 2: Cleanup errors mask the original error

Recommendation:

- preserve the primary failure reason
- append cleanup failure context after it
- ensure blocked-ticket output remains readable

### Risk 3: Stop/yank semantics become surprising

Recommendation:

- keep stop/yank ticket behavior as close to current behavior as possible
- treat immediate cleanup as best-effort in those paths
- let reconcile be the safety net

### Risk 4: Scope expands into branch lifecycle

Recommendation:

- defer all automatic branch deletion work
- do not add `pr_state`/branch lifecycle modeling in the first pass

---

## Delivery Order

1. Tranche 1 — helper extraction and runtime ownership fields
2. Tranche 2 — success-path finalization and metadata persistence
3. Tranche 3 — failure/cancellation cleanup
4. Tranche 4 — startup reconcile
5. Tranche 5 — audit and regression pass

This order keeps the first meaningful behavioral win early:

- successful worktree-backed runs stop leaking worktrees

and then layers in:

- strict failure semantics
- cancellation cleanup
- startup cleanup for old debris

---

## Done Criteria

The implementation is done when all of the following are true:

- successful worktree-backed runs delete their worktree before disposition lands
- `branch_name`, `commit_hash`, and `pr_url` persist to ticket frontmatter when
  available
- failures in setup/Git actions/metadata persistence/cleanup block the ticket
- explicit stop/yank no longer rely on worktrees surviving as valid state
- startup reconcile removes or reports stale worktree debris
- no new UI is required for the first pass
