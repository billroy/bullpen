# File Format Rationalization

Status: Implemented baseline with deferred slices

## Purpose

Bullpen's current export/import surface grew from practical needs: workspace
archives, all-workspace archives, worker archives, single-worker archives, and
CSV value history downloads. This is useful but not conceptually clean. For a
user with normal external backup, export is not primarily a disaster-recovery
feature. It is a sharing and handoff feature.

This proposal reframes export/import around Bento, a neutral carrier that can
hold Bullpen share artifacts without making Bullpen semantics part of the file
format itself. Backup-like exports remain possible, but they should not define
the core user experience.

## Implementation Readiness

The implemented baseline is ready for follow-on implementation planning within a
bounded scope:

- safe carrier validation and carrier-only preview
- Socket.IO Bento export, preview, and import events
- worker and worker-group packages
- ticket and ticket-bundle packages
- preview-before-apply import discipline
- request-correlated Socket.IO replies
- dormant imports with runtime state stripped
- explicit worker placement choices on conflict
- per-import approval for preserving command, environment, service,
  notification, and git automation fields
- ticket target-column selection limited to dormant columns
- one coherent import review modal for implemented worker and ticket decisions

The next implementation plan should treat this as a proven first package layer,
not as an open-ended file-format redesign. Worksheet, project-template,
project-snapshot, scanner, gallery/social sharing, and grid-native/polished
preview UI work are separate future plans. Unsupported or mixed package kinds
must continue to fail closed until their semantics are deliberately specified.

Follow-on planning should stay split into two lanes:

- Import UX polish: continue refining the coherent preview/apply surface for
  the implemented worker and ticket package kinds.
- New package kinds: decide and specify the next supported kind before adding
  worksheet, project-template, project-snapshot, or mixed-package behavior.

## Current Inventory

Before the Bento worker-package migration, Bullpen had three
downloadable/importable zip archive formats:

1. Workspace archive
   - Former export: `/api/export/workspace`
   - Former import: `/api/import/workspace`
   - Payload: one workspace `.bullpen/` directory with runtime config stripped.

2. Legacy workers archive
   - Former export: `/api/export/workers`, `/api/export/worker`
   - Former import: `/api/import/workers`
   - Payload: `.bullpen/layout.json`, referenced profiles, and
     `bullpen-workers-export.json`.
   - Single-worker, worker-group, and all-worker downloads are variants of the
     same archive format.
   - Status: removed from the app surface after the Socket.IO Bento worker
     export/import path was wired.

3. All-workspaces archive
   - Former export: `/api/export/all`
   - Former import: `/api/import/all`
   - Payload: `workspaces/<workspaceId>/.bullpen/...` plus
     `bullpen-export.json`.

Adjacent transfer formats exist but are not durable Bullpen archive formats:

- Value worker history CSV.
- In-memory worker copy/paste payloads.
- Worksheet clipboard TSV/CSV-ish paste into value workers.

## Design Direction

Introduce a single durable carrier:

- File type: Bento
- Extension: `.bento`
- Physical encoding: zip file
- Primary manifest: `bento.json`
- Generic media type: `application/vnd.bento+zip`
- Bullpen media type: `application/vnd.bullpen.bento+zip`

The extension identifies the file as a Bento carrier. The carrier manifest
identifies profiles, items, and arbitrary labeled JSON attribute bundles. Bullpen
semantics live in a Bullpen profile layered on top of the carrier.

The carrier SHALL be strict about archive safety, path safety, resource limits,
manifest parseability, and references from manifest to archive members. It SHALL
NOT impose exact object models for application objects. Profile-aware importers
own semantic validation.

### Labeled Attribute Bundles

The Bento manifest has a first-class `attributes` array. Each entry is a labeled
JSON metadata bundle with a namespace and either inline JSON or a path to a JSON
member. This makes the container self-describing without requiring every future
producer to wedge metadata into the top-level manifest.

Attribute bundles can describe:

- preview card metadata
- compatibility notes
- scanner findings
- source application hints
- social sharing metadata
- import policy suggestions
- arbitrary third-party extension metadata

Importers MUST preserve unknown bundles when round-tripping unless the user
chooses to sanitize the file. Importers MUST NOT execute behavior merely because
an attribute bundle requests it.

This keeps file naming simple while avoiding extension sprawl:

- Do not create separate long-term extensions for worker, worksheet, ticket,
  template, or project-snapshot exports.
