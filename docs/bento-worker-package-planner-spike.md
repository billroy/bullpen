# Bento Worker Package Planner Spike

Status: Planning spike output

## Readiness

Ready to plan as the second bounded spike after carrier preview exists. Do not
start ticket packages, clipboard migration, scanner remediation, or social
sharing in this spike.

The risky part is not writing a zip. The risky part is making import
preview-first, preserving Bullpen's loose human naming model, and ensuring
workers arrive dormant even when their configuration contains commands,
notifications, queues, or git-affecting options.

## Existing Behavior To Respect

Current worker movement paths already define useful local conventions:

- Legacy worker archive import merges directly and auto-translates conflicting
  coordinates.
- Worker paste rejects occupied coordinates unless replacing one worker
  explicitly.
- Worker group paste rejects any occupied target coordinate.
- Cross-workspace transfer resets runtime state and warns about workspace-local
  dispositions.
- `copy_worker_slot(..., reset_runtime=True)` already clears runtime state for
  copied workers.
- Dispositions are intentionally loose strings and may name workers, columns, or
  directions.

The package planner should reuse these conventions where they are good, but it
must not silently auto-shift imported packages. Bento import should preview the
conflict and ask for a placement decision.

## Proposed Module Boundary

Add `server/bento_workers.py`.

Responsibilities:

- Build worker and worker-group Bento packages from normalized layout data.
- Read worker items from a validated Bento carrier.
- Build worker package preview plans.
- Analyze placement conflicts.
- Analyze loose name bindings.
- Analyze risky capability groups.
- Build an apply plan from preview choices.
- Apply add/merge imports while holding the same write lock used by worker
  state mutations.

Non-responsibilities:

- Low-level carrier validation.
- Ticket package import.
- Clipboard migration.
- Scanner calls.
- Starting workers.
- Running commands.
- Dispatching tickets.

## Package Shape

Worker package exports should use the carrier manifest plus ordinary JSON
payload members:

```text
bento.json
payload/workers/<item-id>.json
payload/profiles/<profile-id>.json
metadata/bullpen-preview.json
```

Worker object payloads should be recognizable current Bullpen worker objects,
not a separate rigid model. Export should avoid runtime-only state by default.

For worker groups, preserve relative positions by including `row` and `col` on
each worker. The preview planner computes the group bounding box and target
coordinates from those fields.

Referenced profiles:

- Include profiles referenced by exported workers when the profile file exists.
- Preview missing profile references as warnings.
- On import, add missing included profiles.
- If a profile already exists, keep the destination profile and warn rather than
  overwriting in the MVP.

## Preview Result Shape

Suggested `bento:previewed` payload once Bullpen worker profile support is
added:

```json
{
  "ok": true,
  "kind": "worker-group",
  "package_id": "preview-token-or-null",
  "items": [
    {
      "item_id": "worker.builder",
      "type": "worker",
      "name": "Builder",
      "worker_type": "shell",
      "profile": "builder-profile",
      "coord": {"col": 0, "row": 0},
      "capabilities": ["commands", "env"],
      "bindings": [
        {
          "field": "disposition",
          "value": "worker:Reviewer",
          "status": "package-local",
          "target": "worker.reviewer"
        }
      ],
      "warnings": []
    }
  ],
  "profiles": [
    {"id": "builder-profile", "status": "included"}
  ],
  "placement": {
    "status": "conflict",
    "state": "placement-fingerprint",
    "requested": [
      {"item_id": "worker.builder", "coord": {"col": 0, "row": 0}}
    ],
    "conflicts": [
      {"coord": {"col": 0, "row": 0}, "existing_name": "Existing Worker"}
    ],
    "options": ["choose-anchor", "place-right", "place-below", "cancel"]
  },
  "capabilities": {
    "commands": 1,
    "services": 0,
    "notifications": 0,
    "git": 0,
    "queues": 0
  },
  "warnings": []
}
```

The first worker-package MVP can avoid server-side preview tokens by requiring
the file to be uploaded again on apply. If that proves awkward, add a short-lived
preview token in a later pass.

The preview placement `state` is a stateless fingerprint of the requested target
cells and any current occupants. Apply requests may send it back as
`placement.state` or `placement.expected_state`; if the same cells no longer
match, import rejects with `stale-preview` before writing.

## Apply Request Shape

Suggested `bento:import` request:

```json
{
  "workspaceId": "workspace-id",
  "mode": "merge",
  "placement": {
    "strategy": "choose-anchor",
    "state": "placement-fingerprint-from-preview",
    "anchor": {"col": 4, "row": 2}
  },
  "name_conflicts": "rename",
  "profile_conflicts": "keep-existing",
  "capability_policy": "sanitize"
}
```

MVP constraints:

- Support only `mode: "merge"` or `mode: "add-only"`.
- Support only `capability_policy: "sanitize"`.
- Reject replacement and capability preservation until approval gates exist.

## Placement Planning

Planner inputs:

- Current normalized layout.
- Current grid config.
- Imported worker coordinates.
- User-selected placement strategy.

Preview options:

- `preserve`: valid only when all requested target cells are empty.
- `choose-anchor`: user picks the top-left anchor for the imported bounding box.
- `place-right`: offer the nearest non-conflicting position to the right of
  current occupied workers.
