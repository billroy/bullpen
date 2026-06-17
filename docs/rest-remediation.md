# REST Remediation

Status: Completed; guarded by `tests/test_rest_remediation.py`

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
- Manager/admin routes:
  - `GET /api/profiles`
  - `POST /api/profiles`
  - `DELETE /api/profiles/<profile_id>`
  - `/api/profiles/<profile_id>/<action>`
  - `/api/profiles/<profile_id>/setup-providers/session`
  - `/api/profiles/<profile_id>/logs`
  - `/api/microsandbox/base-snapshots`
  - `/api/microsandbox/base-snapshots/rebuild/logs`
  - `/api/ports`
  - `/api/profiles/<profile_id>/setup-providers/start`
  - `/api/microsandbox/base-snapshots/rebuild`

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
- `manager:profile-create`
- `manager:profile-delete`
- `manager:profile-action`
- `manager:setup-providers-start`
- `manager:base-rebuild-start`

## Current REST Surface

None currently identified in the main app or the manager/admin app.

Bullpen still has ordinary HTTP routes for pages, static assets, login/logout,
CSRF bootstrap, health checks, favicon handling, and vendor assets. Those are
not REST application endpoints. Browser-visible application commands and state
queries are expected to use Socket.IO events.

## Completion Notes

The manager UI already had a Socket.IO lifecycle for live profile updates and
PTY traffic. All identified manager/admin `/api/*` routes have now been moved
to Socket.IO.

`tests/test_rest_remediation.py` asserts that both Flask URL maps expose no
`/api/*` routes. Feature-specific tests also assert that removed routes return
404 or are absent from frontend source where appropriate.

## Ongoing Guardrails

1. Keep application behavior on request/response Socket.IO events.
2. Keep `tests/test_rest_remediation.py` green.
3. Before adding any new `/api/*` route, document why Socket.IO is unsuitable
   for that behavior and get explicit architecture approval.
4. Any approved browser-callable HTTP application route must have explicit
   authentication, CSRF/origin protection, resource limits, and tests.

## Regression Criteria

- The main app URL map contains no `/api/*` routes.
- The manager/admin URL map contains no `/api/*` routes.
- Frontend source does not call removed `/api/*` routes.
- Socket.IO event tests cover replacement behavior for removed routes.
- Docs that describe current supported behavior do not imply `/api/*` support.
