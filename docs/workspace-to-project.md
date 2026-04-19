# Workspace → Project Rename: Analysis & Remediation Plan

## Summary

Bullpen has been gradually migrating the internal concept "workspace" to "project". The migration is partial: the codebase already exposes `project:join`, `project_menu`, `test_frontend_project_name_visibility.py`, and `docs/cross-project-fixup.md`, but ~1,400 occurrences of "workspace" (case-insensitive) remain across 114 files. This document is the remediation plan for the cleanup pass.

`docs/cross-project-fixup.md` contains the prior migration context (72 occurrences) — it documents multi-project isolation fixes in the Live Agent subsystem and uses `workspaceId` as the JSON payload key. Any rename of that key is a wire-format change affecting the Vue frontend, the Socket.IO contract, and the MCP stdio server.

## 1. Code symbols (rename)

### Core module rename

- `server/workspace_manager.py` → `server/project_manager.py`
  - `WorkspaceState` → `ProjectState`
  - `WorkspaceManager` → `ProjectManager`
  - Params: `workspace_id` → `project_id`; `ws_id` → `proj_id`
  - Methods: `get_workspace_path()` → `get_project_path()`, `all_workspaces()` → `all_projects()`
- `tests/test_workspace_manager.py` → `tests/test_project_manager.py`

### Function signatures / parameter names

- `server/init.py`: `init_workspace(workspace)` → `init_project(project)`
- `server/workers.py`: `_setup_worktree(workspace, …)` and `_run_agent(…, workspace, ws_id=…)` — rename params
- `server/transfer.py`: `source_workspace_id`, `dest_workspace_id` → `source_project_id`, `dest_project_id`; update error strings
- `server/agents/{base,claude_adapter,gemini_adapter,codex_adapter}.py`: `build_argv(self, prompt, model, workspace, bp_dir=None)` → `…, project, bp_dir=None`
- `server/app.py`: `build_file_tree(workspace)`, `load_state(bp_dir, workspace)`, `export_workspace()`, `import_workspace()`, `_export_workspace_*`, `_workspace_*` helpers
- `server/events.py`: `startup_workspace_id`, local `ws_id` → `proj_id`, comments like `# workspaceId -> list`

## 2. API contracts (HIGH RISK — wire format)

These are the riskiest changes because the MCP stdio server, the Vue frontend, and any external clients all speak these keys. Use a **dual-key transition**: read both, emit both, for one release; then drop the old key.

### Socket.IO payload key

`workspaceId` → `projectId` in every `socket.emit(...)` and every `data.get("workspaceId")` / `data.workspaceId` across:

- `server/events.py` — multiple sites: `_resolve()` at ~line 235, emit sites at ~815, 841, 860, 991, 1064, 1117
- `static/app.js` — emit sites at ~212, 330, 418, 585; handlers at ~398, 504, 517, 550

### HTTP JSON responses (`server/app.py`)

- `{"error": "Unknown workspace"}` → `"Unknown project"`
- `{"workspaceId": ws_id}` → `{"projectId": …}` in export/import endpoints

### CLI flag (`bullpen.py`)

- `--workspace` → `--project` (accept both during deprecation window)
- Propagates to `deploy/docker/entrypoint.sh`, `deploy/digitalocean/bullpen.service`, `AGENTS.md` examples

### MCP tool surface (`server/mcp_tools.py`)

25 occurrences — audit tool parameter names and docstrings for `workspace` / `workspace_id`. Since MCP is wire-format to Claude Code, apply the same dual-key strategy. A breaking change here will silently corrupt ticket writes from running Claude Code sessions, so coordinate carefully.

### Backwards-compat pattern

```python
# Phase 1 (dual-read, dual-emit)
ws_id = data.get("projectId") or data.get("workspaceId")
socketio.emit("task:created", {"projectId": proj_id, "workspaceId": proj_id, ...})

# Phase 2 (after one release)
ws_id = data.get("projectId")
socketio.emit("task:created", {"projectId": proj_id, ...})
```

## 3. Frontend state (`static/app.js` — ~157 occurrences)

Internal Vue reactive state; no wire impact once payload keys are handled above.

- `workspaces` reactive map → `projects`
- `activeWorkspaceId` → `activeProjectId`
- `_applyWorkspaceAmbient`, `_applyWorkspaceTheme`, `_workspaceBaseName` → `_applyProject*`, `_projectBaseName`
- `lastLiveAgentTabByWorkspace` → `lastLiveAgentTabByProject`
- `_wsData()` helper returns `{workspaceId: …}` — update to `{projectId: …}`

Components to sweep for internal variable names and user-visible labels: `LeftPane.js`, `TopToolbar.js`, `LiveAgentChatTab.js`, `CommitsTab.js`, `FilesTab.js`, `WorkerCard.js`, `WorkerTransferModal.js`, `BullpenTab.js`.

## 4. Tests

- Rename `test_workspace_manager.py` → `test_project_manager.py`
- Rename test functions:
  - `test_chat_tabs_are_workspace_room_isolated` → `_project_room_isolated`
  - `test_chat_session_ids_are_scoped_by_workspace` → `_by_project`
  - `test_live_agent_tabs_remember_last_active_per_workspace` → `_per_project`
  - `test_commits_tab_requests_are_workspace_scoped` → `_project_scoped`
