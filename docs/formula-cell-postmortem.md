# Formula Cell Implementation Postmortem

**Date:** 2026-07-16  
**Status:** Review  
**Scope:** Formula-cell specification, implementation, review, and validation

## Executive Summary

The formula-cell effort was framed too narrowly as a calculation-engine
feature. In practice, formulas introduced a new cell lifecycle spanning input
parsing, editing, navigation, structural grid operations, persistence,
calculation, collaboration, automation, MCP, and help. The original proposal
covered the evaluator and recalculation architecture in depth but did not map
the complete user and integration surface.

Implementation and tests followed that incomplete decomposition. Individual
components passed focused tests while ordinary end-to-end workflows remained
broken or unspecified. Basic failures were consequently discovered by manual
use after tranches had been reported complete: scalar formula entry, range
entry, formula re-editing, structural reference adjustment, navigation state,
MCP discovery, and MCP formula creation in an empty coordinate.

Skipping the usual adversarial specification review removed a valuable safety
net, but it was not the root cause and does not excuse the outcome. The
specification and implementation process should independently have exposed
the missing lifecycle coverage, contradictory contracts, and absence of
user-level acceptance tests.

The primary corrective action is to make substantial feature specifications
prove coverage through a surface inventory, lifecycle matrix, decision ledger,
traceability table, and executable acceptance journeys before implementation.
Adversarial review then challenges those artifacts rather than serving as the
only mechanism capable of discovering omissions.

## Impact

The practical impact was a prolonged sequence of corrective work after the
feature appeared substantially complete:

- The user became the primary exploratory tester for fundamental workflows.
- Multiple implementation tranches and tickets conveyed more confidence than
  their validation justified.
- Failures were addressed piecemeal, increasing review cost and making it
  difficult to know whether the remaining surface was complete.
- Attention was diverted from planned work to input parsing, edit round trips,
  structural semantics, UI state cleanup, MCP completeness, and recalculation
  lifecycle analysis.
- Confidence in both the proposal and its test suite was reduced.

No single defect caused this outcome. It resulted from a chain of scope,
review, implementation, and validation failures.

## What Happened

The proposal treated formula parsing, safe evaluation, dependency extraction,
server-authoritative recalculation, and collaboration as the feature's center.
Those were necessary concerns, but they were not a complete functional model.

The implementation was then divided into technically coherent tranches. Tests
were added around parsers, evaluators, server events, frontend source paths,
and MCP dispatch. Because the plan and tests shared the proposal's framing,
they mostly confirmed that the proposed components existed. They did not prove
that a formula survived a complete user operation across all layers.

Manual testing exposed the omitted boundaries in succession:

1. Entering `=2+2` did not display `4` through the actual browser workflow.
2. `=SUM(C36:C37)` was split at the colon by ordinary Value input parsing.
3. Re-editing a formula introduced an extra leading colon.
4. Moving or dragging a formula did not have complete, explicit relative-
   reference semantics.
5. Arrow-key navigation left stale editing and menu presentation state.
6. Formula and constant cells were not visually distinguishable.
7. Worker-trigger behavior after recalculation required renewed lifecycle
   analysis.
8. Point mode and in-cycle function help had been described but not delivered.
9. MCP formula support lacked adequate discovery and worker guidance.
10. `set_formula` could update an existing Value cell but could not create a
    formula in an empty coordinate, despite functional acceptance requiring
    formula creation through MCP.

Each defect was individually repairable. The damaging pattern was that the
defects occupied different product surfaces while sharing the same root cause:
there had been no complete formula-cell lifecycle model against which to judge
the specification or tranche completion.

## Root Causes

### 1. The Feature Boundary Was Misidentified

Formula support was treated as an evaluator added to Value cells. A better
model is that it introduced a new kind of editable, addressable, derived cell.
That model immediately raises questions about every operation that creates,
reads, edits, moves, copies, serializes, observes, or automates a Value cell.

The narrower model made interaction and integration work appear secondary even
though it was required for the feature to function at all.

