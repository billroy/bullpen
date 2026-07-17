# Formula Runtime Post-Remediation Review

**Review date:** 2026-07-17
**Range:** `e9a434b24ea671aadb93bc5b32c72acdb56f4206..36e6be581db79702c4c38aa5003e4137564b36d1`
**Range rationale:** `e9a434b` is the final commit before the July 16 implementation series and is therefore the resolved `<start-of-day-commit>`.
**Integrated diff:** 56 files, 9,155 insertions, 217 deletions
**Method:** The range was reviewed as one change set, including the final remediation commit. The initial review was read-only; the requested follow-on remediation and its verification are recorded at the end of this document.
**Remediation status:** All six findings below are closed by the uncommitted follow-on change set verified on 2026-07-17.

## Executive assessment

The reviewed commit range materially improved the design: formula calculation
became server-owned, revision handling was centralized, trigger intent was
persisted, single-operation transfer failures were compensated, and meaningful
browser and real-MCP tests were added.

The initial review found four high-priority failure modes:

1. A generation reference-budget limit can silently leave dependent formulas
   stale.
2. Public formula helpers can bypass the advertised resource budgets.
3. A transient trigger-delivery failure can remain pending forever without
   another user or connection event.
4. Group transfers and process interruption can still leave partial cross-file
   state.

It also found two medium-priority gaps in error isolation and end-to-end
lifecycle evidence. These findings describe the reviewed commit range at the
time of review; their closure is documented in **Post-remediation verification**
below.

## Prioritized findings (pre-remediation)

### [P1] Generation budget exhaustion can silently preserve a stale dependent

**References:** `server/formulas.py:2015-2035`,
`server/formulas.py:2037-2047`, `server/formulas.py:2084-2124`

When the generation-wide reference limit is reached, later formulas receive an
entry in `analysis_errors`, but their dependency edges are not added to
`reverse`. Partial recalculation computes its affected set exclusively by
walking `reverse` from the root. A formula skipped during analysis is therefore
not necessarily included in `affected`, so the stored `#LIMIT!` error is never
applied and its old value survives without any error.

A read-only probe reduced the generation budget to one reference and
recalculated a root with two direct dependents. The first dependent changed from
10 to 4; the second retained the deliberately stale value 999. The generation
reported `evaluated_count=1` and `error_count=0`.

This is a silent correctness failure. It also suppresses history, value-change
triggers, and downstream recomputation for the omitted formula.

**Required consolidation:** Make dependency discovery and affected-set
selection one coherent phase. If the generation budget is exhausted, either:

- reject the entire generation before mutating any cell; or
- conservatively include every unanalyzed formula, persist `#LIMIT!` for it,
  and propagate that error through all possible dependents.

Add a reduced-budget regression in which a dependency after the cutoff must
never retain an apparently successful stale value.

### [P1] Function helpers can allocate unbounded intermediates before limits run

**References:** `server/formulas.py:788-818`,
`server/formulas.py:1366-1381`, `server/formulas.py:1388-1396`,
`server/formulas.py:1762-1772`, `server/formulas.py:1792-1812`,
`tests/test_formulas.py:244-286`

The result validator runs only after a helper returns. Several helpers perform
the dangerous work first:

- `ROUND`, `ROUNDUP`, and `ROUNDDOWN` calculate `10 ** digits` without bounding
  `digits`.
- `RATE`, `PV`, `FV`, `PMT`, and `NPV` perform exponentiation without using the
  evaluator's exponent or integer-bit guards.
- `CONCAT` and `TEXTJOIN` build the complete joined string before checking the
  8,192-character output limit.

For example, `=ROUND(1,1000000000)` requests an enormous integer before result
validation, and `=FV(1,1000000000,1)` reaches helper-local exponentiation that
the guarded `^` and `POWER` paths never see. Range-backed string joins can
similarly build a large intermediate before being rejected.

The hard-timeout adversarial test covers numeric literals, direct `^`, `REPT`,
bit shifts, and `POWER`; it does not cover the helper implementations above.
Consequently the decision record's claim that budget exhaustion is always a
deterministic `#LIMIT!` is not established.

**Required consolidation:** Introduce a shared evaluation-budget object and
route all expensive helper operations through bounded primitives such as
`safe_pow`, `safe_scale`, and a length-accounting string builder. Preflight
projected work and output before allocation. Extend subprocess hard-timeout
coverage to every helper that allocates, loops, exponentiates, sorts, or joins.

### [P1] Persisted trigger intents have no autonomous retry path

**References:** `server/events.py:3245-3256`,
`server/events.py:3271-3339`, `server/events.py:3352-3355`,
`server/events.py:3398-3403`, `server/events.py:4268-4270`,
`server/app.py:476-494`, `tests/test_events.py:1715-1777`,
`docs/formula-runtime-remediation.md:16-19`

