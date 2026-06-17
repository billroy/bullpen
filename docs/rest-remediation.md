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

These now use Socket.IO:

- `bento:export`
- `bento:import`
- `worker:transfer`

## Current Main-App REST Surface

### Archive Transport

- `/api/export/workspace`
- `/api/export/all`
- `/api/import/workspace`
- `/api/import/all`

Assessment:

- These are file transport endpoints, not ordinary app commands.
- They remain suspect because import mutates workspace state and export can leak
  workspace content.
- They should be migrated or contained behind an explicit maintenance/admin
  affordance.

Remediation:

1. Prefer Socket.IO for preview/apply semantics.
2. Keep HTTP download/upload only if browser file mechanics make it materially
   better than Socket.IO binary payloads.
3. If retained, move out of primary sharing UI and document as maintenance
   transport with CSRF/origin checks.

### Files

- `/api/files`
- `/api/files/<path>`
- `PUT /api/files/<path>`

Assessment:

- Current file browsing/editing is a main app feature, so this is architectural
  REST creep.
- `PUT /api/files/<path>` is high-risk because it writes workspace files.

Remediation:

1. Add Socket.IO file events for tree/list, read, and write.
2. Preserve existing path traversal and size checks in the event path.
3. Remove HTTP file routes after `FilesTab` is migrated.

Candidate events:

- `files:list`
- `files:read`
- `files:write`
- `files:written`
- `files:error`

### Commits

- `/api/commits`
- `/api/commits/<commit_hash>/diff`

Assessment:

- Commit browsing is app state/query behavior and belongs on Socket.IO.
- It also shells out to git, so event responses should retain timeout and
  validation behavior.

Remediation:

1. Add Socket.IO commit list and diff events.
2. Migrate `CommitsTab`.
3. Remove HTTP commit routes.

Candidate events:

- `commits:list`
- `commits:listed`
- `commits:diff`
- `commits:diffed`
- `commits:error`

### Model Lookup

- `/api/models/opencode`

Assessment:

- This is not a durable external API; it is UI support for worker/chat model
  pickers.
- It should become a Socket.IO query event.

Remediation:

1. Add `models:opencode` Socket.IO request handling.
2. Migrate `WorkerConfigModal` and `LiveAgentChatTab`.
3. Remove the HTTP route.

### Service Preview

- `POST /api/service/preview`

Assessment:

- This is an app command/query used by the worker configuration UI.
- It already depends on workspace state and selected worker slot, so Socket.IO
  is the natural transport.

Remediation:

1. Add `service:preview` Socket.IO handling.
2. Migrate `WorkerConfigModal`.
3. Remove the HTTP route.

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

1. Remove low-risk UI support routes with clear socket replacements:
   - `service:preview`
   - `models:opencode`
2. Remove app query routes:
   - commits list/diff
   - file list/read
3. Remove or contain app mutation/file transport:
   - file write
   - workspace/all import
   - workspace/all export
4. Audit and remediate manager/admin REST.

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