### 2. Reused Subsystems Were Not Audited for Violated Assumptions

Existing Value-cell machinery was reused without a systematic review of its
assumptions. Formula source is not ordinary Value text:

- `:` is range syntax, not necessarily a label delimiter.
- A leading `=` changes the interpretation of the entire entry.
- Exact source preservation matters across edit and re-entry.
- Coordinates embedded in source may translate during structural operations.
- The displayed result and editable source are different representations.

The specification should have listed every reused parser, formatter, editor,
deparser, movement path, and API, followed by the question: **Which assumptions
does formula source violate here?**

### 3. Contradictory Contracts Were Not Elevated to Blocking Decisions

The earlier Value-cell specification explicitly prohibited MCP creation. The
formula specification required formulas to be created through MCP but did not
define whether `set_formula` was update-only or an upsert. The implementation
silently inherited the older restriction.

This was not merely a missing test. It was an unresolved product decision that
should have blocked implementation until reconciled. Similar ambiguity existed
around drag versus copy semantics and trigger behavior during structural or
bootstrap calculations.

### 4. Tests Mirrored the Code Instead of the User Journey

The test suite emphasized component boundaries:

- parser and evaluator unit tests;
- Socket.IO handler tests;
- frontend source and helper assertions;
- mocked MCP client dispatch;
- focused formula-generation tests.

Those tests were useful but insufficient. A mocked MCP test could prove that
`set_formula` received the expected arguments while completely missing that
the server rejected an empty target. Parser tests could pass while the browser
sent the source through a different, colon-aware input path.

The missing tests were direct journeys:

- Enter `=2+2` in an empty cell and observe `4`.
- Enter `=SUM(C36:C37)` and observe the correct result.
- Reopen the formula and see its exact source.
- Press Enter without changes and verify source, value, and history remain
  correct.
- Copy, paste, drag, move, and duplicate the formula according to explicit
  reference-adjustment rules.
- Press each navigation key and verify selection, focus, and menus.
- Perform the same empty-cell creation through MCP.
- Repeat a calculation with two browser windows and verify one authoritative
  commit and no feedback loop.

### 5. Tranche Exit Criteria Were Too Local

A tranche was considered complete when its intended components existed and
focused tests passed. That is a development checkpoint, not functional
acceptance.

A formula-entry tranche is not complete unless a formula can be entered through
the real UI, calculated, displayed, reopened, and re-entered. An MCP tranche is
not complete unless the tool performs representative operations against the
real server contract. A range tranche is not complete if range text cannot pass
through every supported editing path.

Commit and ticket checkpoints made the work auditable, but they also created
false confidence when their status language did not distinguish component
completion from journey completion.

### 6. The First Fundamental Failure Did Not Trigger Re-Baselining

When `=2+2` failed through the browser, the appropriate response was not only
to repair that path. It was evidence that the specification-to-test model had
failed at the most basic boundary. Work should have paused for an audit of all
input, editing, structural, collaboration, and API paths.

Continuing with local remediation allowed the same class of omission to be
found repeatedly. The user was left to discover which untested surface would
fail next.

## Contributing Factors

- The formula engine involved enough genuine technical complexity to draw
  attention away from mundane but essential interaction paths.
- The phased plan encouraged horizontal subsystem progress before a complete
  thin vertical slice had been demonstrated.
- Existing tests made it easy to add assertions at familiar seams instead of
  constructing higher-cost user journeys.
- Specification prose used words such as “created” and “through UI and MCP”
  without mapping them to exact API semantics.
- Review concentrated on correctness within the proposed architecture rather
  than challenging whether the architecture covered the whole feature.
- The normal adversarial specification review was skipped, removing an
  additional chance to catch these problems before implementation.

## What Went Well

- Server-authoritative calculation and single-generation collaboration rules
  prevented the initially proposed multi-window recalculation feedback loop.
- Tranche commits and live tickets made individual corrections traceable.
- Once reproduced, the defects were generally isolated and covered with focused
  regression tests.
