# Microsandbox Workspace Root Proposal

## Problem

The current Microsandbox deploy flow is still shaped around one selected
project. It bind-mounts that project into the sandbox at
`/workspace/<project-name>`, starts Bullpen with that path as the startup
workspace, and optionally clones a Bullpen project with
`--install-bullpen-project`.

That model is awkward for the multi-project workflow Bullpen now supports.
Changing the set of projects requires either adding paths that are not mounted,
recreating the sandbox with a different single-project mount, or relying on
setup conveniences that no longer match the desired operating model.

For the Microsandbox install, the better model is to mount the host directory
that contains the user's projects as `/workspace`, then let the user add one or
more projects from inside Bullpen using the existing Add Project, New Project,
and Clone Project commands.

## Goal

Introduce a Microsandbox-specific "workspace root directory":

- The workspace root is a host directory containing project directories.
- The workspace root is mounted into the sandbox as `/workspace`.
- Bullpen does not pre-install or auto-register a project during deploy.
- Users configure Bullpen projects from the running app by adding paths such as
  `/workspace/bullpen`, `/workspace/my-app`, or `/workspace/client/site`.
- The same sandbox can work with multiple projects without being rebuilt.

This replaces the `--install-bullpen-project` convenience path for the
Microsandbox deploy flow.

## Proposed Behavior

### CLI

Add a first-class `--workspace-root PATH` option to `deploy-msb.py`.

Recommended command:

```bash
python3 deploy-msb.py --workspace-root /Users/bill/aistuff --replace
```

The deployer mounts `/Users/bill/aistuff` as `/workspace` in the sandbox. The
Bullpen source checkout remains mounted read-only as `/app`, and the persistent
sandbox home remains mounted at `/home/bullpen`.

CLI decisions:

- `--workspace-root PATH` is required for Microsandbox deploy.
- `--workspace PATH` is removed from the Microsandbox deploy flow.
- `--install-bullpen-project` is removed from the Microsandbox deploy flow
  without a deprecation period. There are no user dependencies on it, and it is
  the wrong abstraction for this workflow.
- When launched without `--workspace-root`, the deployer fails with a direct
  error. It should not infer a workspace root because that risks mounting more
  of the host than the user intended.

### Mounts

Current:

```text
/app                         read-only Bullpen source
/workspace/<project-name>    writable selected host project
/home/bullpen                persistent sandbox home
```

Proposed:

```text
/app                         read-only Bullpen source
/workspace                   writable host workspace root
/home/bullpen                persistent sandbox home
```

Important ownership rule: the deployer must stop repairing or chowning
`/workspace` as a whole. Once `/workspace` is a bind mount of a broad host
directory, a sandbox-side `chown /workspace` could mutate host directory
ownership. The deployer should only verify access and should let normal host
UID/GID mapping determine write permission.

If `/workspace` is not writable by the sandbox Bullpen user at deploy time,
deployment should fail. The deployer should report the problem directly and
should not attempt ownership repair.

### Runtime Environment

The Microsandbox runtime should continue setting:

```text
BULLPEN_PROJECTS_ROOT=/workspace
BULLPEN_HIDE_UNAVAILABLE_PROJECTS=1
```

The startup-workspace variables need to change:

```text
BULLPEN_WORKSPACE=
BULLPEN_WORKSPACE_NAME=
```

or be replaced by a clearer startupless flag:

```text
BULLPEN_START_WITHOUT_PROJECT=1
```

The exact environment shape is an implementation decision, but the important
semantic change is that `/workspace` is the project parent, not a project.

### Bullpen Startup

Bullpen currently assumes a startup workspace:

- `create_app(workspace, ...)` registers the startup path immediately.
- `app.config["startup_workspace_id"]` is used as the fallback workspace for
  routes and socket events.
- `project:remove` refuses to remove the startup project.
- Startup reconciliation, MCP token setup, schedulers, terminals, workers, and
  import/export routes all assume at least one active workspace exists.

For the workspace-root model, Bullpen needs a Microsandbox-compatible empty
project startup mode. In that mode:

- The project registry may be empty.
- Existing persisted projects under `/workspace` are listed and can be joined.
- No `.bullpen` directory is created in `/workspace` itself.
- The first Add Project/New Project/Clone Project action creates or activates a
  normal workspace and becomes the active project.
- If no projects are configured, the web app opens the project menu and shows a
  prominent floating hint pointing to Add Project.

This is the clean solution. Treating `/workspace` itself as the startup project
would be easier, but it would violate the goal by registering the parent
directory as a Bullpen project and creating `/workspace/.bullpen`.

### Project Operations

In Microsandbox workspace-root mode:

- Add Project accepts absolute sandbox paths under `/workspace`.
- New Project creates directories under `/workspace` by default.
- Clone Project defaults to `/workspace/<repo-name>`.
- Project registration rejects paths outside `BULLPEN_PROJECTS_ROOT` when that
  environment variable is set.
- Symlinks are resolved before the root-containment check so a path inside
  `/workspace` cannot escape through a symlink.

The existing `_default_clone_parent()` already prefers
`BULLPEN_PROJECTS_ROOT`, so Clone Project is close to the desired behavior. Add
Project and New Project still need root-containment enforcement.

### Project-Root Guard

The project-root guard is the rule that says "a Bullpen project in this sandbox
must live under `/workspace`." Without it, Add Project could register another
readable path inside the sandbox, such as `/app`, `/home/bullpen`, or any
future path that Microsandbox exposes.

There are two layers where this check should live:

- Event-handler layer: validate `project:add`, `project:new`, and
  `project:clone` before they call project registration. This gives the UI good
  error messages close to the user action.
- Workspace-manager layer: validate inside
  `WorkspaceManager.register_project()` whenever `BULLPEN_PROJECTS_ROOT` is
  set. This protects any non-UI caller, including tests, future MCP tools, CLI
  paths, or server code that registers projects directly.

Recommended: implement both. The event handlers provide friendly messages; the
manager-level guard is the real invariant.

### Provider Verification

The deployer currently verifies Claude, Codex, and Git by changing directory to
the selected container workspace. In startupless mode there is no selected
project during deploy.

Provider verification should run from `/workspace` itself:

- Claude and Codex auth checks can use `/workspace` as a neutral working
  directory.
- Git auth can still verify global identity and `gh auth status`, then skip
  repository remote checks because `/workspace` is not expected to be a Git
  repository.

That keeps deploy verification independent from any project the user might add
later.

### Existing Sandboxes

Do not migrate existing single-project sandboxes for this feature. Existing
sandboxes are disposable and should be replaced before testing the
workspace-root workflow. This avoids preserving stale `projects.json` entries
from the previous layout and keeps the implementation focused on the new model.

## Implementation Plan

### Phase 1: Deployer Shape

Primary files:

- `deploy-msb.py`
- `tests/test_sandboxed_bullpen.py`
- `docs/microsandbox.md`

Steps:

1. Update `DeployConfig`
   - Replace the Microsandbox deployer's central `workspace` concept with
     `workspace_root`.
   - Wire the existing unused `projects_root` concept or remove it in favor of
     the clearer name.
   - Replace `container_workspace_path(config)` with a constant
     `container_workspace_root_path(config)` that returns `/workspace`.

2. Update CLI parsing and validation
   - Add `--workspace-root`.
   - Require it for deploy.
   - Validate that the path exists and is a directory.
   - Remove Microsandbox deploy support for `--workspace`.
   - Remove Microsandbox deploy support for `--install-bullpen-project`.
   - Keep auth/test-provider subcommands usable by requiring
     `--workspace-root` there too, since their verification cwd becomes
     `/workspace`.

3. Update sandbox creation
   - Bind `config.workspace_root` to `/workspace`.
   - Stop binding individual project paths under `/workspace/<name>`.
   - Keep `/app` and `/home/bullpen` unchanged.

4. Update mount/access checks
   - Remove creation of `/workspace/.bullpen`.
   - Remove `chown` or recursive ownership repair under `/workspace`.
   - Verify `/workspace` and `/home/bullpen` are accessible.
   - Fail deploy if `/workspace` is not writable by the Bullpen user.

5. Update deploy runtime environment
   - Set `BULLPEN_PROJECTS_ROOT=/workspace`.
   - Set `BULLPEN_START_WITHOUT_PROJECT=1`.
   - Stop setting `BULLPEN_WORKSPACE` to `/workspace/<project>`.
   - Either omit `BULLPEN_WORKSPACE_NAME` or set it to an empty value.

6. Update deploy startup and verification
   - Start Bullpen in startupless mode from `/app`.
   - Use `/workspace` as the cwd for Claude and Codex verification.
   - Let Git verification check global Git/GitHub auth and skip repository
     remote checks unless `/workspace` itself is a Git repository.

Tests:

- Update existing `tests/test_sandboxed_bullpen.py` cases that currently pass
  `--workspace`.
- Add a parser test proving deploy without `--workspace-root` fails.
- Add a parser test proving `--workspace` and `--install-bullpen-project` are
  rejected.
- Add a runtime env test proving `BULLPEN_PROJECTS_ROOT=/workspace` and
  `BULLPEN_START_WITHOUT_PROJECT=1`.
