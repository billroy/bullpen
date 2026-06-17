# REST Remediation

Status: Active remediation plan

## Position

Bullpen is a Socket.IO application. Browser-visible application behavior should
default to Socket.IO events, not REST endpoints. REST routes are not free
integration points; each one must either be justified as a document/file
transport boundary that Socket.IO cannot reasonably replace, or removed.

The goal is not to rename HTTP routes into different HTTP routes. The goal is to
move application commands and state queries onto authenticated Socket.IO events,
leaving only narrowly justified HTTP surfaces.

## Already Removed

- Legacy worker zip exports/imports:
  - `/api/export/workers`
  - `/api/export/worker`
  - `/api/import/workers`
- Cross-workspace worker transfer:
  - `/api/worker/transfer`
  - `/api/worker/transfer_group`
- Service worker preview:
  - `/api/service/preview`
- OpenCode model lookup:
  - `/api/models/opencode`
- Commit browsing:
  - `/api/commits`
  - `/api/commits/<commit_hash>/diff`
- File tree/read/write app behavior:
  - `/api/files`
  - text `GET /api/files/<path>`
  - `PUT /api/files/<path>`
- Workspace/all archive transport:
  - `/api/export/workspace`
  - `/api/export/all`
  - `/api/import/workspace`
  - `/api/import/all`

These now use Socket.IO:

- `bento:export`
- `bento:import`
- `worker:transfer`
- `service:preview`
- `models:opencode`
- `commits:list`
- `commits:diff`
- `files:list`
- `files:read`
- `files:exists`
- `files:write`
- `archive:export`
- `archive:import`

## Current Main-App REST Surface

### Files

- raw/download/media `GET /api/files/<path>?raw=1`
- image/PDF media `GET /api/files/<path>`

Assessment:

- File browsing/editing is now Socket.IO app behavior.
- The remaining HTTP path is a browser file transport for downloads, PDF/embed,
  image preview, and raw HTML attachment handling.
- This route remains suspect and should be revisited, but it is not an app state
  query or mutation endpoint.

Remediation:

1. Keep raw/media HTTP route isolated from JSON app behavior.
2. Preserve path traversal checks and HTML-as-attachment behavior.
3. Decide later whether downloads/media previews should move to blob URLs fed by
   Socket.IO binary payloads.

## Manager/Admin REST Surface

`server/manager.py` has a separate admin/management UI with these REST routes:

- `/api/profiles`
- `/api/profiles/<profile_id>`
- `/api/profiles/<profile_id>/<action>`
- `/api/profiles/<profile_id>/setup-providers/start`
- `/api/profiles/<profile_id>/setup-providers/session`
- `/api/profiles/<profile_id>/logs`
- `/api/microsandbox/base-snapshots`
- `/api/microsandbox/base-snapshots/rebuild`
- `/api/microsandbox/base-snapshots/rebuild/logs`
- `/api/ports`

Assessment:

- These are still REST, but they are not the main Socket.IO board surface.
- They require their own pass because the manager app may not share the same
  Socket.IO lifecycle as the board.

Remediation:

1. Inventory whether the manager UI has or should have a Socket.IO connection.
2. Move profile and microsandbox actions to manager Socket.IO events if the UI
   is live and session-bound.
3. If any manager REST route remains, document the reason and harden it with
   CSRF/origin checks.

## Order Of Operations

1. Remove or contain app mutation/file transport:
   - workspace/all import
   - workspace/all export
   - raw file download/media transport
2. Audit and remediate manager/admin REST.

## Acceptance Criteria

For each route removed:

- Frontend no longer calls the HTTP path.
- Flask URL map no longer includes the route.
- Tests assert the route is absent or the frontend does not reference it.
- Socket.IO event tests cover the replacement behavior.
- Docs/security notes are updated so stale REST references do not imply
  support.

For each route retained:

- The document names the route.
- The document explains why Socket.IO is not the preferred transport.
- The route has explicit auth, CSRF/origin protection when browser-callable,
  resource limits, and tests.