- Manual user testing exercised realistic workflows and exposed gaps that the
  implementation-shaped suite did not.
- The later reviews simplified over-engineered proposals, particularly around
  worker-trigger coalescing, before those proposals became additional code.

These positives reduced the cost of correction, but they did not compensate
for the missing pre-implementation product model.

## How This Should Have Worked

### Start With a Thin Vertical Slice

Before building the full function library or advanced recalculation behavior,
the first tranche should have proved one complete formula lifecycle:

1. Enter `=2+2` in an empty cell.
2. Create the Value cell and preserve the exact source.
3. Calculate on the server.
4. Persist one committed generation.
5. Broadcast it to two browser windows without client recalculation.
6. Render `4`.
7. Reopen the cell and display exactly `=2+2`.
8. Re-enter it unchanged.
9. Create the same formula at an empty coordinate through MCP.
10. Reload the workspace and verify the same source and result.

Only after this journey passed should ranges, the full function suite,
structural adjustment, volatility, and trigger integration have been layered
onto it.

### Specify the Lifecycle, Not Only the Components

The proposal needed a matrix similar to the following before implementation:

| Operation | Empty coordinate | Existing constant | Existing formula | Collaboration | MCP |
|---|---|---|---|---|---|
| Enter/set formula | Create | Replace | Edit | One server generation | Coordinate upsert |
| Re-enter unchanged | N/A | N/A | No semantic change | No duplicate work | No semantic change |
| Set constant | Create | Replace | Clear formula | One generation | Explicit literal write |
| Copy/paste | Create translated source | Replace per UI contract | Translate | One batch generation | Defined or unavailable |
| Drag/move | Move per explicit policy | Move | Translate per explicit policy | One batch generation | N/A |
| Recalculate | N/A | Error or no-op | Evaluate | Server only | Explicit tool |
| Reload/import | Reconstruct | Preserve | Validate and recalculate | One committed state | Read after commit |

For every row, the specification should define source preservation, result
calculation, history, triggers, errors, and event delivery.

## Required Process Changes

### 1. Surface Inventory Gate

Every substantial feature proposal must enumerate affected surfaces before it
can be approved:

- direct UI entry and configuration;
- keyboard and mouse interaction;
- display and accessibility;
- persistence, reload, import, export, and templates;
- copy, paste, duplicate, drag, move, swap, and delete;
- server events and collaboration;
- history and audit behavior;
- triggers and downstream automation;
- MCP and other programmatic interfaces;
- error, stale, blank, and recovery states;
- documentation and in-product help.

An intentionally unsupported surface must be stated explicitly rather than
left absent.

### 2. Lifecycle and Representation Gate

The proposal must identify all representations of the feature and transitions
between them. For formulas these include editable source, parsed expression,
dependency metadata, calculated value, formatted display, last successful
value, error state, and serialized state.

Each transition must have an authority, transaction boundary, and failure
contract.

### 3. Decision Ledger Gate

Ambiguous or conflicting semantics must be collected in a prioritized decision
ledger. P0 decisions block implementation. The ledger must include conflicts
with earlier specifications and current behavior, not only choices introduced
by the new proposal.

No implementation agent should silently resolve a normative contradiction by
following whichever existing code path is convenient.

### 4. Acceptance Journey Gate

Before implementation, define a small suite of concrete journeys that cross
the actual product layers. At least one journey must cover each supported entry
surface. Mocks may support diagnosis but cannot be the sole acceptance proof
for an external interface.

The first journeys should use the smallest and most obvious inputs. Complexity
tests do not substitute for `=2+2`.

### 5. Specification-to-Test Traceability

Every normative requirement must map to one or more tests. The traceability
record should distinguish:

- unit or component evidence;
- server integration evidence;
- browser or API journey evidence;
- manual validation, when automation is not yet practical.

A requirement covered only by a mock or source-string assertion should be
visibly marked as lacking end-to-end evidence.