- Put those distinctions in profile metadata inside the manifest.
- Treat existing `.zip` exports as legacy compatibility endpoints or advanced
  maintenance tools.

## Bullpen Profile Kinds

The carrier manifest does not require package kinds. The Bullpen profile can
define a `kind` hint for UX and default import behavior, but the current
implementation treats that hint as confirmation, not proof. The actual contents
are still described by `items`.

Initial package kinds:

- `worker`
- `worker-group`
- `worksheet`
- `ticket`
- `ticket-bundle`
- `project-template`
- `project-snapshot`
- `mixed`

The package kind is not a security boundary, and it is not a carrier-level type
system. Import code MUST inspect every item and apply the relevant validations
and approvals.

Current baseline support is deliberately strict: worker and ticket packages
must include classifiable item hints such as `bullpen_type`, and any declared
`bullpen.kind` must match the inferred item kind exactly. Packages without
classifiable item hints, mismatched declared kinds, or unsupported/mixed item
sets preview/import as unsupported until path/field-based classification is
implemented deliberately.

## Bullpen Profile Contracts

The Bullpen profile is intentionally loose. Bullpen objects are user-facing
configuration, not an interchange standard that should reject useful human
material because a field is unexpected, renamed, or slightly ambiguous.

The profile contract is:

- Objects are ordinary JSON.
- Objects are classified by their item path, manifest item hints, and
  recognizable fields.
- Unknown inert fields are preserved when possible.
- Unknown effectful fields are rejected or neutralized unless a specific import
  approval covers them.
- Objects that cannot be classified safely are rejected for import but may still
  appear in preview as unsupported items.
- Relationships are best-effort and name-oriented unless the relationship is
  explicitly local to the package.

Loose name-based binding is required. Bullpen already lets users route work
through names and human labels, for example `worker:Reviewer`, `random:QA`, and
column dispositions such as `review`. Package import must preserve that style
because the user model is human: names are meaningful, ambiguous, renamed,
misspelled, and still often the best available binding.

Binding rules:

- Preserve `worker:NAME`, `random:NAME`, `pass:DIRECTION`, and bare column
  dispositions as authored.
- In preview, resolve names against package-local workers first, then existing
  workspace workers, and report ambiguity or misses as warnings.
- Do not treat ambiguous name resolution as a carrier error.
- If a relationship cannot be resolved confidently, import the object dormant
  and show the unresolved relationship in the import result.
- If import renames a worker due to a conflict, rewrite only package-local
  references that clearly point to that imported worker. Preserve ambiguous
  external references as written and warn.
- Preserve original local IDs only as source metadata. Generate destination IDs
  for imported tickets and other workspace-owned objects.

## Container Layout

Example:

```json
{
  "format": "bento",
  "version": "1",
  "profiles": [
    {
      "id": "org.bullpen.share",
      "version": "1",
      "label": "Bullpen Share"
    }
  ],
  "items": [
    {
      "id": "worker.builder",
      "media_type": "application/json",
      "path": "payload/workers/builder.json",
      "label": "Builder"
    },
    {
      "id": "profile.custom-builder",
      "media_type": "application/json",
      "path": "payload/profiles/custom-builder.json",
      "label": "Custom Builder"
    }
  ],
  "attributes": [
    {
      "label": "preview",
      "namespace": "org.bullpen.preview",
      "name": "preview",
      "version": "1",
      "merge": "replace",
      "data": {
        "badges": ["worker-group"]
      }
    }
  ],
  "warnings": [
    {
      "code": "contains-command-worker",
      "message": "This package contains command-based workers."
    }
  ]
}
```

Recommended internal paths for the Bullpen profile:

- `payload/workers/*.json`
- `payload/profiles/*.json`
- `payload/tickets/*.json`
- `payload/worksheets/*.json`
- `payload/values/*.json`
- `assets/*`
- `metadata/*`

Each internal object should be ordinary JSON with enough recognizable fields for
Bullpen to preview and place it. Bento must not require exact object models.
Bullpen profile handling should use the loose contracts above: preserve unknown
inert fields, inspect effectful fields, and reject only when Bullpen cannot
safely classify the object. Avoid embedding host paths, runtime tokens, process
state, or logs unless a diagnostic export profile explicitly requires that data
and the user has approved that inclusion.