On delivery failure, the drainer increments `attempts`, stores `last_error`, and
returns. Another attempt occurs only after a later mutation, connection, or
project join. There is no timer, backoff scheduler, or startup workspace sweep.
If the failure is transient but the connected workspace stays otherwise idle,
the intent remains indefinitely and the value-triggered worker never receives
its task. Its cooldown timestamp has already been persisted.

The retry test calls the private drainer manually after restoring the mocked
dependency, so it proves idempotency under an explicitly requested retry, not
eventual delivery. The decision record also says intents are retried on
“startup,” but the implemented call sites are connection/join hooks rather than
an application-start scan.

**Required consolidation:** Treat the outbox as a durable retry state machine.
Persist `next_attempt_at`, use bounded exponential backoff, scan pending intents
at application startup, schedule the next attempt without requiring user
activity, and define a visible terminal/dead-letter state. Add an integration
test where one delivery fails once and succeeds automatically while the client
remains connected and performs no second mutation, plus a restart-recovery
test.

### [P1] Transfer/import compensation is exception-safe, not operation-atomic

**References:** `server/events.py:2340-2369`,
`server/transfer.py:229-241`, `server/transfer.py:261-327`,
`server/bento_workers.py:786-802`, `tests/test_transfer.py:449-485`,
`tests/test_bento_workers.py:415-444`

The new compensation handles selected in-process exceptions for one worker, but
two partial-state paths remain:

- A group transfer invokes and persists `transfer_worker` once per member. If a
  later member fails, earlier members remain copied or moved. The handler
  returns before broadcasting the already-mutated source and destination
  layouts, so connected clients can also remain stale.
- A process exit between destination write and source removal bypasses the move
  rollback and leaves a duplicate. A process exit after profile creation but
  before the associated layout write similarly leaves an orphan profile in
  transfer or Bento import.

The added tests monkeypatch write failures and allow the Python exception
handler to run. They do not exercise multi-member failure or interruption
between durable phases.

**Required consolidation:** Use one recoverable operation protocol for transfer
and Bento import. Persist an operation id and phase journal before the first
cross-file change, make every phase idempotent, and recover incomplete
operations during startup. Preflight a requested group and commit it as one
operation; if partial group results remain an intentional contract, broadcast
each committed member and expose durable per-member status. Verify with
subprocess crash injection at every phase boundary and with two connected
clients.

### [P2] Host-language exceptions escape the cell error contract

**References:** `server/formulas.py:734-753`,
`server/formulas.py:1415-1431`, `server/formulas.py:1792-1812`,
`server/formulas.py:2084-2124`, `server/events.py:715-743`,
`tests/test_formulas.py:120-180`

Recalculation converts only `FormulaError` into persisted cell error state.
Several validly parsed, invalid-domain formulas raise ordinary Python
exceptions instead. Read-only probes confirmed:

- `=SUBSTITUTE("a","","b",1)` raises `ValueError`.
- `=PMT(0,0,1)` raises `ZeroDivisionError`.
- `=NPV(-1,1)` raises `ZeroDivisionError`.
- `=FV(1,1000000,1)` raises `OverflowError`.

The Socket.IO wrapper catches these only at the whole-handler boundary, emits a
generic internal error, and abandons the generation. Thus one malformed formula
can reject an otherwise valid root write instead of isolating the failure to
that formula cell. The public-function test validates one successful example
per function but not the error-domain contract.

**Required consolidation:** Establish one evaluator boundary that converts
expected arithmetic and domain failures into stable `FormulaError` codes before
they reach generation orchestration. Keep programmer faults observable, but
ensure user-controlled values cannot produce raw `ValueError`,
`ZeroDivisionError`, or `OverflowError`. Add a table-driven invalid-domain suite
for every public function and assert that recalculation preserves prior values
while persisting a deterministic cell error.

### [P2] Volatile lifecycle acceptance is asserted from source text, not end to end

**References:** `server/events.py:3572-3599`,
`static/app.js:776-800`, `tests/test_formulas.py:183-241`,
`tests/test_frontend_value_formulas.py:29-35`,
`docs/formula-runtime-remediation.md:50-52`

The volatile unit tests cover clock and timezone calculations. The frontend
test only searches JavaScript source for event wiring and revision-guard
strings. No test drives a stale `NOW()` or `TODAY()` through focus, visibility,
reconnect, or two simultaneous windows and then verifies the server-side
coalescing, revision, history, trigger-suppression, and persistence behavior.
The server's `formula:activate` handler itself therefore has no lifecycle-level
acceptance evidence.

**Required consolidation:** Add an injected-clock integration fixture and a
real-browser journey with two windows. Advance past the freshness boundary,
activate both windows, and assert exactly one durable generation, convergence
on the new revision, no ordinary history append, and no value-trigger task.
Repeat across reconnect and the workspace timezone's midnight boundary.

## Consolidation plan

1. **Make formula evaluation one budgeted subsystem.** Combine parsing,
   dependency analysis, affected-set selection, helper execution, and error
   normalization around a shared budget and a single deterministic failure
   contract.
