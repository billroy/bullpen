This document lays out the evolution of the worker grid from a fixed viewport-fitted grid into a
sparse, spreadsheet-like worker canvas.

The implementation should support at least a 20 x 20 test grid, a 100 x 100 comfortable working
scale, and a 1000 x 1000 minimum design scale without rendering the full grid to the DOM.

---

## Current Status

The worker grid is a fixed grid whose dimensions are chosen from a dropdown in the header (2-7 rows
x 2-10 cols). Layout computation fits that many worker cards into the viewport; card size is
whatever fills the space. Changing dimensions rearranges workers.

Internally, workers occupy slots in a 1-D array (`slots[index]`). Neighbor-direction logic
(up/down/left/right drag handles) is computed from that index plus the current column count.

---

## Target Model

The grid is an unbounded sparse coordinate plane. Workers are placed at integer `{ col, row }`
coordinates. The origin `(0, 0)` is the top-left of the initial viewport, with positive coordinates
increasing right and down. Negative coordinates are allowed so the grid can extend up and left.

The occupied region expands on demand. There is no hard max during normal use, but writes must reject
coordinates outside a generous validation envelope of `-100000 <= col,row <= 100000`. This preserves
the unbounded user model while avoiding accidental JavaScript number/pathological-render blowups.

Only occupied cells and explicitly reserved cells are stored. A coordinate can contain at most one
worker. The canonical occupancy index is a `Map<"col,row", worker>`; any write that would place a
second worker into an occupied coordinate must be rejected at the service layer with a structured
collision error.

The viewport shows a rectangular window into this coordinate plane. The user pans the viewport; the
page itself does not scroll.

On first use, or after reset, the viewport starts at `{ col: 0, row: 0 }` and uses Medium layout,
220 px columns, and a visible 4-column x 5-row default working area. Medium is the default so the
initial 4 x 5 area is usable on common laptop and desktop viewports. Large remains available, but it
is not the default because 5 Large rows are taller than most browser viewports.

---

## Viewport And Panning

The grid viewport is a fixed-size clipping element containing a virtualized canvas. Partial cards are
allowed at the viewport edges. This is the v1 recommendation because it makes panning feel continuous
and avoids layout jumps when the viewport size is not an exact multiple of card dimensions.

`viewportOrigin` is a pair of floating-point values in cell units: `{ col, row }`. Fractional origins
are required for smooth wheel, trackpad, and pointer panning. Rendering and hit-testing functions
floor or ceil as needed when converting between pixels and logical cells.

Viewport panning is clamped so the visible range stays inside the writable coordinate envelope,
accounting for the current visible viewport dimensions. This prevents users from panning into regions
where Add Worker or Paste Worker would immediately fail. Cells outside the writable envelope are not
valid creation targets and should not materialize as actionable empty cells.

Panning is handled through gestures and explicit pan controls, not through the same arrow keys used
for selection.

Pointer gestures:

| Gesture | Action |
|---|---|
| Scroll wheel / trackpad two-finger scroll | Pan by `deltaX` and `deltaY` |
| Shift + scroll wheel | Mouse fallback for horizontal pan (`deltaY` becomes horizontal delta) |
| Middle-mouse drag | Free pan |
| Click + drag on empty canvas | Free pan once the pointer has moved past the click/drag threshold |

Keyboard and explicit controls:

| Control | Action |
|---|---|
| Home key | Jump to `{ col: 0, row: 0 }` |
| `f` key (with grid focus) | Run Fit |
| Fit icon button (pane header) | Fit occupied region into viewport; if the grid is empty, fall back to Home |
| Minimap pan-arrow buttons | Nudge viewport by one card width/height |
| Minimap single click | Pan viewport to center on that minimap coordinate (instant, no animation in v1) |

Click vs. drag threshold: a pointer press that releases within 5 CSS px of its origin counts as a
click (selection, menu open, or clear-selection). Movement beyond 5 px promotes the interaction to a
pan. Without this threshold, minor hand tremor during mousedown swallows clicks.

Shift+drag is intentionally reserved for future multi-select range selection. It must not be used
for panning.