Carrier-level import MUST enforce local path rules, duplicate normalized path
rejection, special-file rejection, ZIP bomb limits, manifest parsing, and safe
preview-before-apply discipline before any Bullpen profile semantics are applied.

## Relationship to Current Exports

Map existing archive exports onto Bullpen profile kinds:

- Current workspace export -> `project-snapshot`
- Current workers export -> `worker-group` or `mixed`
- Current single-worker export -> `worker`
- Current all-workspaces export -> advanced maintenance archive, not a primary
  profile kind

The all-workspaces export should remain available for migration and support, but
it should be visually demoted from the main sharing flow. It is closer to an
admin operation than to a share artifact.

## Import UX

Import must be preview-first.

Import flow:

1. User selects a `.bento` file or legacy Bullpen archive.
2. Server validates zip structure, size, entry count, paths, and manifest.
3. Server builds a safe preview from carrier metadata and supported Bullpen
   profile semantics.
4. UI shows a preview:
   - Bullpen profile kind, if present
   - item counts by type
   - names of workers, tickets, worksheets, and profiles
   - command/service/notification capabilities
   - conflicts and suggested resolutions
5. User chooses an import mode.
6. User explicitly approves risky capabilities.
7. Server imports using a transaction-like plan.
8. UI reports added, skipped, renamed, and rejected items.

Import modes:

- Add only: never overwrite existing objects.
- Merge: add new objects and rename conflicting ones.
- Replace selected: overwrite only objects explicitly selected in preview.
- Template import: create objects but strip runtime state, assignments, history,
  and logs.

Placement policy:

- Preserve visual grid positions when all target cells are available.
- If any target position conflicts, pause and ask the user to choose a conflict
  resolution instead of silently shifting the imported objects.

No import should immediately start a worker, run a command, open a network
connection, send a notification, mutate git, or dispatch tickets to workers.
Import creates dormant objects unless the user takes a separate action after
import.

## Security and User Approval

Package import crosses a trust boundary. Treat every package as untrusted input,
even if it was created by Bullpen.

### Baseline Validation

The server must enforce:

- Zip magic/format validation.
- Maximum file count.
- Maximum uncompressed byte size.
- Maximum compression ratio.
- No nested archives by default.
- No absolute paths.
- No `..` path traversal.
- No empty member names after normalization.
- No duplicate member paths after slash normalization, dot-segment removal, and
  case-folding.
- No symlink extraction.
- No device files, FIFOs, sockets, or other special archive members.
- UTF-8 JSON decoding with clear errors.
- Carrier format/version validation.
- Manifest item paths must point to existing archive members.
- Manifest item paths must not point outside the validated archive member set.
- Unknown effectful Bullpen fields rejected or neutralized unless explicitly
  approved by the user.

The server should extract to a temporary directory, validate fully, and only
then apply an import plan to the workspace.

### Runtime State Stripping

Default package imports strip or ignore:

- `state`
- `started_at`
- `task_queue`
- `assigned_to`
- process IDs
- live output buffers
- MCP tokens
- server host/port
- workspace filesystem paths
- worktree paths
- run logs
- archived execution artifacts

Diagnostic exports may carry logs or artifacts later, but they should be a
separate Bullpen profile mode with explicit user warnings.

### Capability Warnings

The preview must call out items that can cause effects after import:

- Shell workers with `command`, `pre_start`, `env`, or non-default `cwd`.
- Service workers with startup commands, health checks, crash policy, or ports.
- AI workers configured for `auto_commit`, `auto_pr`, worktrees, or trusted
  execution.
- Notification workers configured for speech, desktop, webhook, or external
  delivery.
- Tickets with embedded instructions likely to affect workers.
- Package assets that may be written into the workspace.

Suggested warning groups:

- "Can execute local commands"
- "Can access network or external services"
- "Can modify git state"
- "Can send notifications or messages"
- "Contains ticket instructions"
- "Contains local file paths"
- "Contains environment variable names or values"

### Explicit Approval Gates

The user should be able to import safe metadata without approving execution
capabilities. Risky capabilities require targeted approval.

Examples:

- Import shell/service workers as disabled until user approves command
  capability.
- Import workers with `auto_commit` and `auto_pr` turned off unless user
  explicitly preserves them.
- Import notification workers with delivery channels disabled unless user
  approves notification capability.
- Import tickets into a human column, not `assigned` or `in_progress`.
- Import ticket bundles without assigning them to workers unless the user chooses
  a worker in the import flow.

