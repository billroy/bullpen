# Bento Carrier Foundation Spike

Status: Implemented baseline

## Readiness

Implemented as a bounded carrier foundation in `server/bento_carrier.py`, with
Socket.IO preview support in `server/events.py` and focused tests in
`tests/test_bento_carrier.py`.

The first implementation also moved beyond the carrier-only slice to support
Bullpen worker, worker-group, ticket, and ticket-bundle packages. Clipboard,
worksheet, scanner, social, project-template, and project-snapshot semantics
remain outside this baseline.

## Proposed Module Boundary

`server/bento_carrier.py` owns carrier inspection.

Responsibilities:

- Open uploaded zip-like files.
- Detect root `bento.json`.
- Validate member paths and resource limits.
- Parse `bento.json` as UTF-8 JSON.
- Validate the carrier envelope:
  - `format == "bento"`
  - `version == "1"`
  - `profiles` is a list when present
  - `items` is a list when present
  - `attributes` is a list when present
- Validate manifest item `path` references against archive members.
- Return a preview-safe carrier summary.
- Optionally extract to a temporary directory only after validation succeeds.

Non-responsibilities:

- Worker semantics.
- Ticket semantics.
- Capability approval.
- Applying objects to `.bullpen`.
- Running scanners.
- Trusting or executing attribute bundles.

## Carrier API Sketch

The first implementation can keep the API deliberately small:

```python
class BentoCarrierError(ValueError):
    code: str
    message: str


def inspect_bento(fileobj, *, limits=None) -> dict:
    """Validate a Bento carrier and return a preview-safe summary."""
```

Preview summary shape:

```json
{
  "ok": true,
  "format": "bento",
  "version": "1",
  "profiles": [
    {"id": "org.bullpen.share", "version": "1", "label": "Bullpen Share"}
  ],
  "items": [
    {
      "id": "worker.builder",
      "label": "Builder",
      "media_type": "application/json",
      "path": "payload/workers/builder.json"
    }
  ],
  "attributes": [],
  "supported_profiles": [],
  "unsupported_profiles": ["org.example.other"],
  "warnings": []
}
```

Error shape for Socket.IO result events:

```json
{
  "ok": false,
  "error": "Archive contains duplicate normalized paths",
  "code": "duplicate-path"
}
```

## Socket.IO Event Shape

Implemented events:

- `bento:preview`
- `bento:export`
- `bento:import`

Behavior:

- Uses the existing authenticated Socket.IO session.
- Accepts package bytes in `file` or `data`.
- `bento:preview` does not apply or extract into workspace state.
- Emits `bento:previewed` with carrier-only preview for valid Bento files.
- Emits `bento:error` with a stable error code for invalid archives.
- Emits unsupported profile information without treating unsupported profiles as
  trusted.
- `bento:import` validates the carrier before reading package semantics or
  mutating workspace state.
- Bullpen packages route by declared `bullpen.kind` when present, and by
  manifest item hints when kind is absent.

## Legacy Routing

The carrier spike originally left existing endpoints unchanged so the first
slice could focus only on package inspection. That was a temporary spike
boundary, not a long-term architecture decision. After the Socket.IO Bento
worker export/import path was wired through the UI, the legacy worker zip REST
routes were removed:

- `/api/import/workers`
- `/api/export/workers`
- `/api/export/worker`

Workspace and all-workspace zip behavior also moved to Socket.IO during REST
remediation. The former routes were:

- `/api/import/workspace`
- `/api/import/all`
- `/api/export/workspace`
- `/api/export/all`

A future unified import event may route by manifest presence:

- `bento.json` -> Bento preview/import path
- `bullpen-export.json` -> legacy all-workspaces importer
- `.bullpen/` or `config.json` -> legacy workspace importer

That unified router is not required for the carrier spike.

## Limits

Use the current legacy defaults as compatibility inputs but do not expose them
as the final Bento defaults without review:

- `_MAX_IMPORT_ARCHIVE_BYTES = 200 MiB`
- `_MAX_IMPORT_ARCHIVE_FILES = 1000`
- `_MAX_IMPORT_COMPRESSION_RATIO = 100`

For Bento preview, consider stricter defaults:

- total entries: 256
- total uncompressed bytes: 25 MiB
- single member bytes: 5 MiB
- `bento.json` bytes: 512 KiB
- single JSON payload bytes: 2 MiB

The spike decision is whether to start strict for Bento while leaving legacy
imports at current limits.

## Test Matrix

Create `tests/test_bento_carrier.py`.

Happy path:

- Valid minimal Bento previews successfully.
- Valid Bento with profiles/items/attributes previews successfully.
- Valid non-Bullpen Bento previews as unsupported.
- Item `path` references an existing payload member.

Archive rejection:

- Invalid zip file.
- Missing `bento.json`.
- `bento.json` is not UTF-8 JSON.
- `bento.json` root is not an object.
- Unsupported carrier version.
- Too many files.
- Total uncompressed bytes too large.
- Per-member compression ratio too high.
- Total compression ratio too high.
- Nested archive member.
- Absolute path.
- `..` traversal.
- Empty normalized path.
- Duplicate normalized path.
- Windows drive prefix.
- NUL byte in name if the ZIP reader exposes one.
- Symlink or special-file member.
- Encrypted member if detectable.

Manifest rejection:

- `items` is not a list.
- Item descriptor is not an object.
- Item `path` is not a string.
- Item `path` points to a missing member.
- Item `path` points to a directory.
- Attribute `path` points to a missing member.
- Attribute `path` points to non-JSON when loaded for preview.

Event behavior:

- `bento:preview` rejects missing upload.
- `bento:preview` never mutates `.bullpen`.
- Unsupported Bento emits a successful preview with unsupported profile data,
  not a crash.
- Legacy import/export tests still pass.

## Closed Decisions

- Preview is stateless.
- `inspect_bento` validates from `ZipFile`; it does not extract.
- Bento preview uses stricter defaults than legacy ZIP import/export.
- Unsupported profiles are successful carrier previews, not errors.

## Implementation Tickets

Completed:

1. Add `server/bento_carrier.py` with carrier inspection and typed errors.
2. Add focused carrier unit tests in `tests/test_bento_carrier.py`.
3. Add `bento:preview` using the carrier inspector.
4. Add Socket.IO tests proving preview does not mutate workspace state.
5. Run existing legacy import/export tests to verify no regression.

Follow-up now belongs in narrower worker/ticket/package UX tickets rather than
this carrier spike.