Wheel handling: wheel events inside the viewport must be handled with a non-passive listener
(`{ passive: false }`). Call `preventDefault()` to cancel native document scrolling/zooming, and call
`stopPropagation()` if parent handlers would otherwise react to the same wheel event. Trackpads should
use native wheel event deltas directly: when `event.shiftKey` is true, pan horizontally by `deltaY`;
otherwise pan by both `deltaX` and `deltaY`. Browser pinch gestures often arrive as `ctrlKey +
wheel`; since zoom is not in v1, suppress those events with `preventDefault()` inside the viewport so
pinch does not accidentally page-zoom or fight the canvas.

Touch and pen input should use Pointer Events for empty-canvas drag panning. The surrounding page
does not scroll. The canvas pan surface must have `touch-action: none` before the gesture begins,
because browsers decide native touch handling at gesture start. Do not rely on applying
`touch-action: none` only after pointer capture. Keep this rule scoped to the grid pan surface so
other controls in the pane can retain normal browser behavior when appropriate.

Momentum/inertia is optional in v1.

---

## Virtualization

Only cells within the visible viewport plus an overscan buffer are rendered. Rendering a
1000 x 1000 grid of placeholders is not feasible.

Use a windowing model:

- Track `viewportOrigin: { col, row }` as fractional cell coordinates.
- Derive `visibleSize: { cols, rows }` from viewport pixel dimensions and `{ width, height }` card
  size.
- Render the visible range plus an overscan buffer.
- Use `overscanCells = 2` by default, defined as a named constant so it can be tuned after profiling.
- Render empty cells only when they are inside the virtualized range **and** are the current
  interactive coordinate: hovered by pointer, holding keyboard focus, menu-open target, active
  directional-drag drop target, or active paste target. A non-empty pane clipboard does not
  materialize every visible empty cell; it only enables Paste Worker on the current actionable empty
  coordinate. No other condition materializes an empty cell.
- Represent all other empty space with the canvas background grid/dot pattern.

Empty-cell hover must not require a DOM node for every empty cell. Pointer events land on the canvas;
the current logical cell is resolved with `pixelToCoord`; then one reusable ghost-cell/menu-target
element is rendered at that coordinate. Keyboard focus and targeted Add/Paste menus on an empty
coordinate use the same ghost-cell mechanism.

Performance targets:

- 60 fps panning at 100 x 100 scale on a typical development machine.
- 60 fps panning at 1000 x 1000 sparse scale, with minimap geometry memoized and the occupied-dot
  layer not rebuilt per pan frame.

The virtualized render path is required before any high-scale testing.

---

## Infinite Canvas Orientation

Render a faint grid line or dot pattern on the empty canvas so users understand they are on a large
coordinate plane rather than in blank whitespace.

A minimap is in scope for v1. Without it, users have too little spatial orientation once the grid
extends beyond the initial block.

---

## Card Layouts

Card layout is chosen per pane using three icon buttons in the tab header, replacing the rows x cols
dropdown. All cards in the pane share one layout at a time.

| Layout | Contents | Card height |
|---|---|---|
| **Small** | Header only | 48 px |
| **Medium** | Header + task queue | 140 px (default) |
| **Large** | Header + task queue + chat readout | 280 px |

Heights are exact, not approximate. The geometry module treats them as constants so row pitch is
deterministic and sub-pixel drift does not compound across large grids.

Card outer dimensions are invariant for the active layout. If queue contents, chat readouts, worker
names, output text, or future fields exceed the available space, the card interior must clip, wrap,
collapse, or scroll internally. Content must never grow the outer card height or width, because that
would invalidate row pitch and virtualization math.

Card width is fixed per pane, independent of viewport width. The default width is 220 px. Add a
numeric input in the pane header labeled `Width: [220] px`, next to the layout icon buttons, with
20 px steppers, a 140 px minimum, and a 480 px maximum. Persist this as `columnWidth` in the
per-pane grid state.

Row pitch is derived from the active layout height. A worker's `{ col, row }` stays the same when the
user switches layout; the visual y-position is recalculated from the new row height, so rows spread
apart or contract uniformly and cards do not overlap.

Dragging column edges to resize is deferred; it would require hit-testing across every rendered card
boundary and is not needed for v1.

