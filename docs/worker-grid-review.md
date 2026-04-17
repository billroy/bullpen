Review comments on `docs/worker-grid.md`, organized by what matters most — starting with
spec gaps that could trip up implementation, then smaller ambiguities, then missing topics.

## Spec gaps likely to cause implementation pain

**Geometry API uses an underspecified `cardSize`.** `visibleRange`, `pixelToCoord`, and
`coordToPixel` all take `cardSize`, but elsewhere the doc is explicit that width is fixed
(`columnWidth`) and height is layout-driven (~48 / ~140 / ~280 px). The signatures should
be `cardSize: { width, height }` (or two separate args). As written, an implementer could
easily assume square cells and break the Small layout.

**`viewportOrigin` is "fractional or integer" — pick one.** This is a surprisingly
load-bearing decision. If it's fractional, panning is smooth but `coordToIndex`-style math
needs floors everywhere and partial-edge cards are the default. If it's cell-snapped,
panning will judder on trackpads. Recommend committing to fractional (floats, in cell
units) and saying so explicitly.

**Overscan of "at least 1 cell" is too thin.** At 60 fps on a fast trackpad, one cell of
buffer will pop in visibly during pan. Typical virtualization libs use 2–5. Suggest:
`overscan: 2` default, configurable via constant.

**Coordinate uniqueness isn't stated.** The model says workers store `{ col, row }`, but
nothing says two workers can't occupy the same cell. Migration from a slot-indexed layout
is safe, but drag/drop, Paste, and Copy Worker all need a collision rule. Recommend: the
`Map<"col,row", worker>` mentioned for neighbor lookup should be the canonical index, and
writes that would collide are rejected at the service layer with a structured error.

**`occupiedBounds([])` and `nearestOccupiedInDirection` have undefined edge behavior.**
What does `occupiedBounds` return for the empty set — `null`, all zeros, or throw? What
does "nearest" mean in `nearestOccupiedInDirection` — strictly along the axis, or the
closest worker whose angle falls within a 90° cone from the origin? This matters for
arrow-key selection to feel predictable.

**Empty-cell hover with no DOM node.** The Virtualization section says empty cells are
only materialized on hover/focus, but the background is a pattern, not cells. Worth a
sentence explicitly stating that pointer events land on the canvas, the current cell is
resolved via `pixelToCoord`, and a single "hovered ghost cell" element is rendered in that
coordinate position — otherwise implementers may reach for per-cell DOM placeholders and
defeat the virtualization.

## Smaller ambiguities and inconsistencies

**Default working area of 4×5 at Large layout is 880 × 1400 px.** On a 1366×768 laptop or
a 1920×1080 desktop with browser chrome, the 5th row won't fit. Either the default should
be 4×3 at Large, or the default layout should be Medium. Right now the doc implies Large +
5 rows, which is inconsistent with what the user actually sees.

**Minimap bounds can explode at 1000×1000.** "Occupied bounds expanded by the current
viewport and a small margin" combined with a 1 px/cell clamp means, in the worst case, a
1000 × 1000 px minimap. Add a rule: if computed minimap size exceeds the frame, switch to
a fit-to-frame scale and let cell dots drop below 1 px (or aggregate).

**Large-delta drag/drop isn't scoped.** Directional drag handles only address adjacent
cells. If the user drags a whole card onto a distant cell, is that supported? Worth a
one-liner — either "deferred" or "allowed; coordinate is resolved by `pixelToCoord` at
drop."

**Clipboard lifetime is undefined.** Copy Worker produces a whitelisted config, but where
does it live? Per-tab `state.clipboard`? Persisted across reload? Shared across panes?
This matters for Paste Worker behavior and for the test plan.

**"Move" in bulk-ops list is new.** The multi-select section mentions Copy/Delete/Move as
bulk operations, but Delete and Move aren't defined anywhere else. If they're out of scope
for v1, drop them from the deferred-multi-select section; if they're implicit today, add
them to the single-card menu list.

**Row-major order for Tab isn't defined for sparse grids.** Presumably: lowest row first,
then lowest col within row. Worth one sentence, because negative coordinates make "first"
ambiguous.

## Missing topics worth considering

**Layout switch with existing workers.** If the user changes from Small to Large, cards
get taller. Does each worker's `{col, row}` stay the same (so cards grow down and may
overlap the next row's cards), or does row pitch change uniformly (so visual spacing
scales but logical rows don't)? The latter is almost certainly the intent but needs to be
stated — row pitch is a function of layout, not stored per worker.

**Empty-grid `Fit` and `Home`.** After deleting the last worker, `Fit` has nothing to fit
and `occupiedBounds` is undefined. Suggest: `Fit` falls back to `Home` when the occupied
set is empty.

**Hard cap on coordinate range.** "Unbounded" is fine as a model, but in practice
`{col: 2**53, row: 0}` will misbehave. A soft cap (e.g., ±100,000) with a validation error
on write costs little and prevents accidental blowups.

**Accessibility.** No mention of ARIA. A worker grid is a natural fit for `role="grid"`
with `aria-rowindex`/`aria-colindex` on rendered cells, and a live region for "selection
moved to worker at col N, row M." Worth at least a paragraph, even if full implementation
is deferred.

**Undo/redo.** Copy/Paste/Move/Delete are all destructive and worth undoing. If undo is
out of scope for v1, say so explicitly — otherwise implementers will build it in ad hoc.

**Persistence scope of `viewportOrigin`.** Per-pane is stated, but is it also persisted to
disk across reloads? For panes with workers hundreds of cells away from origin,
reload-to-origin would be jarring.

## Nits

The Selection section ("Escape closes an open menu, then clears selection") and the Menus
subsection ("Escape closes the menu and returns focus to the card or cell") drift
slightly. Unify to one sentence and reference it from both places.

The opening of "Drag Handles And Neighbor Detection" ("Directional drag handles must move
from 1-D index arithmetic to coordinate arithmetic") is already implied by the Target
Model; the section mostly exists to define the neighbor table and the Map key. Consider
merging with the drag section of Selection or with Geometry Module.

The implementation sequence has steps 7 ("Move worker status into the card header") and 8
("Replace rows x cols dropdown") sandwiched between structural changes. Both are UI-only
and could land in parallel with steps 1–5 behind a flag, which might shorten the critical
path.