Approval should be attached to the import operation, not stored as permanent
trust in the package. The next package import asks again.

### Sanitized Defaults

When in doubt, preserve useful structure and remove effectful behavior.

Default sanitization:

- Keep worker name, type, layout position, model choice, prompts, notes, value
  configuration, and profile references.
- Disable command execution fields or mark them pending approval.
- Keep ticket title, body, type, priority, tags, and custom metadata.
- Reset ticket status to a selected human column, defaulting to `backlog`.
- Clear worker assignment fields from tickets.
- Clear worker queues from workers.

## Optional Scanning Service

The architecture should allow an optional package scanning provider in a later
scanner phase. The first design target is a provider modeled on `cladis.ai`, but
the interface must support other providers.

This proposal does not require a scanner for the first package implementation.
Scanner support is a deferred plug-in point. Initial package security MUST rely
on carrier validation, bounded parsing, safe preview, sanitization, and explicit
approval, not on a scanner.

Scanner responsibilities:

- Inspect Bento manifest and extracted JSON objects.
- Flag secrets, credentials, tokens, private URLs, and local filesystem paths.
- Flag dangerous shell/service commands.
- Flag prompt-injection patterns in tickets, worker prompts, and notes.
- Flag suspicious assets or unsupported file types.
- Produce a machine-readable verdict and human-readable findings.

Provider-neutral interface:

```json
{
  "provider": "cladis",
  "provider_version": "unknown",
  "verdict": "pass | warn | block | error",
  "findings": [
    {
      "severity": "low | medium | high | critical",
      "code": "possible-secret",
      "item_id": "worker.deploy",
      "path": "workers/deploy.json",
      "message": "Command environment appears to contain a token-like value.",
      "recommendation": "Remove the value before sharing."
    }
  ],
  "sanitized_package_path": null
}
```

Provider abstraction:

```python
class PackageScanner:
    provider_id: str

    def scan(self, extracted_dir: str, manifest: dict) -> "ScanResult":
        """Return findings and optional sanitized output."""
```

Configuration:

- Scanner disabled by default.
- Provider selected by config, for example `package_scanner.provider`.
- Provider-specific API keys stored outside package files and outside exported
  workspace data.
- Network scanner use must be disclosed in UI because Bento content may be
  sent to a third party.

Cladis-style provider placeholder:

- Provider id: `cladis`
- Expected model: upload or submit package contents to a scanning API, receive
  structured findings and optional sanitized output.
- Bullpen should not hard-code Cladis concepts into the Bento carrier. It should
  only depend on the generic scanner result contract.

Scanner verdicts, block behavior, object lockout, and edit-and-rescan
remediation are intentionally deferred. Initial import safety should rely on
local validation, preview, sanitization, and explicit approval gates.

## Copy/Paste Semantics Across Internal Objects

The package format and internal copy/paste should converge on the same object
model, even when the transport differs.

Today:

- Worker copy/paste uses an in-memory payload containing workers and relative
  offsets.
- Worker drag/drop uses browser data transfer payloads for slots/groups.
- Worksheet paste accepts clipboard table text and creates value workers.
- Tickets are copied or moved mostly through board interactions, not a durable
  clipboard payload.

Proposed direction:

- Internal copy/paste payloads should be "package fragments": the same item JSON
  and relationship model used by the Bullpen package format, without requiring a
  zip container.
- Durable package export is the file transport.
- Clipboard copy is the local ephemeral transport.
- Drag/drop is the pointer-driven ephemeral transport.

This gives one import planner for all object movement:

- Paste worker group.
- Paste worksheet cells as value workers.
- Paste ticket bundle.
- Import package from disk.
- Later, receive package from social/share link.

### Worker Clipboard

Worker clipboard payloads should include:

- Workers.
- Relative grid offsets.
- Referenced profiles.
- Relationships such as pass connections and `worker:NAME` disposition
  references.
- Optional value-worker dependencies referenced by placeholders.

On paste, use the same conflict planner as package import:

- occupied cells
- duplicate names
- missing profiles
- unsafe command fields
- disabled capabilities

### Ticket Clipboard

Tickets should become first-class shareable objects.

Ticket copy/paste payloads should include:

- Ticket title, body, type, priority, tags, custom metadata.
- Optional related tickets.
- Optional attached artifacts, if attachments become first-class.
- Optional worker assignment only as metadata, not as an active queue
  relationship.