The IDLE / WORKING / QUEUED status pill and elapsed timer must be visible in the card header for all
layouts. Move status into the header as part of this work so Small layout remains useful at a glance.

---

## Selection And Keyboard

Panning and selection are separate interaction modes. Arrow keys always navigate worker selection;
they never pan the canvas.

### Single-card selection

- Click a card to select it unless the click is on a drag handle or interactive control.
- Interactive controls that suppress selection on click include: the four directional drag handles,
  the status pill, the elapsed-time indicator, the `...` menu trigger, and any button or form
  control inside the card header. A click anywhere else on the card selects it.
- Only one card is actively selected in v1.
- Store selection internally as an array of coordinates from the start so multi-select can be added
  without replacing the state shape.
- Clicking empty canvas clears selection unless the click begins an empty-canvas pan (see the
  click/drag threshold in Viewport And Panning).
- Escape closes the active menu if one is open; otherwise it clears selection.

### Keyboard navigation

When a worker is selected:

| Key | Action |
|---|---|
| Arrow keys | Move selection to the nearest occupied worker in that direction |
| Tab / Shift+Tab | Move selection to next/previous occupied worker in row-major order |
| Enter | Open the selected worker's context menu |
| Escape | Close menu / deselect |

When no worker is selected, arrow keys select the nearest occupied worker in that direction from the
current viewport center. If no worker exists in that direction, the grid does not `preventDefault`
the key event (so native browser behavior for that key is still available) and briefly flashes a
boundary indicator on the viewport edge closest to the attempted direction, so the no-op is visible
rather than silent.

For arrow-key navigation, "nearest in a direction" means strictly axis-aligned first: right/left
prefer workers on the same row, up/down prefer workers in the same column. If no worker exists on
that exact axis, choose the closest worker in the half-plane for that direction, sorted by primary
axis distance and then perpendicular distance.

Tab order for a sparse grid is row-major over occupied workers: sort by `row` ascending, then `col`
ascending. Negative coordinates naturally sort before positive coordinates.

Selection does not stop at viewport edges. If the next selected worker is outside the visible
rectangle, pan the viewport enough to bring it into view.

Keyboard-only panning is available through the minimap frame's four pan buttons, plus Home and Fit.
This avoids the previous mode split where arrow keys sometimes panned and sometimes selected.

### Menus

Occupied worker cards keep their current `...` menu behavior and add Copy Worker. This grid spec does
not define or rename pre-existing occupied-card menu items; implementers should preserve the menu
items already exposed by `WorkerCard` and add only the Copy Worker item required by this work.

Unoccupied slots should no longer show always-visible Add/Paste inline UI. Empty slots materialize
only when hovered, focused, or opened through a targeted add action, using the same `...` menu visual
style as occupied cards.

Unoccupied slot menu items:

- Add Worker
- Paste Worker — always shown for layout stability; rendered **disabled** (greyed, non-clickable)
  when the pane clipboard is empty or when the target coordinate is not empty. Hiding the item
  instead of disabling it would cause the menu to change height as clipboard state changes.

When a menu is open:

- Up/Down arrows move between menu items.
- Enter activates the highlighted item.
- Escape closes the menu and returns focus to the card or cell without clearing selection.

### Multi-select deferred

Multi-select is not implemented in v1, but the design must preserve the path:

- `selectedCells` is an array.
- Shift+Click is reserved for range selection.
- Ctrl/Cmd+Click is reserved for additive selection.
- Selected cells should all show a focus ring when multi-select lands.
- Future bulk operations should act on the full selection. No bulk Copy, Delete, or Move commands
  are part of v1.

---

## Worker Copy / Paste

Copy Worker must use a field whitelist. It must never clone the full worker object.

The copied worker config includes:

- User-set worker name
- Model ID
- System prompt
- Expertise prompt / expertise tags
- Display settings: icon, color/theme, and avatar reference if any
- Per-worker card layout preference, if stored per worker rather than per pane
- Any other explicit, non-secret, non-runtime UI fields declared in the whitelist in code

The whitelist is the source of truth, not this document. Any field added to the worker record in the
future must be added explicitly to the whitelist, or it is dropped on copy.