- `place-below`: offer the nearest non-conflicting position below current
  occupied workers.
- `cancel`: no apply.

Implementation notes:

- Keep group relative offsets intact.
- Reject negative destination coordinates.
- Reject any plan where two imported workers land on the same coordinate.
- Do not silently use legacy auto-translation. It can be reused as a suggestion
  generator, not as the default apply behavior.

## Name Binding

Bullpen package import must preserve loose name-based behavior.

Binding analysis:

- `worker:NAME`: resolve package-local worker names first, then workspace worker
  names.
- `random:NAME`: same as `worker:NAME`, but blank names remain valid.
- `pass:DIRECTION`: preserve and validate only direction shape in preview.
- Bare dispositions: compare to destination column keys and warn on misses.
- `watch_column`: compare to destination column keys and warn on misses.

Ambiguity handling:

- Ambiguous bindings are warnings, not carrier errors.
- Unresolved bindings import dormant and remain visible in the import result.
- If import renames a worker due to a destination name conflict, rewrite only
  package-local references that clearly point to that imported worker.
- Preserve ambiguous external references exactly as authored.

Name conflicts:

- Default strategy: rename imported workers.
- Suggested naming: `Name copy`, then `Name copy 2`, matching existing worker
  copy behavior.
- Import result must report every rename.

## Capability Analysis And Sanitization

The worker MVP should identify risky capability groups but default to safe,
dormant import.

Capability groups:

- `commands`: shell command fields, service command fields, health commands,
  pre-start commands.
- `env`: shell/service environment key-value entries.
- `services`: service worker startup, port, health, crash policy.
- `notifications`: speech, desktop, webhook, or external delivery settings.
- `git`: `auto_commit`, `auto_pr`, worktree/trusted execution fields.
- `queues`: `task_queue`, `state`, `started_at`, service runtime state.

MVP sanitization:

- Always call `copy_worker_slot(worker, reset_runtime=True)` or an equivalent
  shared helper before apply.
- Clear task queues, active state, start timestamps, service runtime state, and
  last trigger timestamps.
- Set imported workers dormant.
- Preserve command/service/notification/git fields only as inert configuration
  if the current app already treats them as inert until explicit start.
- If a field can cause effects merely by being present after import, strip it
  until approval gates exist.
- Never enqueue tickets or start workers during import.

Open decision:

- Whether command/service/notification/git fields should be stripped in the MVP
  or kept inert with warnings. Recommendation: keep inert only when there is no
  automatic activation path; otherwise strip and report.

## Export Events

Add after carrier foundation:

- `bento:export` with `kind=worker` and `slot`
- `bento:export` with `kind=worker-group` and `slots`

Response event:

- Media type: `application/vnd.bullpen.bento+zip`.
- Download extension: `.bento`.
- Current legacy `.zip` worker exports remain available.

Do not remove or rename existing legacy worker export routes in the MVP.

## Import Events

Extend after carrier foundation:

- `bento:preview` recognizes `org.bullpen.share` worker packages.
- `bento:import` applies worker packages only.

Apply behavior:

- Requires auth.
- Requires workspace ID.
- Validates carrier again on apply.
- Builds a fresh plan against current workspace state.
- Rejects apply if current state no longer matches the requested conflict
  decision.
- Writes layout/profiles under the existing write lock.
- Emits `layout:updated` after successful apply.

## Test Matrix

Create `tests/test_bento_workers.py`.

Export:

- Single worker export writes `.bento` with `bento.json`.
- Worker group export preserves relative coordinates.
- Referenced profile is included when present.
- Missing profile reference produces export warning or preview warning.
- Export omits runtime state by default.

Preview:

- Single worker preview lists name, type, profile, coord, and capabilities.
- Worker group preview lists all workers and relative placement.
- Occupied requested coordinate produces placement conflict.
- Pass-connected group reports package-local binding.
- `worker:NAME` missing in package/workspace warns.
- Duplicate destination name proposes rename.
- Command/service/notification/git fields produce capability warnings.

Apply:

- Single worker imports dormant into empty workspace.
- Pass-connected group imports with relative positions intact.
- Import with `choose-anchor` lands at requested anchor.
- Import with stale conflict state rejects and asks for re-preview.
- Destination name conflict renames imported worker and reports it.
- Package-local references rewrite when the referenced imported worker is
  renamed.
- Ambiguous external references preserve original text and warn.
- Included profile imports when missing.
- Existing profile is kept and warning is reported.
- Runtime state, queues, and service state are stripped.
- No worker starts, service starts, notification sends, git mutation, or ticket
  assignment occurs on import.

Legacy compatibility:

- Existing worker `.zip` export/import tests continue to pass.
- Existing worker paste and transfer tests continue to pass.

## Implementation Tickets

1. Add worker package builder in `server/bento_workers.py`.
2. Add worker package preview planner.
3. Add placement planner with explicit conflict options.
4. Add binding analyzer for dispositions and watch columns.
5. Add capability analyzer and MVP sanitization path.
6. Add worker `.bento` export event support.
7. Extend `bento:preview` for Bullpen worker packages.
8. Add `bento:import` for worker packages in add/merge mode.
9. Add tests for worker export, preview, apply, and legacy compatibility.
