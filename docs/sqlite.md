# SQLite Persistence Analysis

## Executive Summary

Bullpen's current persistence is a set of workspace-local files under `.bullpen/`: markdown tickets with custom frontmatter, JSON blobs for config/layout/profiles/teams, markdown prompt files, and text logs. Moving this to SQLite is a good fit because the application already wants a single local, embedded, transactional store, but it should not become a fully normalized relational system. The best design is a hybrid: use SQLite for atomicity, indexing, and coherent state transitions, while keeping tickets and worker definitions mostly as JSON plus markdown text.

The recommended target is one database per workspace at `.bullpen/bullpen.sqlite`. Tasks should become rows with stable identity and a loose `meta` JSON document, plus a `body` text column. Only high-traffic fields such as `status`, `priority`, `order`, `assigned_to`, `created_at`, `updated_at`, and archive state need generated columns or indexes. This preserves the "barely typed" ticket model while eliminating fragile whole-file scans, custom frontmatter parsing as the active storage layer, and multi-file consistency problems.

## Current Persistence Shape

The active workspace state is stored under each project's `.bullpen/` directory.

| Area | Current storage | Main code paths | Notes |
| --- | --- | --- | --- |
| Tasks | `.bullpen/tasks/{slug}.md` with frontmatter and markdown body | `server/tasks.py`, `server/app.py`, `server/workers.py`, `server/mcp_tools.py` | Primary domain object. Frontmatter parser is custom and intentionally permissive. Archived tasks move to `.bullpen/tasks/archive/`. |
| Config | `.bullpen/config.json` | `server/init.py`, `server/app.py`, `server/events.py`, agent adapters, MCP token reader | Includes user config and transient per-run fields such as `server_host`, `server_port`, and `mcp_token`. |
| Layout/workers | `.bullpen/layout.json` | `server/events.py`, `server/workers.py`, `server/scheduler.py`, `server/app.py` | Stores worker configuration and runtime state in the same JSON document. Queue mutations and worker state updates are frequent. |
| Profiles | `.bullpen/profiles/{id}.json` copied from repo `profiles/` | `server/profiles.py`, init/tests | Built-ins are copied into each workspace; user-created profiles are stored the same way. |
| Teams | `.bullpen/teams/{name}.json` | `server/teams.py` | Saved layout snapshots with runtime fields stripped. |
| Prompts | `.bullpen/workspace_prompt.md`, `.bullpen/bullpen_prompt.md` | `server/events.py`, `server/workers.py`, init | Plain text included in agent prompts. |
| Logs | `.bullpen/logs/slot-*.log` | `server/workers.py` | Append-like invocation records, capped by deleting old files per slot. |
| Global project registry | `~/.bullpen/projects.json` | `server/workspace_manager.py` | Cross-workspace registry, not workspace-local. |

The backend serializes most writes with `server.locks.write_lock`, so the code already assumes a single-writer critical section. SQLite can replace this coarse file-level coordination with transactions gradually, but the first migration can keep the lock to reduce behavioral risk.

## Why SQLite Helps

SQLite improves the current design in five concrete ways.

1. Atomic multi-object changes: assigning a task currently updates a ticket file and `layout.json` separately. SQLite can update task status, assignment, worker queue, and worker state in one transaction.

2. Faster and safer task queries: `list_tasks()` scans every active markdown file and parses frontmatter on each call. SQLite can query indexed task rows by status, assignment, archive state, priority, and order.

3. Simpler concurrency failure modes: whole-file read/modify/write is vulnerable to stale reads and partial multi-file state even with atomic individual writes. SQLite provides rollback, WAL, busy timeouts, and transactional integrity.

4. Better migration path for loose data: SQLite's JSON support lets Bullpen keep arbitrary task fields without forcing every extension into a schema migration.

5. Cleaner future features: audit trails, task history, live chat transcripts, output chunks, usage accounting, search, and worker queue inspection all become easier without inventing more file formats.

## Preserve Barely-Typed Tickets

Do not model tickets as a wide relational table. Tickets are deliberately extensible: tests already verify that beans-compatible files can omit Bullpen-specific fields, and runtime code adds fields such as `handoff_depth`, `tokens`, and `history` without a central model definition.

Recommended representation:

```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  meta TEXT NOT NULL CHECK (json_valid(meta)),
  body TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  created_at TEXT GENERATED ALWAYS AS (json_extract(meta, '$.created_at')) VIRTUAL,
  updated_at TEXT GENERATED ALWAYS AS (json_extract(meta, '$.updated_at')) VIRTUAL,
  status TEXT GENERATED ALWAYS AS (json_extract(meta, '$.status')) VIRTUAL,
  priority TEXT GENERATED ALWAYS AS (json_extract(meta, '$.priority')) VIRTUAL,
  assigned_to TEXT GENERATED ALWAYS AS (json_extract(meta, '$.assigned_to')) VIRTUAL,
  order_key TEXT GENERATED ALWAYS AS (json_extract(meta, '$.order')) VIRTUAL
);

CREATE INDEX tasks_active_status_order_idx
  ON tasks(archived_at, status, priority, order_key);

CREATE INDEX tasks_assigned_idx
  ON tasks(assigned_to)
  WHERE assigned_to IS NOT NULL AND assigned_to != '';
```

The task API should continue to return the same dictionaries it does today: `{**meta, "id": id, "body": body}`. `update_task()` should merge arbitrary validated fields into `meta`, treat `body` specially, refresh `updated_at`, and leave unknown fields alone.

This preserves the core loose shape while giving the app enough typed affordances for sorting, filtering, and worker assignment.

## Suggested Database Shape

Use a per-workspace database:

```text
.bullpen/
  bullpen.sqlite
  bullpen.sqlite-wal
  bullpen.sqlite-shm
```