The copied worker config excludes:

- API keys
- Session tokens
- Conversation history
- Current task queue
- Runtime process state
- Any credential-bearing field added in the future

Clipboard state is in-memory UI state, scoped to the current Bullpen tab instance. It is not written
to disk, does not survive reload, and is not shared across panes or projects in v1. Paste Worker is
enabled only when the current pane has a valid copied worker config and the target coordinate is
empty.

The implementation should expose a helper such as `copyableWorkerConfig(worker)` and test that it
drops unknown fields by default.

Undo/redo for Copy/Paste/Delete/Move workflows is out of scope for v1. Paste and future destructive
worker operations should still be implemented through small action helpers so an undo layer can wrap
them later without rewriting the grid model.

---

## State And Migration

Replace `state.config.grid` from:

```js
{ rows, cols }
```

to:

```js
{
  layout: "medium" | "large" | "small",
  columnWidth: number,
  viewportOrigin: { col, row }
}
```

Grid state is per pane / per `BullpenTab` instance and is persisted to disk across reloads. Reloading
must preserve `layout`, `columnWidth`, and `viewportOrigin`, especially for panes whose workers are
far from the origin.

Worker placement moves from slot index to coordinates stored on the worker:

```js
{ col, row }
```

Coordinate migration is the first implementation step. Existing workers with slot indices must be
mapped with the saved column count:

```js
{ col: index % cols, row: Math.floor(index / cols) }
```

If `cols` is missing, zero, or negative in saved state, fall back to a safe default (`cols = 4`,
matching the first-use working area) and emit a migration warning. Do not silently divide by zero or
drop workers. Validate `cols` before the divide, not after, so the fallback is visible in logs.

Migration must run before any component assumes 2-D placement. Preserve existing worker ordering and
avoid moving workers during migration. If migration encounters duplicate coordinates, keep the first
worker in its mapped coordinate and place later colliding workers into the nearest empty coordinate to
the right, emitting a migration warning.

On load:

- Read old `{ rows, cols }` if present.
- Convert any indexed slots into coordinate-bearing worker records.
- Validate all coordinates against the configured coordinate range.
- Build the canonical occupancy map and reject duplicate coordinates outside migration recovery.
- Write the new grid config shape with defaults for missing `layout`, `columnWidth`, and
  `viewportOrigin`.
- Derive the rendered range from `viewportOrigin`, viewport pixel size, card width, and layout row
  height.

---

## Drag And Drop Behavior

Directional drag handles move from 1-D index arithmetic to coordinate arithmetic.

For a worker at `{ col, row }`, the neighbor target for each handle is:

| Direction | Target coordinate |
|---|---|
| Up | `{ col, row: row - 1 }` |
| Down | `{ col, row: row + 1 }` |
| Left | `{ col: col - 1, row }` |
| Right | `{ col: col + 1, row }` |

If the target coordinate is occupied, the drag/drop operation addresses that worker. If the target is
empty, the operation addresses that empty cell and may reveal the Add/Paste affordance. Empty targets
at the edge of the occupied region are valid; they are how the grid grows.

Neighbor lookup uses the canonical occupancy `Map<"col,row", worker>`, not an array scan.

Large-distance card dragging is out of scope for v1. Drag handles only address adjacent coordinates.
If a future full-card drag/drop interaction is added, its drop target should be resolved with
`pixelToCoord` and the same collision rules used by Paste Worker.

---

## Geometry Module

Extract grid math into `static/gridGeometry.js` from the start. These functions must be pure,
side-effect free, and testable with plain Node (no Vue and no DOM).

`viewportOrigin` values are floats in cell units. `cardSize` is always an object with explicit
dimensions:

```js
{ width: number, height: number }
```

Required exports:

- `coordKey(col, row)` -> string key for the occupancy map
- `indexToCoord(index, cols)` -> `{ col, row }` — migration/compat helper only; not for runtime use
- `coordToIndex(col, row, cols)` -> `number` — migration/compat helper only; not for runtime use
- `visibleRange(viewportOrigin, viewportPx, cardSize)` -> `{ colStart, colEnd, rowStart, rowEnd }`
- `overscanRange(visibleRange, buffer = 2)` -> same shape with buffer added
- `pixelToCoord(px, py, viewportOrigin, cardSize)` -> `{ col, row }`
- `coordToPixel(col, row, viewportOrigin, cardSize)` -> `{ x, y }`
- `occupiedBounds(coords)` -> `{ colMin, colMax, rowMin, rowMax } | null`
- `nearestOccupiedInDirection(origin, direction, occupiedCoords)` -> coordinate or `null`
- `clampOriginToOccupied(viewportOrigin, occupiedBounds, viewportPx, cardSize)` -> optional for v1

The two `*ToIndex`/`indexTo*` helpers exist solely so migration and legacy compatibility code paths
can be tested in isolation. Runtime code should index workers by `coordKey(col, row)` and never
compute or consume slot indices.

Edge behavior:

- `occupiedBounds([])` returns `null`.
- `Fit` treats `null` occupied bounds as Home.
- `visibleRange` floors start coordinates and ceils end coordinates so partial edge cards are
  included.
- `pixelToCoord` floors the logical coordinate after applying fractional `viewportOrigin`.
- `coordToPixel` returns the top-left pixel of the coordinate relative to the viewport.
- `nearestOccupiedInDirection` uses the axis-first, half-plane fallback behavior defined in
  Selection And Keyboard.
- `clampOriginToOccupied` and any viewport-origin clamp helper must also respect the writable
  coordinate envelope, so panning does not expose actionable out-of-bounds cells.

---

## Minimap Specification

The minimap is a collapsible overlay in a viewport corner, defaulting to bottom-right.

- **Dimensions**: fixed frame of 160 x 120 px; collapsible to a single icon button.
- **Rendering**: occupied cells render as colored dots, with color based on worker status
  (idle/working/queued). Empty cells are transparent. The current viewport rectangle is drawn as a
  semi-transparent outline or fill.
- **Interaction**: clicking a point in the minimap pans the viewport to center on the coordinate
  derived from the minimap's continuous bounds-to-coordinate transform, not from the rendered dot
  under the pointer. This remains true when dots are aggregated or rendered below 1 CSS px. Four
  pan-arrow buttons live in the minimap frame and nudge the viewport by one card width/height.
- **Scale**: first compute occupied bounds expanded by the current viewport and a small margin. If
  that scaled region fits within 160 x 120 at 1 px per cell, use 1-3 px dots. If it does not fit,
  switch to fit-to-frame scaling and allow dots to fall below 1 CSS px through canvas rendering or
  aggregate multiple workers into one visible pixel.
- **Bounds**: use occupied bounds expanded by the current viewport and a small margin so isolated
  far-away workers remain visible in context.
- **Performance**: recompute minimap geometry only when worker placement, worker status, or the
  occupied set changes. Do not rebuild the occupied dot layer on every pan frame; only update the
  viewport rectangle during panning.

---

## Accessibility

The grid should be keyboard and screen-reader navigable from the first implementation pass, even if
advanced multi-select is deferred.

- The viewport should expose `role="grid"` or an equivalent ARIA structure.
- Rendered worker and ghost cells should expose positive 1-based `aria-rowindex` and
  `aria-colindex` values derived from the current rendered/windowed grid, because ARIA indices cannot
  be negative. The real signed `{ col, row }` coordinate must be included in the human-readable
  `aria-label` and live-region text.
- The active cell should use a roving tabindex pattern so keyboard focus remains predictable under
  virtualization.
- Selection changes should be announced through a polite live region, for example "Selected worker
  Builder at column 4, row 2" or "Empty cell at column -1, row 0".
- Menu controls must be reachable by keyboard and follow the Escape behavior defined in the menu
  section.
- Pointer-only operations, including panning and minimap movement, must have keyboard alternatives.

---

## Implementation Sequence

