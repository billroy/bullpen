# Locality of Reference for Named Targets

Status: Proposal for discussion. No runtime behavior changes are made by this document.

## Problem

Bullpen workspaces often contain several small clusters of workers and nearby
Value cells. A worker in one cluster may refer to `start`, while another
cluster has its own `start`. Today, a named Value reference chooses the first
matching Value cell in row-major coordinate order. A `worker:NAME` ticket
handoff chooses the first matching worker in the layout's slot array. Neither
rule considers where the referring worker is. The handoff winner can be
especially opaque because users cannot see slot order on the canvas.

The proposed rule is: **when a reference has a source cell, resolve a
duplicated name to the nearest matching target cell in the same workspace.**
This allows repeated names in separate clusters without requiring durable
worker IDs or explicit wiring between each worker and its data.

This is a lookup rule, not an ownership boundary. A nearer matching cell can
be added or moved later, changing which target a name denotes.

## Scope and terminology

- **Source** is the worker or Value cell containing the reference or initiating
  the handoff. Use its current grid coordinate when the reference is resolved.
- **Target** is a current worker or Value cell whose normalized name matches
  the reference, subject to the reference type's eligibility rules.
- **Local lookup** has a known source coordinate. **Unanchored lookup** has no
  meaningful source cell, such as a direct MCP `get_value(ref="start")` call.
- Lookup stays within the current workspace and current layout snapshot. It
  does not search other workspaces, imported packages, or historical cells.
- Names remain case-insensitive with leading and trailing whitespace trimmed;
  internal whitespace remains significant. Coordinate references remain exact
  and take precedence over names where that is the existing syntax.

## Proposed resolution algorithm

1. Parse an explicit coordinate, if the reference syntax permits one. Resolve
   it exactly; do not apply proximity to coordinate references.
2. Otherwise collect all currently eligible targets with the matching
   normalized name in the current layout.
3. If there is no target, retain the reference type's existing missing-target
   behavior. If there is one target, use it.
4. If there are multiple targets and a source coordinate exists, rank each by
   **Manhattan distance**:

   `abs(target.col - source.col) + abs(target.row - source.row)`

   Choose the minimum. For equal distances, choose the lowest target row,
   then the lowest column, then the lowest slot index. The last component only
   makes malformed or legacy layouts with duplicate coordinates deterministic.
5. If there is no source coordinate, retain the existing deterministic rule:
   row-major first for Value names, first slot for `worker:NAME`. Report that
   the lookup was unanchored when duplicates exist.

For example, a worker at `B2` referring to `start` chooses a matching Value
cell at `B3` (distance 1) over one at `A1` (distance 2), regardless of slot
order. A tie between `A2` and `C2` is resolved to `A2` under the proposed
row-major tie-breaker. This is **nearest on the grid**, not nearest in the
slot array or nearest along a handoff chain.

The same position-based rule should be used in live execution, previews, and
dependency analysis. A layout snapshot must produce the same answer at each
of those stages; an actual later run may see a newer layout.

## Reference-specific behavior

### Named Value reads from a worker

Use the referring worker's coordinate as the source for named Value placeholders
in its command, working directory, environment, notification text, and other
worker-owned templates. The same source applies to all placeholders in that
worker's configuration. A Service or Notification worker is a valid source
even though it is not a Value worker.

Formula names use the **formula cell's** coordinate as the source. Formula
parsing and dependency analysis must use the same target as evaluation. Keep
the existing direct-self-reference error: if the nearest `start` is the
formula cell itself, the formula reports a cycle instead of silently choosing
the next `start`. Explicit coordinate references, including formula ranges,
remain coordinate-based.

For direct UI and MCP Value reads and writes, the requested name is an
unanchored lookup unless the request has a trustworthy source worker context.
Do not guess a source from viewport position, current selection, or the most
recent worker run. A future API could accept an explicit source coordinate,
but it needs a separate contract for validation and caller identity. Until
then, preserve the current row-major winner and surface ambiguity.

### Ticket handoff with `worker:NAME`

Use the worker completing the ticket as the source. Find matching workers by
current name and rank by grid distance. Exclude the source worker from the
candidate set: `worker:NAME` means handoff to *another* worker. If no other
match exists, block the ticket with a target-not-found explanation. Preserve
the existing handoff-depth behavior and normal target assignment policy.

Eligibility needs a deliberate choice. The recommended rule is to filter out
workers that cannot accept tickets **before** distance ranking. This means a
nearby Value cell named `Review` does not prevent handoff to a farther runnable
worker named `Review`. If all matches are ineligible, block the ticket and
report that no matching worker can accept tickets. This differs from today's
first-slot behavior, which can select an ineligible match and block without
trying another.