Set `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, and a `busy_timeout`. Use one connection per operation or a small thread-local connection helper; avoid sharing a single connection freely across worker threads.

Suggested initial tables:

| Table | Shape | Purpose |
| --- | --- | --- |
| `schema_migrations` | `version`, `applied_at` | Idempotent migrations. |
| `kv` | `namespace`, `key`, `value_json` or `value_text` | Config, prompts, and small workspace settings. |
| `tasks` | `id`, `meta` JSON, `body`, `archived_at`, generated/indexed fields | Active and archived tickets. |
| `workers` | `slot INTEGER PRIMARY KEY`, `data` JSON | Worker slot config and runtime state. This replaces `layout.json` while preserving loose worker fields. |
| `worker_queue` | `slot`, `position`, `task_id` | Optional but recommended. Separates queue order from worker config and prevents stale queue blobs. |
| `profiles` | `id`, `data` JSON, `source` | Built-in copied profiles and custom workspace profiles. |
| `teams` | `name`, `layout` JSON, `created_at`, `updated_at` | Saved team snapshots. |
| `logs` | `id`, `slot`, `task_id`, `created_at`, `success`, `prompt_preview`, `output`, `error` | Optional first-pass replacement for `.bullpen/logs/`. Keep file logs for one tranche if desired. |

The most conservative first version can store layout as one JSON value in `kv` instead of splitting `workers` and `worker_queue`. However, worker queues are exactly where file persistence is currently most fragile, so moving queues into rows is worth doing early.

## Compatibility and Export

The largest product question is whether `.bullpen/tasks/*.md` remains a user-editable contract or becomes an import/export format.

Recommended stance:

- SQLite is the authoritative store once migration succeeds.
- Markdown/frontmatter remains a compatibility format, not the live store.
- Provide a one-time importer from existing files into SQLite.
- Provide an export command or debug endpoint that can recreate `.bullpen/tasks/*.md` for users who want git-friendly snapshots or beans interoperability.
- During a transition period, leave existing files in place and write `.bullpen/MIGRATED_TO_SQLITE` or similar to make authority clear.

Trying to keep live bidirectional sync between SQLite and editable markdown files would add conflict detection, timestamp races, and confusing source-of-truth behavior. It is possible, but it should not be part of the first database migration.

## Required Code Changes

### New Storage Layer

Add a small repository layer, likely `server/store.py` or `server/db.py`, that owns:

- Database path resolution from `bp_dir`.
- Connection creation and pragmas.
- Schema migrations.
- Transaction helper.
- JSON serialization/deserialization.
- Import from current file tree.

Keep the existing domain-facing modules (`tasks.py`, `profiles.py`, `teams.py`) as the public API where possible. Internals can swap from file I/O to database queries without forcing the UI or MCP layer to change immediately.

### Task Module

`server/tasks.py` needs the largest change:

- `create_task()` inserts a row into `tasks`.
- `_next_order_key()` queries `max(order_key)` rather than scanning files.
- `read_task()` selects by `id` and ignores archived rows by default.
- `update_task()` merges fields into `meta`, updates `body` separately, and refreshes `updated_at`.
- `delete_task()` deletes or tombstones a row.
- `archive_task()` sets `archived_at` instead of moving files.
- `archive_done_tasks()` can be one query plus updates.
- `list_tasks()` queries active rows sorted by the current priority weight and order key.

One subtle issue: current sorting uses a Python priority map before `order`, not status-first ordering. Preserve this exact behavior unless the UI intends status-local ordering.

### Layout and Worker State

`layout.json` is the second critical area. It mixes worker configuration, runtime state, queues, timestamps, pause state, and grid coordinates. Conversion options:

- Conservative: store the whole layout JSON in `kv(namespace='workspace', key='layout')`.
- Better: store one `workers` row per occupied slot and one `worker_queue` row per queued task.

The better option makes assignment, dequeue, worker start, worker stop, yanking, handoff, scheduler triggers, and reconciliation transactional. It also avoids writing the full layout blob for every queue mutation.

The API can still return the current `{"slots": [...]}` shape by materializing it from rows, so the frontend does not need to change initially.

### Config and Prompts

Move `config.json` to `kv` or a `config` singleton row. Split durable user config from per-run secrets:

- Durable: name, grid, columns, timeout, max prompt chars, auto behavior.
- Runtime-only: `server_host`, `server_port`, `mcp_token`.

Today the MCP token is written into `config.json` so a local MCP stdio process can connect. In SQLite, either keep a small runtime token file for MCP bootstrap or store the runtime token in SQLite and teach `server/mcp_tools.py` to read it from the database. A small token file may be simpler and avoids requiring the MCP process to initialize the full database layer just to connect.

Prompts can be stored as `kv` text rows. That is enough; they do not need their own tables.

### Profiles and Teams

Profiles and teams can remain barely typed JSON rows:

- `profiles(id PRIMARY KEY, data TEXT CHECK json_valid(data), source TEXT)`
- `teams(name PRIMARY KEY, layout TEXT CHECK json_valid(layout), updated_at TEXT)`

`init_workspace()` should seed built-in profiles into SQLite if missing, but not overwrite user-modified rows. Tests currently expect files to be copied, so those tests will need to move from file assertions to API/state assertions.

### Logs and Agent Output

Agent output is currently appended into the task body, while invocation logs are separate `.log` files. There are two viable paths:

- Minimal: keep appending output to `tasks.body` and keep logs as files for now.
- Better: introduce `task_outputs` or `agent_runs` rows and render/append into the markdown body for compatibility.

For the first migration, keep task body behavior unchanged so UI rendering and clear-output behavior stay stable. Logs can move later.

### App Loading and Events

`load_state()` should become a composition of repository reads: config, layout materialization, active tasks, profiles, teams. Socket event payloads can remain the same.

Event handlers should wrap multi-step mutations in database transactions, especially:

- Assign task to worker.
- Start worker.
- Stop/yank worker.
- Agent success/failure.
- Handoff/pass-to-direction.
- Scheduler firing and auto-task creation.
- Archive done tasks.
- Team load replacing layout.

The existing `write_lock` can remain around these operations at first. Once the transaction boundaries are reliable, some lock usage can be narrowed.

### MCP Tools

`server/mcp_tools.py` currently lists tickets by directly calling `task_store.list_tasks(bp_dir)`, while create/update go through Socket.IO for real-time updates. If `tasks.py` keeps its API, list behavior carries over automatically. The MCP token bootstrap does need attention if `config.json` disappears.

## Migration Strategy

Migration should be idempotent and local to each workspace.

1. On startup, call `init_workspace()` and then `open_or_initialize_database(bp_dir)`.
2. If `bullpen.sqlite` is missing, create schema and import existing files.
3. Import `config.json`, `layout.json`, prompts, profiles, teams, active tasks, archived tasks, and optionally logs.
4. Preserve task IDs from frontmatter slug or filename.
5. Store archive state for files under `tasks/archive/`.
6. Leave source files untouched after successful import.
7. Mark migration completion in `schema_migrations` and optionally a small sentinel file.

Handle malformed data leniently:

- If a task file has no frontmatter, import it with generated defaults and the whole file as body.
- If frontmatter is partially invalid, preserve parsed keys and fill missing required UI fields with defaults.
- If duplicate IDs are found, keep the first ID and suffix subsequent imports while recording an import warning.
- If `layout.json` references missing task IDs, keep the queue entry only if the UI already tolerates it, or drop it with an import warning. Current `start_worker()` already removes missing tasks from the front of a queue, so either behavior can be defended.

## Risks and Design Issues

### Loss of Git-Friendly State

The current file format is easy to inspect, diff, edit, and commit. SQLite is opaque in git and harder to manually repair. Export tooling and a clear support story are important.

### External Beans Compatibility

The spec explicitly calls tasks beans-compatible. SQLite as the live store weakens that unless import/export remains first-class. Bidirectional sync should be considered a later feature, not bundled into the initial migration.

### Runtime Secrets in Durable Config

The current design writes `mcp_token` into `config.json`. Moving to SQLite is a chance to separate durable settings from per-run secrets. This has security and cleanup benefits, but requires MCP bootstrap changes.

### Threading and Connection Scope

The app uses Flask-SocketIO threading mode, background scheduler threads, agent execution threads, and MCP Socket.IO clients. SQLite can handle this, but only with disciplined connection handling, WAL mode, busy timeouts, and short transactions. Do not share cursors or long-lived write transactions across subprocess waits.

### Transaction Boundaries Can Change Behavior

Some current flows rely on intermediate file states being visible after each step. Moving to larger transactions may delay emits until commit. That is usually correct, but tests should assert emitted payloads and final state rather than internal write timing.

### JSON Typing Edge Cases

SQLite JSON values distinguish numbers, strings, booleans, and null. The custom frontmatter parser has its own looser coercions. Migration must preserve Python-facing values closely enough that tests for tags, history, integers, empty strings, and missing fields continue to pass.

### Generated Columns Availability

SQLite versions bundled with Python are usually modern, but generated columns and JSON behavior depend on runtime SQLite. Add a startup compatibility check or avoid generated columns initially by maintaining ordinary indexed shadow columns from Python.

### Large Task Bodies and Output Growth

SQLite can store large text bodies, but constantly rewriting a large `body` field to append output is still inefficient. The first migration can preserve current behavior; a later tranche should split agent output/runs into their own table.

### Backups and Corruption Recovery

Atomic file writes are simple to reason about. SQLite needs explicit backup guidance: use the SQLite backup API or copy after checkpointing, not arbitrary copies of the main database while WAL files are active.

## Testing Changes

Add database-focused tests without throwing away current behavioral tests.

- Storage tests: schema creation, idempotent migrations, JSON round trips, transaction rollback, archive state, generated/indexed field behavior.
- Import tests: active tasks, archived tasks, beans-like missing fields, malformed/no-frontmatter task, config/layout/profiles/teams/prompts.
- Behavioral task tests: keep existing `create/read/update/delete/archive/list/clear_output` assertions with the new backend.
- Worker tests: assignment, queue order, start/stop, yanking, handoff, scheduler trigger, retry history, token accumulation.
- App/event tests: state initialization, emitted payloads, multi-workspace isolation.
- MCP tests: list/create/update still work and token bootstrap works after `config.json` is gone or reduced.

## Prioritized Work Plan

### Tranche 1: Storage Foundation

- Add `server/db.py` with connection, pragmas, transaction helper, and migrations.
- Create `.bullpen/bullpen.sqlite` during workspace initialization.
- Add `schema_migrations`, `kv`, `tasks`, `profiles`, and `teams`.
- Keep file storage as the production source while tests prove database helpers.
- Decide whether generated columns are available or use shadow columns for indexed task fields.

### Tranche 2: One-Time Import and Read Parity

- Import existing `.bullpen/` files into SQLite idempotently.
- Add read APIs that materialize the current config/layout/tasks/profiles/teams shapes from SQLite.
- Add import warnings/logging for duplicate or malformed records.
- Keep writing files for now or run in a read-from-DB/write-to-files compatibility mode only in tests.

### Tranche 3: Tasks Become Database-Backed

- Switch `server/tasks.py` to SQLite as the authoritative backend.
- Preserve task dict shape and loose field merging.
- Implement archive as row state.
- Update `load_state()` and MCP listing through existing task APIs.
- Keep optional markdown export/debug tooling so old task files can be recreated.

### Tranche 4: Workers, Layout, and Queues

- Replace `layout.json` with database-backed layout materialization.
- Prefer `workers` plus `worker_queue` over one layout blob.
- Wrap assignment/start/stop/yank/handoff/agent completion in transactions.
- Keep frontend payloads unchanged.
- Update scheduler and reconciliation to use the new worker repository APIs.

### Tranche 5: Config, Prompts, Profiles, Teams

- Move durable config and prompts to `kv`.
- Move profiles and teams to JSON rows.
- Split runtime server connection fields and MCP token from durable config.
- Update init/seeding behavior and tests that currently assert physical files.

### Tranche 6: Logs, Output, and Cleanup

- Decide whether invocation logs stay as files or become `agent_runs`.
- Consider splitting agent output from task body into structured rows while rendering compatible markdown for existing UI.
- Add export/import commands for markdown tickets and JSON snapshots.
- Remove obsolete file persistence helpers or keep them only for import/export.
- Document backup, migration, and recovery procedures.

## Recommended First Implementation Choice

Start with a repository layer that makes `tasks.py` database-backed while preserving the public Python API and Socket.IO payloads. That gives the highest value quickly: faster task listing, reliable archive state, and transactional ticket updates. Then move worker queues next, because that is where cross-object consistency matters most. Config, profiles, teams, prompts, and logs can follow with much lower risk.

The guiding principle should be: SQLite owns coherence; JSON owns shape. Use relational columns only for identity, relationships, indexes, and transaction boundaries. Let tickets remain mostly mysterious little documents, because the rest of Bullpen already expects them to be that flexible.