- Add a volume-mapping test proving `/workspace` binds the host root directly.
- Add a mount-access command construction test proving no `.bullpen` creation
  or `chown /workspace` remains.

### Phase 2: Startupless Server Mode

Primary files:

- `bullpen.py`
- `server/app.py`
- `server/events.py`
- `server/workspace_manager.py`
- existing server test files, especially `tests/test_e2e.py` and
  `tests/test_events.py`

Steps:

1. Add an internal startupless launch path
   - Add a `--start-without-project` CLI flag or use
     `BULLPEN_START_WITHOUT_PROJECT=1` as the server-side switch.
   - Keep normal local Bullpen startup behavior unchanged.
   - In Microsandbox, start Bullpen with `/workspace` available but do not
     register `/workspace` as a project.

2. Update `create_app()`
   - Allow `create_app()` or the CLI entrypoint to start without registering an
     initial workspace when the Microsandbox startupless flag is set.
   - Set `app.config["startup_workspace_id"]` to `None` in startupless mode.
   - Keep `app.config["workspace"]` and `app.config["bp_dir"]` either absent or
     explicitly `None`; do not point them at `/workspace`.
   - Make startup reconciliation, MCP runtime config creation, scheduler
     startup, and fallback workspace resolution tolerate an empty workspace
     list.
   - Ensure events that require a workspace return a clear "add or select a
     project first" error rather than falling back to a nonexistent startup id.

3. Update connect behavior
   - Browser clients should receive `projects:updated` even when no
     `state:init` is emitted.
   - Browser clients should receive `state:init` only after a project is joined
     or added.
   - MCP clients should fail or report no active workspace until a project
     exists; MCP project creation can be deferred.

4. Update workspace resolution
   - `_resolve()` in `server/events.py` currently falls back to
     `startup_workspace_id`. In startupless mode, it should return an explicit
     missing-workspace error when no workspace id is supplied.
   - API routes in `server/app.py` that use `request.args.get("workspaceId",
     startup_id)` need to tolerate `startup_id is None`.
   - Routes that cannot operate without a workspace should return a 400-style
     JSON error instead of raising.

Tests:

- Add a server test that starts with `BULLPEN_START_WITHOUT_PROJECT=1` and an
  empty registry.
- Assert connect emits `projects:updated` with an empty list and no
  `state:init`.
- Assert workspace-required socket events return the no-active-workspace error.
- Assert `project:add` from empty state registers a real project and emits
  `state:init` with `switchTo: true`.
- Assert normal `create_app(workspace)` behavior remains unchanged.

### Phase 3: Frontend Empty State

Primary files:

- `static/app.js`
- `static/components/LeftPane.js`
- frontend string tests in `tests/test_frontend_leftpane_project_menu.py`

Current state:

- `LeftPane` already tracks `projectsLoaded`.
- `LeftPane` already has `showEmptyProjectHint`.
- The current hint tells the user to open the menu; the new behavior should
  open the menu automatically and point directly at Add Project.

Steps:

1. Update active-workspace handling
   - Treat `projectsLoaded && projects.length === 0 && !activeWorkspaceId` as
     a first-class app state.
   - Avoid rendering workspace-dependent tabs when no workspace is active.
   - Disable or no-op commands that require `activeWorkspaceId`.

2. Update `LeftPane`
   - If no active workspace is available after connect, open the project menu
     automatically.
   - Show a prominent floating hint pointing at the Add Project command.
   - Keep the hint dismissible so it does not become a permanent obstruction.
   - Avoid rendering task, worker, terminal, file, and stats panes until a
     workspace is active.
   - Keep existing behavior unchanged once a workspace is joined.
   - Do not build a separate landing page unless the menu-plus-hint pattern
     still fails in testing.

3. Verify visually
   - Test desktop and narrow viewport states.
   - Confirm the hint does not overlap the menu, pane resize handle, or toolbar.
   - Confirm the menu closes normally after Add/New/Clone prompts.
   - Confirm the hint does not return after dismissal in the same session.

Tests:

- Extend frontend string tests to require automatic menu opening on empty
  projects.
- Add checks for the Add Project hint text and dismiss path.
- If feasible, add a lightweight browser smoke test for the empty state.

### Phase 4: Project-Root Containment

Primary files:

- `server/workspace_manager.py`
- `server/events.py`
- `tests/test_events.py`
- `tests/test_e2e.py`

Steps:

1. Add a root-containment helper
   - Add a helper that resolves a candidate path and verifies it is equal to or
     below `BULLPEN_PROJECTS_ROOT`.
   - Resolve symlinks before comparing paths.
   - Return a clear user-facing error when the path is outside the root.