Default paste/import behavior:

- Paste tickets into a human column selected by the user, defaulting to the
  current column or `backlog`.
- Clear `assigned_to`.
- Do not paste into `assigned` or `in_progress`.
- Do not enqueue pasted tickets on workers unless the user explicitly chooses
  "paste and assign."
- Preserve original IDs only as `source_id`; generate new local IDs.
- Preserve source status only as metadata unless the destination workspace has a
  matching human column and the user chooses to keep statuses.

Ticket bundles should support common sharing flows:

- "Here are the tickets for this mini-project."
- "Here is a repro ticket plus the worker that can process it."
- "Here is a template set of tasks for onboarding."

### Worksheet Clipboard

Worksheet copy/paste should also fit the fragment model.

Text/TSV paste remains useful because it interoperates with spreadsheets. But
Bullpen-origin worksheet copy should be richer:

- cell coordinates or relative offsets
- value worker configs
- value types and formatting
- formulas or references if added later
- history only when explicitly included

Default share behavior should exclude value history unless the user requests it.
Value history CSV remains a separate reporting/export feature, not the main
sharing format.

## Legacy Compatibility

Support a migration period:

- Continue accepting current `.zip` workspace archives.
- Export new packages from the primary sharing UI.
- Keep old workspace and all-workspace archive behavior available through
  Socket.IO during the migration period.
- Remove the legacy worker zip REST routes as part of the Socket.IO Bento worker
  remediation:
  - `/api/export/workers`
  - `/api/export/worker`
  - `/api/import/workers`
- Add manifest detection so import can route:
  - `bento.json` -> Bento importer
  - `bullpen-export.json` -> legacy all-workspaces importer
  - `.bullpen/` or `config.json` -> legacy workspace importer

## Implementation Slices

Keep the first delivery small enough to prove the format and import model before
expanding to every share surface.

### Slice 0: Carrier Foundation

Status: Implemented.

- Implement Bento detection for uploaded zip-like files.
- Implement local carrier validation:
  - archive limits
  - normalized path uniqueness
  - special-file rejection
  - JSON manifest parse and version checks
  - item path existence checks
- Return a carrier-only preview for unsupported or non-Bullpen Bento files.
- Keep all legacy zip imports and exports operational.

Exit criteria:

- Unsafe archives are rejected before profile handling.
- Unknown-but-valid Bento files preview as unsupported rather than crashing.
- Legacy workspace, workers, and all-workspaces imports still pass existing
  tests.

### Slice 1: Worker Package MVP

Status: Implemented baseline.

- Implement `.bento` export for one worker and selected worker groups.
- Route primary worker-card and worker-group export actions through Socket.IO
  `.bento` export. Legacy worker zip REST routes have been removed.
- Include referenced profiles.
- Represent worker relationships using current Bullpen language:
  `worker:NAME`, `random:NAME`, `pass:DIRECTION`, and bare column dispositions.
- Implement worker package preview:
  - worker names and types
  - referenced profiles
  - grid positions
  - unresolved or ambiguous name bindings
  - command/service/notification/git capability warnings
  - placement conflicts
- Implement worker package import in add/merge mode only.

Exit criteria:

- A single worker can round-trip through `.bento`.
- A pass-connected worker group can round-trip with relative positions intact.
- Conflicting placement produces a preview choice instead of silent movement.
- Imported workers are dormant and have runtime state stripped.

Current baseline: package import preserves placement when preview reports all
target cells are available. When preview reports a conflict, the import review
modal lets the user choose `place-right`, `place-below`, or an explicit
`choose-anchor` coordinate for `bento:import`.

### Slice 2: Approval Gates

Status: Implemented modal baseline; placement visualization polish remains.

- Add import apply options for risky capability preservation.
- Default to sanitizing command, service, notification, git, queue, assignment,
  and runtime fields.
- Show targeted approval controls for each risky capability group.
- Apply approvals only to the current import operation.

Current baseline: the shared package import action performs preview first and
shows per-import approval controls before preserving command, environment,
service, notification, or git automation fields. Declined capabilities are
imported stripped through the existing backend sanitizer. Runtime state and
queues remain non-preservable.

Exit criteria:

- Safe worker metadata can import without approving effectful behavior.
- Preserving command/service/notification/git behavior requires explicit
  approval in the import flow.
