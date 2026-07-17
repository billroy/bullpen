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
the private `_formula_trigger_outbox`, are retried on join/connect/startup, and
are never sent to browser or worker clients. A full outbox rejects the initiating
write before any user-visible state is committed.

`workspace_revision` orders every durable layout mutation. Browser clients ignore
duplicate or older snapshots. `formula_revision` remains a formula-generation
counter and is not advanced by unrelated layout edits.

Formula cells are read-only to increment operations. Callers must first replace
the formula with a literal value; failed increments do not change history.

Evaluation has explicit budgets for tokens, steps, analyzed references, generated
references, numeric size, exponents, shifts, wildcard inputs, and produced
strings. Budget exhaustion is a deterministic `#LIMIT!` result rather than an
unbounded allocation or loop.

Volatile formulas use the workspace IANA timezone. Their staleness is derived at
serialization time and activation is attempted on join, reconnect, focus,
visibility, and a visible-page interval.

Cross-workspace import and transfer remain file-backed operations, so they use
compensation rather than an unavailable cross-file transaction: a failed layout
write removes copied profiles, and a failed move-source write restores the
destination snapshot.

## Acceptance matrix

| Invariant | Verification |
| --- | --- |
| Sparse coordinates drive `ROW()` and `COLUMN()` | Formula unit test and Chromium two-window test |
| Formula generations are atomic and revisioned once | Event tests for persisted calculation metadata and revisions |
| Trigger failures are recoverable and deduplicated | Event test that fails delivery, retries the outbox, and observes one ticket |
| Formula increments cannot corrupt formula/history state | Socket event test and MCP end-to-end test |
| Adversarial formulas are bounded | Formula tests for huge literals, powers, strings, and shifts |
| Volatile formulas respect timezone and lifecycle activation | Formula timezone tests and frontend lifecycle assertions |
| Concurrent clients converge on the newest snapshot | Chromium two-window revision test |
| Failed imports/transfers leave no partial copied state | Bento and transfer compensation tests |
| Git commit listing does not perform per-commit ref subprocesses | Commit API tests plus the single `for-each-ref` implementation |

## Verification sequence

Run focused formula, event, transfer, Bento, frontend, and MCP tests first. Then
run the entire pytest suite with local browser/server access enabled. Treat any
failure in the acceptance matrix as release-blocking.