2. Apply it at both layers
   - Use it in `project:add`, `project:new`, and `project:clone`.
   - Apply the same guard in `WorkspaceManager.register_project()` whenever
     `BULLPEN_PROJECTS_ROOT` is set.
   - Keep normal non-Microsandbox behavior unchanged when
     `BULLPEN_PROJECTS_ROOT` is unset.

Tests:

- Add Project accepts `/workspace/project`.
- Add Project rejects `/app`.
- Add Project rejects `/home/bullpen`.
- Add Project rejects a symlink inside `/workspace` that resolves outside
  `/workspace`.
- New Project and Clone Project use `/workspace` defaults.
- Normal local Bullpen registration still accepts projects outside any
  Microsandbox root when `BULLPEN_PROJECTS_ROOT` is unset.

### Phase 5: Documentation And In-Sandbox Proof

Primary files:

- `docs/microsandbox.md`
- `docs/microsandbox-workspace-root.md`
- optional test harness under `tmp/` or a reusable test script if it proves
  useful

Steps:

1. Update user-facing Microsandbox docs
   - Update `docs/microsandbox.md` to document workspace root setup.
   - Remove `--install-bullpen-project` instructions.
   - Explain that project paths in the UI are sandbox paths such as
     `/workspace/bullpen`, not host paths such as `/Users/bill/aistuff/bullpen`.

2. Replace test sandboxes
   - Create a fresh sandbox with the new deploy path.
   - Do not reuse old single-project sandbox homes for acceptance testing.

3. Prove the workflow in situ
   - Deploy with `--workspace-root /Users/bill/aistuff`.
   - Verify the UI starts with no project active.
   - Add `/workspace/bullpen`.
   - Verify `.bullpen` is created inside `/workspace/bullpen`, not
     `/workspace`.
   - Add at least one second project under `/workspace` without rebuilding.
   - Verify Claude/Codex/Git commands still run from the added project.
   - Verify app load performance remains in the low-ms range after the
     Microsandbox HTTP patch.

## Acceptance Criteria

- A deploy command with `--workspace-root /Users/bill/aistuff` mounts that
  directory as `/workspace`.
- Deploy requires `--workspace-root`; it does not accept `--workspace` or
  `--install-bullpen-project`.
- Deploy does not clone or register a Bullpen project.
- Deploy does not create `/workspace/.bullpen`.
- Deploy does not chown `/workspace` or mutate host workspace-root ownership.
- Deploy fails clearly if `/workspace` is not writable by the sandbox Bullpen
  user.
- Bullpen starts successfully with an empty project registry.
- The browser UI opens the project menu and points the user at Add Project when
  no projects are configured.
- Adding `/workspace/<project>` creates `/workspace/<project>/.bullpen`,
  switches the UI to that project, and enables normal Bullpen operation.
- Multiple projects under `/workspace` can be added without rebuilding the
  sandbox.
- Project Add/New/Clone rejects paths outside `/workspace`, including symlink
  escapes.
- MCP tools report no active workspace until a project is added.
- Claude, Codex, and Git verification still pass or produce the existing
  actionable auth messages.

## Remaining Issues Before Implementation

1. Empty-state UI details

   The direction is decided: open the project menu and show a floating hint.
   The exact placement, wording, dismissal behavior, and persistence rules
   should be designed and tested. Prior attempts at this interaction were not
   satisfactory, so this deserves deliberate UI verification.

2. Startupless server fallback behavior

   Many server routes currently use `startup_workspace_id` as a fallback. The
   implementation needs an explicit list of which routes should return a
   no-active-workspace error, which routes can operate without a workspace, and
   which routes should be hidden or disabled in the UI until a project is
   active.

3. MCP project administration

   Initial behavior is decided: MCP tools report no active workspace until a
   project is added. A later feature can decide whether MCP should be allowed to
   add projects itself.

4. Fresh-sandbox rollout

   This feature should be tested against newly created sandboxes only. Before
   implementation testing starts, replace the existing test fleet so stale
   state from the previous single-project layout does not confuse results.

## Recommended Decision Set

- Require explicit `--workspace-root` for the new Microsandbox workflow.
- Remove Microsandbox deploy support for `--workspace`.
- Remove Microsandbox deploy support for `--install-bullpen-project`.
- Implement true startupless Bullpen mode instead of using `/workspace` or a
  hidden directory as a fake project.
- Open the project menu and show a prominent Add Project hint when no projects
  are configured.
- Enforce `BULLPEN_PROJECTS_ROOT` containment in `WorkspaceManager` and reuse
  the helper from project socket handlers.
- Replace existing sandboxes for this change instead of migrating stale
  single-project sandbox state.
- Fail deployment if `/workspace` is not writable by the sandbox Bullpen user.