1. Extract and test `gridGeometry.js`.
2. Add migration from indexed slots to coordinate placement.
3. Update persisted grid config to `layout`, `columnWidth`, and `viewportOrigin`.
4. Replace viewport-fitted card sizing with fixed column width and layout-driven row height.
5. Add virtualized visible/overscan rendering and sparse empty-cell materialization.
6. Rewrite drag-handle neighbor detection around coordinate keys.
7. Add gesture panning, Home, Fit, and minimap pan controls.
8. Add selection/menu keyboard behavior and ARIA wiring.
9. Implement Copy Worker / Paste Worker with whitelist copying.
10. Add the minimap occupied-dot layer and viewport rectangle.
11. Replace rows x cols dropdown with layout buttons and the width input.
12. Move worker status/timer into the card header for all layouts.

Steps 11 and 12 are UI-only and may land in parallel behind a compatibility flag once the geometry,
migration, and rendering path are stable.

---

## Test Plan

Unit tests:

- Index-to-coordinate migration for several saved column counts.
- Migration from malformed saved state: `cols` missing, `cols: 0`, `cols: -3`, and missing `slots`
  array. Workers must not be dropped and the fallback warning must fire.
- Coordinate-to-index inverse behavior for compatibility paths.
- Visible range math with partial cards at all four viewport edges.
- Overscan expansion and negative-coordinate ranges.
- Pixel/coordinate conversion around card boundaries.
- `cardSize` handling with non-square Small, Medium, and Large dimensions.
- Viewport-origin clamping to the writable coordinate envelope.
- Empty `occupiedBounds` returning `null`.
- Occupied bounds and nearest-worker selection, including axis-first and half-plane fallback cases.
- Collision rejection for worker placement, Paste Worker, and service-layer writes.
- Coordinate range validation.
- Copy Worker whitelist excludes unknown and credential-like fields.

Frontend structure / behavior tests:

- Rows x cols dropdown is removed.
- Layout buttons and width input are present.
- Worker status/timer render in the card header for Small, Medium, and Large layouts.
- Empty slots are not rendered outside the virtualized range.
- Hovering empty canvas renders only one ghost-cell/menu-target element, and a non-empty clipboard
  does not materialize every visible empty cell.
- Empty slot menu exposes Add Worker and Paste Worker only when materialized.
- Paste Worker is disabled (greyed, non-clickable) when the clipboard is empty or the target is
  occupied; it is not hidden.
- Directional drag handles compute coordinate targets.
- Large-distance card drag is not supported (only adjacent handles address neighbor coordinates).
- Arrow keys do not pan; minimap buttons do.
- Arrow key pressed with no worker in that direction flashes the boundary and does not
  `preventDefault` the key event.
- Tab order follows row-major sorting for sparse and negative coordinates.
- Escape closes menus without clearing selection, then clears selection when no menu is open.
- ARIA grid roles, active cell focus, and live-region selection announcements are present.
- Minimap click centers the viewport instantly on the clicked coordinate with no animation.
- Minimap click mapping uses the continuous minimap bounds transform even when occupied dots are
  aggregated or rendered below 1 CSS px.
- Card width input rejects values below 140 or above 480, and steps by 20.
- Wheel listeners on the grid viewport are non-passive and cancel native scrolling/zooming.
- The canvas pan surface has `touch-action: none` before pointer gestures begin.
- ARIA row/column indices are positive while signed grid coordinates appear in labels/live-region
  text.
- Card content overflow does not change the outer card dimensions for any layout.

Manual verification:

- Existing saved layouts migrate without moving workers.
- 20 x 20 and 100 x 100 test data pans smoothly.
- 1000 x 1000 sparse data does not create a large DOM.
- Trackpad two-finger horizontal and vertical panning work without Shift.
- Mouse Shift+wheel pans horizontally.
- Ctrl+wheel/pinch does not trigger accidental zoom inside the grid viewport.
- Minimap remains responsive while panning.
- Empty-grid Fit falls back to Home.
- Clipboard does not persist after reload and does not cross panes/projects.
- Switching Small/Medium/Large preserves worker coordinates and recalculates row pitch without
  overlap.

---

## Disregarded Review Feedback

No substantive review feedback was disregarded.

Two editorial suggestions were incorporated by adjustment rather than literal deletion. The
drag-handle material remains as its own `Drag And Drop Behavior` section because it now also defines
large-distance drag scope and collision behavior. The implementation sequence keeps UI cleanup steps
visible but marks them as parallelizable once the structural grid work is stable.