- Fixtures in `tests/conftest.py`: `tmp_workspace` → `tmp_project`, `two_workspaces` → `two_projects`
- Update assertions that check literal `workspaceId` keys (once API migration reaches Phase 2)

## 5. Docs (search-and-replace, mostly)

Update:

- `README.md`
- `AGENTS.md` (lines 19, 26: `--workspace /path/to/project` → `--project /path/to/project`)
- `CLAUDE.md` (line 48: "workspace's `.bullpen/config.json`" → "project's")
- `docs/cross-project-fixup.md` (72 occurrences)
- `docs/mcp.md`, `docs/spec.md`, `docs/spec-codex-{1,2}.md`, `docs/plan.md`
- `docs/implementation-plan.md`, `docs/implementation-plan-2.md`, `docs/implementation-plan-4.md`
- `docs/roles.md`, `docs/worker-types.md`, `docs/worker-handoff.md`, `docs/feature-worker-focus.md`
- `docs/docker.md`, `docs/digitalocean-droplet.md`, `docs/fly-config.md`, `docs/linux-windows-port.md`
- `docs/preview-proxy.md`, `docs/ollama.md`, `docs/sqlite.md`, `docs/login.md`, `docs/palette.md`
- `docs/features-1.md`, `docs/features-3.md`, `docs/event-sounds.md`
- `docs/electron-analysis-codex.md`, `docs/ai-backend-roadmap.md`
- `docs/security-review-claude-1.md`, `docs/security-review-codex-1.md`, `docs/seed.md`

## 6. Deploy / infra

- `.gitignore`: comment "Bullpen workspace data" → "Bullpen project data"
- `.dockerignore`: audit the one hit
- `deploy-docker.sh` (~line 223): prompt text "Workspace path to mount" → "Project path to mount"
- `deploy-do-droplet.sh`: audit 5 occurrences
- `docker-compose.yml`: rename env var `WORKSPACE_PATH` → `PROJECT_PATH` (dual-support during transition)
- `Dockerfile`: `BULLPEN_WORKSPACE` and `/workspace` path — **leave as-is** (internal container path, not product terminology)
- `deploy/docker/entrypoint.sh`: `WORKSPACE` shell var — leave; the `--workspace` flag it passes must become `--project`
- `deploy/digitalocean/bullpen.service`: flip `--workspace` → `--project`

## 7. Leave alone (false positives)

- `docs/reviews/2026-04-09/**`, `docs/reviews/2026-04-10/**`, `docs/reviews/2026-04-12/**` — historical audit documents, don't retcon
- Container-internal `/workspace` paths and `BULLPEN_WORKSPACE` env var in Dockerfile/compose/entrypoint — infra convention, not product terminology
- CLAUDE.md / AGENTS.md references to Cowork's "workspace folder" — refers to Claude's file-access concept, not Bullpen's project concept. (Note: the Bullpen-specific line 48 of CLAUDE.md *should* change.)
- `tmp/make_onepager.py` — one-off script, low priority

## 8. Ambiguous — needs a decision

- `app.config["workspace"]` in `server/app.py:158` — is the Flask config key part of any external contract, or purely internal? If internal, rename freely; if anyone reads it externally, dual-support.
- `WORKSPACE_PATH` env var in `docker-compose.yml` — any existing deploys reading this? If yes, dual-support; if greenfield, hard rename.
- MCP tool parameter names in `server/mcp_tools.py` — changing these is a visible contract break for Claude Code sessions already running. Dual-support strongly recommended.

## 9. Rollout plan

### Phase 1 — dual-key plumbing (no breaking changes)

1. Socket.IO event handlers accept both `workspaceId` and `projectId`; prefer `projectId`.
2. Dual-emit pattern: emit both keys in all payloads.
3. `bullpen.py` accepts both `--workspace` and `--project`; deprecation warning for `--workspace`.
4. MCP tool params accept both spellings.

### Phase 2 — rename internals (code symbols)

1. Rename `workspace_manager.py` → `project_manager.py` and all classes/methods.
2. Rename test file and update all test fixtures.
3. Update internal variable names in `events.py`, `app.py`, `workers.py`, `transfer.py`, agent adapters.
4. Update `init.py` function signature.
5. Update `static/app.js` reactive objects and Vue state.

### Phase 3 — flip emission

1. Stop emitting `workspaceId`; emit only `projectId`.
2. Still accept `workspaceId` on receive (log deprecation).
3. Update docs and examples to the new spelling.

### Phase 4 — drop legacy

1. Remove `workspaceId` acceptance in receivers.
2. Remove `--workspace` CLI flag.
3. Remove `WORKSPACE_PATH` env var dual-support.

## 10. Scope estimate

~1,400 occurrences across 114 files, roughly:

- 10–15 code symbol renames (module, class, function names)
- 50–60 API / wire-format key changes — high risk, dual-key migration required
- 80–100 internal variable renames — lower risk, internal consistency
- 300+ frontend state & event handler updates in `static/app.js` and components
- 100+ test identifier updates (method names, fixtures, assertions)
- ~200 documentation updates (mostly search-and-replace in `docs/*.md`)
- 10–15 deployment/config updates (CLI args, scripts, service files)