2. **Make trigger delivery an owned background subsystem.** Replace event-driven
   best-effort draining with a durable retry scheduler, startup recovery,
   backoff, terminal state, and observability.
3. **Make cross-file mutations recoverable operations.** Share a small journaled
   state machine between transfer and Bento import; define group atomicity once
   rather than layering compensation around individual files.
4. **Align acceptance documentation with executable journeys.** Replace
   source-presence assertions and manually invoked recovery with tests that
   cross the actual browser/MCP/server/persistence boundaries.

## Verification plan

The remediation should not be considered complete until the following gates
pass:

1. **Formula correctness and security**
   - Reduced generation-budget tests prove no dependent remains silently stale.
   - Every public function has invalid-domain/error-isolation coverage.
   - Helper-level adversarial cases complete under a hard subprocess timeout
     and return `#LIMIT!`, `#NUM!`, or `#VALUE!`.
2. **Trigger recovery**
   - A transient failure retries without another mutation, join, or reconnect.
   - Restart recovery drains persisted pending work exactly once.
   - Backoff, maximum-attempt, and terminal-state behavior are observable.
3. **Cross-file durability**
   - Crash injection after every journal phase converges to a documented final
     state on restart.
   - A multi-member transfer failure is either all-or-nothing or produces
     durable, broadcast, explicitly reported per-member results.
   - Profile/layout consistency is checked after transfer and Bento recovery.
4. **End-to-end lifecycle**
   - Two-browser volatile activation proves coalescing and revision convergence.
   - Real MCP formula mutation still converges with browser state.
   - Trigger, history, and revision side effects are asserted at the persisted
     layout and ticket layers.
5. **Regression suite**
   - Run focused formula, event, transfer, Bento, MCP, and browser suites first.
   - Run the complete suite with local sockets and Chromium available.

## Verification performed during this review

- `pytest -q` with local socket access: **1,568 passed**, with 17 existing
  `pty.forkpty()` deprecation warnings.
- Direct read-only probes confirmed the silent generation-budget omission and
  the raw helper exceptions described above.
- No production implementation files were changed.

## Post-remediation verification

The follow-on implementation closes every finding:

| Finding | Closure and evidence |
| --- | --- |
| Generation budget could preserve stale dependents | Partial recalculation now includes analysis failures conservatively in the affected traversal (`server/formulas.py:2108-2191`), verified by the reduced-budget stale-dependent regression (`tests/test_formulas.py:437`). |
| Helpers could allocate before validation | Power, rounding/scaling, joins, ranges, and finance functions now preflight bounded work (`server/formulas.py:756-817` and helper call sites), with helper-level subprocess timeout and invalid-domain coverage (`tests/test_formulas.py:259-306`). |
| Trigger intents lacked autonomous retry | Persisted backoff, startup scheduling, maximum attempts, dead-letter state, and workspace-removal-safe background retirement are implemented in `server/events.py:3338-3526`; persisted terminal failures are surfaced again on connect by `server/app.py:448-467`. Idle retry, restart recovery, dead-letter behavior, and reconnect observability are covered in `tests/test_events.py:1848-2012`. |
| Cross-file work was not operation-atomic | The shared prepared/committed operation journal and startup recovery are in `server/operation_journal.py:35-117` and `server/app.py:199`; transfer, Bento import, and group transfer use it at `server/transfer.py:296`, `server/bento_workers.py:804`, and `server/events.py:2400`. Subprocess-exit, nested recovery, application-start recovery, and group rollback are verified in `tests/test_operation_journal.py:19-129` and `tests/test_events.py:1411-1464`. |
| Host-language errors escaped cell isolation | Expected arithmetic/domain exceptions are normalized at the evaluator boundary (`server/formulas.py:1935`), with catalog-wide probes and recalculation isolation in `tests/test_formulas.py:306-313` and `tests/test_formulas.py:470-500`. |
| Volatile lifecycle lacked end-to-end evidence | Activation uses one injectable server clock and coalesced durable generation (`server/events.py:3774-3808`). Two-client event coverage is at `tests/test_events.py:2014-2064`; the real two-window Chromium journey is at `tests/test_value_worker_playwright.py:290-352`. |

Final verification:

- Focused formula, event, transfer, Bento, journal, and browser paths passed.
- The complete suite with local socket and Chromium access passed:
  **1,587 passed**.
- The only warnings were 17 pre-existing Python `pty.forkpty()` deprecation
  warnings from `tests/test_server_shutdown.py`.
- A first full run revealed a delayed retry thread outliving a removed temporary
  workspace. The scheduler now treats workspace removal as terminal, and the
  final full run completed without the thread-exception warning.

No unresolved finding from this review remains. Future consolidation should
keep formula budgets centralized, treat the trigger outbox and operation journal
as owned subsystems, and retain the subprocess/browser acceptance gates when
those paths change.