### 6. Stronger Tranche Exit Language

Checkpoint reports and tickets must distinguish:

- **Implemented:** code exists;
- **Component-verified:** focused units and integrations pass;
- **Journey-verified:** representative user/API workflows pass;
- **Accepted:** all tranche acceptance criteria and required reviews are
  complete.

“Complete” should not be used for a tranche that lacks its journey tests.

### 7. Re-Baseline Stop Condition

Pause implementation and reopen the affected lifecycle when any of the
following occurs:

- the simplest supported user input fails after a tranche is declared done;
- two defects arise from different surfaces but share an unmodeled transition;
- implementation encounters a contradiction between approved specifications;
- a public interface is covered only by mocks;
- manual testing repeatedly discovers P0 behavior absent from acceptance
  criteria.

At that point, adding another regression test is necessary but not sufficient.
The surface inventory, lifecycle matrix, and remaining plan must be audited.

## Adversarial Review Protocol

Adversarial review remains recommended for substantial specifications, but it
should inspect explicit artifacts and use differentiated perspectives:

1. **Product semantics:** What would a user familiar with the product category
   naturally expect?
2. **Interaction:** Keyboard, mouse, focus, editing, accessibility, and help.
3. **State and collaboration:** Authority, concurrency, broadcasts, retries,
   feedback loops, and stale state.
4. **Structural operations:** Copy, paste, drag, move, duplicate, import,
   reload, and delete.
5. **Integration:** MCP, workers, history, triggers, interpolation, and other
   consumers.
6. **Test adequacy:** Which claims are mocked, asserted below the user boundary,
   or not exercised through a complete journey?
7. **Simplification:** What machinery can be removed while preserving the
   required behavior?

A useful standing review prompt is:

> Assume this feature is incomplete despite passing its current tests. Starting
> from a blank workspace, devise the first 25 actions an impatient user, an
> automation client, and a second browser window would try. Identify every
> unspecified transition, inherited parser, contradictory contract, and mocked
> boundary.

The review should produce blocking findings and missing acceptance journeys,
not merely commentary on the proposal's internal consistency.

## Action Items

### P0 — Before the Next Comparable Feature

- Require a surface inventory and lifecycle matrix in the proposal template.
- Require a prioritized decision ledger with all P0 items resolved.
- Define the thin vertical acceptance slice before defining horizontal
  implementation tranches.
- Require at least one real UI journey and one real programmatic-interface
  journey when both surfaces are supported.
- Add tranche status vocabulary that separates implementation, component
  verification, journey verification, and acceptance.
- Establish the re-baseline stop condition and invoke it after a fundamental
  acceptance failure.

### P1 — Process and Test Infrastructure

- Add a reusable traceability-table section to substantial specifications.
- Create helpers for browser formula entry, reopen/re-enter, structural
  movement, multi-window observation, and MCP-authenticated operations.
- Maintain a compact “obvious first inputs” conformance corpus for every input
  language: smallest scalar, range, punctuation-bearing string, blank, error,
  and round trip.
- Make adversarial review a standard approval checkpoint for cross-cutting
  features, with explicit sign-off if intentionally skipped.

### P2 — Ongoing Improvement

- Review completed feature tickets for claims supported only by focused or
  mocked tests.
- Periodically run exploratory workflows from a blank workspace rather than
  only regression fixtures.
- Record escaped-defect patterns and feed them back into the proposal and test
  templates.

## Closing Perspective

The lesson is not simply that this specification needed another reviewer.
Adversarial review likely would have caught several gaps, but the process was
too dependent on reviewer intuition. The proposal needed artifacts that made
under-scoping visible: a complete surface inventory, explicit lifecycle
transitions, resolved contradictions, and executable user journeys.

The implementation also needed to treat an elementary workflow failure as
evidence against the plan, not merely against one code path. Had work paused
and re-baselined after the first `=2+2` failure, much of the subsequent
pick-and-shovel remediation could have been found in one deliberate audit
rather than through repeated user surprise.