- Import result reports preserved, sanitized, skipped, renamed, and rejected
  fields/items.

### Slice 3: Tickets

Status: Implemented baseline.

- Implement `.bento` export for one ticket and ticket bundles over Socket.IO.
- Generate new local ticket IDs on import.
- Preserve original IDs only as source metadata.
- Default imported tickets to a selected human column, initially `backlog`.
- Clear `assigned_to`, queue relationships, and active statuses by default.

Current baseline: ticket package import offers a target column from the
workspace's configured dormant columns in the import review modal. `assigned`,
`in_progress`, and `in-progress` are excluded, and the backend still normalizes
active target statuses to `backlog` if a client sends one.

Exit criteria:

- Ticket bundles can import without assigning work to a worker.
- Ticket package preview shows titles, priorities, tags, source statuses, and
  instruction/risk warnings.

### Slice 4: Internal Fragments

Status: Partially implemented for server-side worker/ticket fragment helpers;
frontend clipboard convergence remains deferred.

- Adapt worker copy/paste to the same package-fragment object model used by
  `.bento`, without requiring a zip carrier.
- Start with the server-side paste/apply helper so existing frontend clipboard
  payloads can continue working while worker paste and Bento import share
  conflict, rename, and local binding behavior.
- Add ticket copy/paste fragments after ticket package import is proven.
- Start ticket fragments as server-side `task:paste` and `task:paste_group`
  events that reuse the safe ticket import helper, generate new local IDs, clear
  assignment, and avoid worker queue dispatch.
- Keep worksheet TSV paste as-is while reserving richer worksheet fragments for
  later.

Exit criteria:

- Worker paste and worker package import share the same conflict and capability
  planner.
- Ticket paste and ticket package import share ID/status/assignment handling.

Suggested initial package Socket.IO events:

- `bento:preview`
- `bento:import`
- `bento:export` with `kind=worker` and `slot`
- `bento:export` with `kind=worker-group` and `slots`
- `bento:export` with `kind=ticket` and `id`
- `bento:export` with `kind=ticket-bundle` and `ids`

The event names are illustrative. The key architectural point is that import
preview and import apply are separate Socket.IO operations.

Current baseline: Bento preview, import, and export requests carry a
client-generated `request_id`; success and error events echo it so concurrent
package operations can ignore unrelated replies.

## Aft: Deferred Work

The following work should be kept out of the first package implementation unless
it becomes necessary to complete the worker package MVP cleanly.

### Scanner Remediation and Rescan

Scanner providers, scanner findings, object lockout, remediation, and rescan are
deferred out of the initial package work. If local preview and explicit approval
are sufficient, some of this work may never be needed.

Potential scanner-phase workflow:

- Open a locked worker/ticket/package item from the import result.
- Show scanner findings inline against editable fields.
- Allow the user to edit or remove risky fields.
- Rescan the edited object or package fragment.
- Unlock only when the relevant finding is resolved and scanner status passes
  or drops below the configured lock threshold.
- Keep a local audit trail of the original finding, user edit, scanner provider,
  and final unlock result.

This workflow is deeper than import preview. It should be designed alongside
worker configuration UX rather than squeezed into the initial package importer.

### Social Sharing

Later work can layer social distribution on top of Bullpen packages. This is
deferred and should not influence the initial package format beyond requiring
portable metadata and safe preview.

Possible later features:

- Share package as a link.
- Generate a package preview card with title, summary, object counts, and safety
  badges.
- Publish to a Bullpen package gallery.
- Import from a URL with the same scanner and approval flow as file import.
- Social metadata fields in the manifest, such as summary, author display name,
  preview image, tags, and license.

Security posture for URL/social import should be stricter than local file
import:

- Never auto-import from a link.
- Always preview first.
- After the scanner phase exists, scan when a scanner is configured and the user
  has authorized any required content transfer.
- Show origin URL and publisher metadata.
- Treat publisher metadata as untrusted display text.

Social sharing should be treated as distribution and discovery. Initial package
work should solve the package, preview, conflict, and approval model first.

## Open Questions

- Should ticket package import eventually use a richer picker tied to the
  currently visible board column, or keep the explicit dormant-column prompt?
- Should command-based workers import as disabled, or import enabled with
  command execution requiring approval only when first run?
- What is the minimum app/version metadata needed for compatibility warnings?
