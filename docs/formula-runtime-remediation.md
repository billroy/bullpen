# Formula Runtime Remediation

## Decision record

Formula evaluation is server-owned. Every formula-producing path uses
`server.formula_runtime.calculate_generation`; clients submit source formulas
and render the resulting persisted generation.

A formula generation is one durable layout write containing:

- all recalculated values and formula metadata;
- one incremented `formula_revision`;
- one incremented `workspace_revision`;
- value-trigger intents and their cooldown timestamps.

Trigger tasks are an idempotent post-commit side effect. Durable intents live in
the private `_formula_trigger_outbox`, are retried by an autonomous bounded
exponential-backoff scheduler, and are recovered when the application starts.
Exhausted intents move to the private bounded `_formula_trigger_dead_letters`
collection and produce an operator-visible error toast. Neither private
collection is sent to browser or worker clients. A full outbox rejects the
initiating write before any user-visible state is committed.

`workspace_revision` orders every durable layout mutation. Browser clients ignore
duplicate or older snapshots. `formula_revision` remains a formula-generation
counter and is not advanced by unrelated layout edits.

Formula cells are read-only to increment operations. Callers must first replace
the formula with a literal value; failed increments do not change history.

Evaluation has explicit budgets for tokens, steps, analyzed references, generated
references, numeric size, exponents, shifts, wildcard inputs, and produced
strings. Expensive public helpers use the same bounded power, scaling, and join
primitives as operators. Budget exhaustion is a deterministic `#LIMIT!` result
rather than an unbounded allocation or loop, and generation-analysis exhaustion
cannot silently preserve a stale dependent value.

Volatile formulas use the workspace IANA timezone. Their staleness is derived at
serialization time and activation is attempted on join, reconnect, focus,
visibility, and a visible-page interval.

Cross-workspace import and transfer remain file-backed operations. They use a
shared write-ahead operation journal that records every affected layout and
profile before the first mutation. Prepared operations roll back on exceptions
or application restart; committed operations survive interrupted cleanup. Group
transfer has one enclosing journal, so a later member failure restores every
earlier member.

## Acceptance matrix

| Invariant | Verification |
| --- | --- |
| Sparse coordinates drive `ROW()` and `COLUMN()` | Formula unit test and Chromium two-window test |
| Formula generations are atomic and revisioned once | Event tests for persisted calculation metadata and revisions |
| Trigger failures are recoverable and deduplicated | Automatic idle retry, startup recovery, maximum-attempt, and dead-letter event tests |
| Formula increments cannot corrupt formula/history state | Socket event test and MCP end-to-end test |
| Adversarial formulas are bounded | Hard-timeout formula tests for huge literals, powers, helper-local finance/rounding, strings, and shifts |
| Volatile formulas respect timezone and lifecycle activation | Injected-clock event test and real Chromium two-window activation journey |
| Concurrent clients converge on the newest snapshot | Chromium two-window revision test |
| Failed imports/transfers leave no partial copied state | Group rollback tests plus subprocess-exit and startup journal-recovery tests |
| Git commit listing does not perform per-commit ref subprocesses | Commit API tests plus the single `for-each-ref` implementation |

## Verification sequence

Run focused formula, event, transfer, Bento, frontend, and MCP tests first. Then
run the entire pytest suite with local browser/server access enabled. Treat any
failure in the acceptance matrix as release-blocking.
