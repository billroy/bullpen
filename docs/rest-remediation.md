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
- Raw file download/media transport:
  - raw/download/media `GET /api/files/<path>?raw=1`
  - image/PDF media `GET /api/files/<path>`
- Workspace/all archive transport:
  - `/api/export/workspace`
  - `/api/export/all`
  - `/api/import/workspace`
  - `/api/import/all`
- Manager/admin read/query routes:
  - `GET /api/profiles`
  - `/api/profiles/<profile_id>/setup-providers/session`
  - `/api/profiles/<profile_id>/logs`
  - `/api/microsandbox/base-snapshots`
  - `/api/microsandbox/base-snapshots/rebuild/logs`
  - `/api/ports`

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
- `files:binary`
- `archive:export`
- `archive:import`
- `manager:profiles`
- `manager:setup-session`
- `manager:profile-logs`
- `manager:base-snapshots`
- `manager:base-rebuild-logs`
- `manager:ports`

## Current Main-App REST Surface

None currently identified.

## Manager/Admin REST Surface

`server/manager.py` has a separate admin/management UI with these REST routes:

- `POST /api/profiles`
- `DELETE /api/profiles/<profile_id>`
- `/api/profiles/<profile_id>/<action>`
- `/api/profiles/<profile_id>/setup-providers/start`
- `/api/microsandbox/base-snapshots/rebuild`

Assessment:

- These are mutating manager/admin actions.
- The manager UI already has a Socket.IO lifecycle for live profile updates and
  PTY traffic, so the remaining mutations should move to request/response
  manager Socket.IO events.

Remediation:

1. Move profile create/delete/start/stop/restart/open to manager Socket.IO.
2. Move provider setup start to manager Socket.IO.
3. Move base snapshot rebuild start to manager Socket.IO.
4. If any manager REST route remains, document the reason and harden it with
   CSRF/origin checks.

## Order Of Operations

1. Remove or contain app mutation/file transport:
   - workspace/all import
   - workspace/all export
   - raw file download/media transport
2. Remove manager/admin mutation REST.

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
