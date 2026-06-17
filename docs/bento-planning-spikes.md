# Bento Planning Spikes

Status: Planning

## Purpose

The Bento package work is sensitive because it crosses a trust boundary and
touches live Bullpen state. Treat the first planning pass as two spikes, not as
a broad implementation kickoff. The goal is to prove the carrier boundary and
the worker package planner before expanding into tickets, clipboard fragments,
scanners, or social distribution.

## Spike 1: Carrier Foundation

Question:

Can Bullpen safely recognize, validate, and preview a Bento carrier without
applying any Bullpen semantics or mutating workspace state?

Deliverables:

- Carrier validation contract for `bento.json` packages.
- Decision on module placement for carrier code.
- Preview event shape for carrier-only results.
- Import routing order for Bento and legacy archives.
- Test matrix for unsafe archives and unsupported Bento files.

Scope:

- ZIP structure validation.
- Local path safety.
- Duplicate normalized path rejection.
- Special-file rejection.
- Resource limits.
- Manifest parse and version checks.
- Item path existence checks.
- Unsupported-but-valid Bento preview.
- Legacy zip import/export compatibility checks.

Out of scope:

- Worker import.
- Ticket import.
- Approval UI.
- Clipboard fragment migration.
- Scanner integration.
- Social sharing.

Key decisions:

- Whether carrier validation extracts to a temporary directory or validates
  directly from `ZipFile` first.
- Whether preview uploads are stateless or produce a short-lived server-side
  preview token.
- Exact JSON shape for carrier-only preview errors and warnings.
- How to report unsupported profiles without implying trust.

Exit criteria:

- Unsafe archives fail before profile handling.
- A valid non-Bullpen Bento previews as unsupported.
- Legacy workspace, workers, and all-workspaces imports still work.
- No Socket.IO event applies package contents during preview.

## Spike 2: Worker Package Planner

Question:

Can a worker or worker group travel through Bento with safe preview, loose
name-based binding, placement conflict handling, and dormant import behavior?

Deliverables:

- Worker package examples for one worker and worker groups.
- Worker preview result shape.
- Worker import apply request shape.
- Placement conflict option list.
- Name-binding warning and rewrite rules.
- Runtime-state stripping rules for imported workers.
- Test matrix for worker round trips, conflict handling, and ambiguous names.

Scope:

- `.bento` export for one worker.
- `.bento` export for selected worker groups.
- Referenced profile inclusion.
- Worker preview with names, types, profiles, grid positions, warnings, and
  conflicts.
- Import in add/merge mode only.
- Dormant imported workers.
- Runtime state stripping.
- Loose relationship handling for `worker:NAME`, `random:NAME`,
  `pass:DIRECTION`, and bare column dispositions.

Out of scope:

- Replace-selected import.
- Ticket packages.
- Approval gates beyond default sanitization.
- Clipboard fragment migration.
- Scanner remediation.
- URL import or gallery sharing.

Key decisions:

- Exact conflict choices shown when target cells are occupied.
- How imported worker name conflicts are renamed.
- When package-local name references are rewritten after rename.
- How unresolved or ambiguous bindings appear in preview and import results.
- Whether command/service/notification/git fields are stripped, disabled, or
  retained inert before Slice 2 approval gates exist.

Exit criteria:

- A single worker round-trips through `.bento`.
- A pass-connected worker group round-trips with relative positions intact.
- Placement conflicts produce an explicit plan choice instead of silent movement.
- Imported workers cannot run, enqueue, notify, mutate git, or start services
  merely because they were imported.

## Planning Output

Each spike should finish with:

- Implementation ticket list.
- Test plan.
- Open questions promoted or closed.
- Any required spec updates to `docs/file-format-rationalization.md`.

Only after both spikes are complete should Bullpen plan the first implementation
slice. That implementation slice should remain a vertical proof: worker package
export, safe preview, explicit placement, dormant import, and unchanged legacy
zip behavior.