`pass:DIRECTION` already identifies a neighboring coordinate and is unchanged.
`random:NAME` intentionally chooses at random among eligible matching workers
and should remain distinct from local name resolution unless separately
changed. Bare column dispositions and `watch_column` refer to board columns,
not worker cells, and are unchanged.

### Value-change subscriptions

`value_trigger_scope: "name"` currently subscribes to **every** Value cell
with the matching name. There is no single target to rank. The recommended
scope of this proposal leaves that behavior intact. A new `nearest name`
subscription mode could be designed later, but it would need to define when
the selected source changes after moves, renames, or deletions, and how to
avoid stale subscriptions.

## Movement, duplication, and observability

Names remain weak bindings. Re-evaluate them against the current layout when
used; do not persist a resolved slot index as the binding. Moving a source or
target, duplicating a target, or renaming either can change a future lookup.
This is desirable when a whole cluster is moved together, but moving only one
cell across clusters can rebind a reference.

Formula dependencies must be rebuilt when a structural move or rename changes
the nearest matching target, even if no Value was written. Recalculation must
invalidate formulas whose chosen dependency changes and propagate any changed
results. A preview and an execution using the same layout version should
agree. Ticket handoff should resolve at the moment of handoff, not when the
disposition was configured.

Keep ambiguity visible. Where warnings already exist, report the chosen
coordinate, the source coordinate (if present), and the other matching
coordinates in distance order. Handoff logs or ticket history should record
the chosen target's name and coordinate. A duplicate-name warning is
informational: the nearest match still resolves successfully. Exact
coordinate references remain the way to pin a particular cell location.

## Compatibility and implementation outline

This changes behavior for existing workspaces with duplicate names. Single
matches and explicit coordinates keep their current meaning. No persisted
layout migration is needed; the stored name reference stays the same. The
behavioral migration should be called out in release notes and reflected in
the worker configuration preview, so a user can see which duplicate will win.

Implement one shared name-ranking helper that accepts the layout, normalized
name, optional source coordinate, and an eligibility predicate. Keep parsing
and coordinate lookup in the existing Value helpers. Pass source coordinates
through template rendering, formula analysis and evaluation, and handoff
resolution. Do not use slot order as a proxy for geometric position. Keep
unanchored lookup behavior explicit in the API rather than hiding it in a
default coordinate.

Verification should cover duplicate names in separated clusters; movement of
the source and target; ties; sparse and negative coordinates; ineligible and
self handoff targets; formula dependency changes after relocation; template
preview versus execution; and unanchored MCP/UI lookup. Assert the selected
coordinate, not merely that some matching name was found.

## Options and decisions to settle

1. **Distance metric.** Manhattan distance is recommended: it counts grid
   steps, is simple to explain, and treats a directly adjacent cell as closest.
   Euclidean distance would favor diagonals in some layouts; Chebyshev
   distance would treat all eight surrounding cells as equally close. Which
   visual notion of neighborhood should Bullpen promise?
2. **Tie-breaking.** Row-major order is recommended because Value lookups
   already use it and it is visible on the canvas. Another option is a
   direction preference (for example, below before above) to favor common
   worker/data layouts. Ties should never fall back to hidden slot order when
   target coordinates differ.
3. **Handoff to self.** Excluding the source is recommended for named handoff.
   An alternative keeps self eligible at distance zero, preserving deliberate
   self-handoff loops but making a duplicated name on the source dominate all
   neighbors. An explicit self-target form could support that use case later.
4. **Ineligible names in handoff.** Filtering before ranking is recommended.
   An alternative chooses the nearest match regardless of type and blocks if
   it cannot accept tickets. That preserves the present failure mode but lets
   a nearby Value cell shadow a runnable worker.
5. **Unanchored operations.** Keeping existing resolution is recommended for
   compatibility. Alternatives are to reject ambiguous names or require an
   explicit source coordinate. Any API extension must keep coordinate refs as
   the clear way to identify a single target.
6. **Scope of value-change triggers and `random:NAME`.** Leave their existing
   all-matches and random-selection semantics intact, or extend locality to
   these features in a separate proposal. They currently express different
   intent from a single-target named reference.

## Current implementation references

- `server/values.py`: Value name normalization and row-major duplicate lookup.
- `server/formulas.py`: formula resolver, analysis, evaluation, and dependency
  generation.
- `server/templates.py`: worker-owned Value placeholder rendering.
- `server/workers.py`: named handoff and random pass routing.
- `server/events.py`: Value-change subscription matching and UI Value actions.
- `server/mcp_tools.py`: direct Value operations without a source cell.
