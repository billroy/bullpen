# Marker Workers

## Summary

This proposal adds a new top-level worker type:

- `type: "marker"`

A **Marker worker** is a first-class worker-grid card whose main job is to
label an area of the grid for humans. It should be useful even if it never
receives a ticket. A marker can also serve as a stable jump target in
navigation flows such as **Go to worker**, and it can be used as a no-op
pass-through in a routing chain.

The key idea is balance:

- **Label/documentation behavior** is the primary product value.
- **Target/routing behavior** is equally supported, but should not dominate the
  way the feature is framed or rendered.

This is intentionally **not** a comment system, sticky-note layer, or rich
annotation surface. It is a worker-shaped object that occupies a real cell,
participates in layout and navigation like any other worker, and can accept
tickets without spawning a subprocess.

`Marker worker` is the recommended name.

- `Label worker` sounds purely visual and undersells the fact that the card can
  participate in the normal worker flow.
- `Comment worker` suggests discussion, mutation, or note-thread semantics that
  this proposal does not include.
- `Waypoint worker` is good for routing and navigation, but too weak on the
  labeling/documentation side.

`Marker` best captures both roles without overcommitting the feature to one of
them.

---

## Goals

- Let users place named visual markers inside the worker grid to document
  regions such as `Frontend`, `Deploy`, `QA lane`, or `Customer A`.
- Let those markers look and feel like first-class cards in the grid rather
  than a separate overlay or annotation layer.
- Let those markers appear in worker navigation and search so they can act as
  jump targets.
- Let those markers be used as the visible start, end, or waypoint of a worker
  chain.
- Allow tickets to be dropped onto or routed to a Marker worker.
- Preserve the normal worker-grid mental model: markers are still occupied grid
  cells, not free-floating labels.

## Non-goals

- No rich-text or markdown rendering in v1.
- No arbitrary board comments, threaded notes, or collaborative annotations.
- No multi-cell spanning, merged cells, or floating labels in v1.
- No subprocess execution, health checks, or output streaming.
- No marker-specific routing DSL, marker-specific trigger model, or
  marker-specific loop-detection scheme.

---

## Why this should be a worker type

This should be a new top-level worker type rather than:

- a special visual mode on AI/Shell/Service workers,
- a free-floating canvas annotation layer,
- or a subtype hidden inside existing disposition rules.

Reasons:

1. It occupies a real grid cell and should participate in copy/paste, move,
   minimap, selection, team save/load, transfer, export/import, and Go to.
2. It has distinct runtime semantics: it can accept tickets, but it performs no
   subprocess run.
3. It needs dedicated UI defaults and validation rules that do not fit
   AI/Shell/Service.
4. It is conceptually useful even when it never receives a ticket at all.

So the correct storage shape is:

```text
type: "marker"
```

---

## User stories

### Visual documentation

The operator lays out the grid like this:

```text
Frontend marker -> UI Spec worker -> UI Build worker
Backend marker  -> API Spec worker -> API Build worker
Deploy marker   -> Staging service -> PR merge -> restart
```

The marker cards make the grid readable at a glance without requiring every
visual divider to be a runnable worker.

### Jump target

The operator opens **Go to**, types `Deploy`, and jumps directly to the Deploy
marker even if the actual runnable workers in that area have changed.

### Visible start of a chain

The operator wants the workflow entrance to be obvious in the grid:

```text
Incoming bugs -> Intake marker -> triage worker -> implementation
```

The marker is both the visual signpost humans look for and a real worker target
that can receive drops, watched-column claims, manual runs, or scheduled
triggers.

### Routing waypoint

Another worker routes to `worker:Intake marker`. The ticket lands on the marker
and is then forwarded according to the marker's configured disposition.

---

## Config model

Reserve these Marker-specific fields on worker slots:

| Field | Type | Default | Notes |
|---|---|---:|---|
| `type` | string | `"marker"` | New built-in worker type |
| `name` | string | required | Primary visible label and Go to target |
| `note` | string | `""` | Optional secondary text shown on the card |
| `disposition` | string | `""` | Same output behavior as any other worker |
| `icon` | string | `"square-dot"` | Override allowed, same pattern as other workers |
| `color` | string | theme light color | Default card accent/background family |

Recommended defaults:

- icon: `square-dot`
- color: the current theme's light card color

Validation rules:

- `name` is required and uses the existing worker-name constraints.
- `note` is optional and should be capped at a modest size, e.g. 500 chars.
- `disposition` is optional for pure labeling use, but a Marker worker with a
  blank disposition is considered non-routable.
- If a ticket is assigned to a non-routable marker, the assignment fails closed
  and the ticket goes to **Blocked** with a clear reason.
- Marker workers support the same trigger/activation fields as other workers.
- Marker workers support the same disposition strings as other workers.

UI label recommendations:

- Show the type as **Marker** in the worker library.
- In the config modal, label `disposition` as **Pass tickets to** for Marker
  workers while still storing the canonical `disposition` field.
- In the same library cleanup, remove the Eval worker stub instead of keeping a
  disabled placeholder beside Marker.

### Config modal scope

The Marker config modal should be a slimmed-down version of the ordinary worker
modal, not a totally custom dialog.

Recommended fields to show:

- Name
- Note
- Icon
- Color
- Input Trigger / activation
- Output / Pass tickets to
- Watch column when activation is `on_queue`
- Scheduling fields when activation is `at_time` or `on_interval`

Recommended fields to hide:

- agent/model/profile
- expertise prompt
- trust mode
- max retries
- worktree / auto-commit / auto-pr
- command / cwd / env / timeout
- service-specific lifecycle and health fields

The goal is for the modal to feel like "the normal worker editor, narrowed to
the fields Marker actually uses."

---

## Runtime behavior

Marker workers do not run commands and never spawn a subprocess. Aside from
that, they should behave as much like any other worker as possible.

### Assignment semantics

When a ticket is assigned to a Marker worker:

1. The marker receives the ticket through the ordinary worker flow.
2. The marker performs no subprocess work.
3. The marker routes the ticket onward according to its configured
   disposition.

This routing is the marker's "work." It is a no-op pass-through rather than an
execution stage.

### Trigger model

Marker workers support the same trigger model as ordinary workers in v1:

- `on_drop`
- `on_queue`
- `manual`
- `at_time`
- `on_interval`

That matters because a marker is often the visible start of a chain rather than
just a passive waypoint in the middle of one.

Specific semantics:

- `on_drop`: a dropped ticket is routed immediately.
- `on_queue`: the marker may watch a column, claim tickets, and route them
  immediately.
- `manual`: `Run` routes the head queued ticket, or creates the usual
  synthetic run ticket if the queue is empty and Bullpen's shared worker
  lifecycle would normally do that.
- `at_time` / `on_interval`: scheduled triggers behave the same way as they do
  for other workers, except the marker's runtime effect is immediate routing
  rather than subprocess execution.

This proposal does not introduce any new trigger model for markers; it adopts
the existing one wholesale.

### Inputs and outputs

Marker workers act like any other worker with respect to inputs and outputs.

That means:

- they accept the same activation/trigger modes as other workers,
- they use the same queue ownership model as other workers,
- and they support the full disposition grammar Bullpen already supports,
  rather than a marker-specific subset.

This is important because it lets markers be used in two equally valid ways:

1. as a visual signpost that also forwards to a nearby worker, and
2. as a named routing alias that decouples upstream workers from a specific
   downstream worker name.

Example:

```text
Implementation reviewer
  disposition = worker:PR staging marker

PR staging marker
  disposition = worker:PR service
```

Now upstream workers can target the marker name and the operator can later
change the marker's destination without editing every upstream worker.

### State model

Marker workers should not invent a marker-only lifecycle.

This proposal does **not** add a new marker-specific event type, queue model,
or loop-checking scheme. Where Bullpen already has shared worker-flow behavior,
Marker should inherit it. The only important difference is that the marker does
not launch a subprocess; its contribution to the flow is routing and labeling.

For user-visible behavior:

- no visible `working` state is required,
- no visible card queue is required for the common nearly-instant pass-through
  case,
- and the card should normally return to its resting label presentation
  immediately after the route step completes.

---

## Grid UI

Marker workers should look no different from ordinary runnable workers in their
overall card construction. The user should read them as labels first, but the
visual treatment should stay within the same "deed card" family as the rest of
the worker grid.

### Card presentation

Recommended v1 treatment:

- same overall card shell as other workers
- large label text in the header/body
- optional short note beneath the title
- default background uses the theme's light card color
- signature icon is Lucide `square-dot`
- keep ordinary queue/status framing where it exists today
- no subprocess-specific output affordances

Example card copy:

```text
Deploy
staging + release path
```

The normal persistent presentation should stay label-oriented.

### Menus and controls

Marker worker menus should stay as close to the existing occupied-card menus as
possible.

Required actions:

- Edit
- Run
- Duplicate
- Copy Worker
- Copy to workspace
- Move to workspace
- Delete

Not present in the first cut:

- Watch
- Stop
- Restart

`Watch` in Bullpen's existing card vocabulary means "open the worker focus/log
view." Marker workers have no live subprocess output, and no marker-specific
focus/detail view is needed, so `Watch` should be omitted.

`Stop` and `Restart` are also omitted in the first cut. `Run` remains important
because a marker can be the visible start of a multi-worker flow, but a no-op
pass-through worker does not need stop/restart controls until there is a more
substantial runtime model to justify them.

### Empty-cell library

The Add Worker library should gain a **Marker** option alongside AI, Shell,
and Service.

Suggested create flow:

1. Click empty cell.
2. Choose **Marker**.
3. Open config modal immediately.
4. Focus the Name field first.

Related cleanup:

- Remove the Eval worker type UI stub from the Create Worker menu while adding
  Marker.

### Go to / navigation

Marker workers must appear anywhere Bullpen lets the operator navigate by
worker name. That includes the current **Go to** worker search. This is part of
the product value, not an incidental side effect.

---

## Interaction with the worker grid

Marker workers are real occupied cells.

They must:

- appear in the minimap
- participate in keyboard selection
- block paste/collision like any other worker
- support move, duplicate, copy/paste, transfer, and team save/load
- preserve `row` / `col` like any other worker

They must not:

- materialize a new overlay system
- span multiple cells in v1
- depend on hover-only visibility for their label

The operator should be able to scan the grid and understand area labels even
when not interacting with a card.

---

## Persistence and compatibility

Marker workers should fit the same soft-open worker-type model already used by
Bullpen's worker framework.

Requirements:

- `type: "marker"` round-trips through layout save/load.
- Marker-specific fields round-trip through copy/paste, transfer, team
  save/load, export/import, and app restart.
- Unknown future fields on a Marker worker should be preserved by the existing
  normalization philosophy where feasible.

Backward compatibility:

- Existing workspaces are unaffected.
- Older builds that do not understand `type: "marker"` should degrade via the
  current unknown-worker-type path rather than corrupting the layout.

---

## Failure behavior

Because Marker workers are mostly configuration, failures are deterministic and
should be reported clearly.

Cases:

- blank disposition on ticket arrival
- invalid disposition token
- `worker:NAME` target not found
- `pass:DIRECTION` with no adjacent worker

Recommended behavior:

- fail closed
- move ticket to **Blocked**
- clear `assigned_to`
- append the failure to the Agent Output / Worker Output section if that is
  straightforward in the shared worker path; otherwise append it to the ticket
  body using the existing fallback style Bullpen already uses for worker
  failures
- emit a toast for the operator when the action was user-initiated

Marker workers should not use retry/backoff for these failures because they are
not transient runtime errors.

This proposal does not add any new loop detection or chain-depth enforcement.
Marker workers inherit whatever worker-flow management scheme Bullpen already
uses at implementation time.

---

## Test plan

Minimum required coverage:

### Server/runtime

- Assigning a ticket to a marker with `disposition = review` moves the ticket
  directly to Review and clears assignment.
- Assigning a ticket to a marker with `disposition = worker:NAME` forwards to
  the target worker.
- `pass:RIGHT` forwards to the adjacent occupied cell.
- Missing adjacent target blocks the ticket with a clear reason.
- Blank disposition blocks the ticket with a clear reason.
- Marker-to-marker chains route the same way any ordinary worker chain would.
- Marker assignment does not spawn a subprocess or register live process state.
- `on_queue`, `manual`, `at_time`, and `on_interval` all work for Marker
  workers the same way they do for other workers, except the runtime effect is
  immediate routing.

### Frontend

- Add Worker library exposes Marker.
- Marker card renders with the same overall card shell as ordinary workers,
  using the theme's light card color and `square-dot` as the default icon.
- Marker config modal exposes the ordinary trigger/disposition model.
- Go to includes marker names.
- Marker cards participate in selection, minimap, copy/paste, and transfer.
- Eval worker stub is removed from the Create Worker menu while Marker is
  added.

---

## Rollout recommendation

### Phase 1: useful and aligned with the existing worker model

- new `type: "marker"`
- create/edit/delete/move/copy/paste support
- label + note rendering
- Go to inclusion
- same trigger/disposition model as other workers
- immediate pass-through routing with no subprocess run

### Phase 2: polish if the first version earns usage

- richer visual themes
- optional larger display mode
- optional minimap labels
- optional structured links from docs or commands to marker names
- optional multi-cell banner/span behavior

Phase 1 is already valuable without turning the feature into a full annotation
product.

---

## Final recommendation

Ship this as a **Marker worker**.

Treat it as:

- a first-class worker-grid landmark for humans, and
- a no-op routing waypoint for tickets.

That gives Bullpen a lightweight way to document large grids and creates a
stable naming layer for navigation and handoff design, without inventing a
separate annotation system or overloading existing worker types.

## Implementation planning

Implementation planning for this spec now lives in
`docs/marker-worker-implementation-plan.md`.

The product shape is settled enough that the remaining work is implementation
detail, not feature-definition debate. The main issue carried into planning is
the exact shape of the shared-controller **instant worker** branch:

- where it lives in the shared worker lifecycle
- which existing helpers it can reuse unchanged
- and which minimal helper extraction lets Marker acquire a ticket,
  validate/configure routing, record output/history, and apply the next
  disposition without pretending to be subprocess-backed

Everything else is now specified closely enough to plan and implement.
