# Microsandbox Management Redo

**Date:** 2026-05-26

## Problem statement

The current Microsandbox deployment path is functionally capable but
operationally hostile. `deploy-sandbox.py` has become a command-line flag
garden that asks the user to remember, reconstruct, or preserve a long launch
command for routine lifecycle operations. That is not a management model.

The current experience makes the human operator responsible for:

- remembering the correct `--workspace-root`, ports, sandbox name, home path,
  resource limits, replacement mode, and browser behavior
- knowing when to use prepare, rebuild, replace, auth, test-provider, or
  first-light commands
- understanding which state is durable and which state disappears after a
  laptop restart
- recovering Bullpen after laptop restart, app restart, Microsandbox runtime
  failure, expired provider auth, occupied ports, or stale detached sandboxes
- scaling the above to more than one sandbox

This does not scale on the carbon-unit side. The target experience should make
Microsandbox instances durable named things, not command invocations.

## Goal

Create a human-usable Microsandbox management layer that tucks launch complexity
into persistent configuration and gives the user stable restartable instances
across:

- laptop restarts
- login session restarts
- Bullpen restarts
- manager app restarts
- provider credential expiry
- prepared base upgrades
- any practical number of named instances

The user should be able to say "start my Bullpen instance" or "keep these three
instances running" without reconstructing command-line flags.

## Non-goals

- Do not make Bullpen itself responsible for supervising the VM that contains
  Bullpen. Bullpen can expose status and cooperate with the manager, but the
  manager should live outside the sandboxed Bullpen runtime.
- Do not build or ship a menu bar app as a product surface. This spec
  explicitly rejects menu bar real estate as a control surface.
- Do not remove `deploy-sandbox.py` immediately. It can remain the lower-level
  engine while the manager matures.
- Do not require the user to understand Microsandbox SDK details.
- Do not require a cloud control plane.
- Do not share provider credentials across instances silently.

## Proposed product shape

Gen 1 should be a host-local web manager built with the same family of
technology as Bullpen: Flask, Flask-SocketIO, and Vue. It should run as a
localhost-only control plane that launches and supervises Bullpen instances.
Those instances may be either:

- **local instances:** Bullpen runs directly on the host as a managed process
- **sandboxed instances:** Bullpen runs inside a Microsandbox microVM

The user should struggle through at most one terminal interaction to start the
manager. After that, they should create, start, stop, restart, repair, and open
Bullpen instances from the web interface.

Example Gen 1 launch:

```bash
python3 bullpen_manager.py
```

or, after packaging:

```bash
bullpen-manager
```

The manager prints one URL, such as:

```text
Manager: http://127.0.0.1:5757
```

Everything else moves into persistent profiles and guided UI flows.

This shape deliberately avoids early system-configuration pain:

- no native app installer required
- no menu bar app
- no launchd requirement for first success
- no privileged daemon
- no required background service installation
- no exclusion of Linux or headless VMs

Launch-on-login, launchd user services, systemd user services, packaged desktop
apps, and native wrappers are deferred enhancements. They should build on the
same profile registry and lifecycle engine rather than replace it.

### Gen 1 web manager strengths

- fastest path from the current codebase
- reuses Flask, Socket.IO, Vue, and the current Bullpen UI idioms
- supports macOS, Linux, and headless VMs
- easy to run in development without poking system-level laptop config
- can manage both host-local and Microsandboxed Bullpen from one place
- keeps the manager outside the Bullpen instances it supervises
- allows remote/tunneled access later with normal web deployment patterns

### Gen 1 web manager risks

- the first launch is still a terminal command until packaging improves
- auto-start after laptop restart requires an optional service integration
- browser UX can feel less "installed" than a desktop app
- file pickers and Keychain integration are less native unless bridged
- the manager must be clearly distinguished from the Bullpen instances it
  launches

### Deferred packaging options

These remain valid later, but they should not shape Gen 1:

- **Bullpen Desktop:** a Docker Desktop-like native app that wraps the same
  manager backend and presents Bullpen plus AI runtimes as a local appliance.
- **Electron desktop:** fastest desktop wrapper for the web manager, but
  heavier and not needed to prove the lifecycle model.
- **Tauri desktop:** lighter desktop wrapper, better aligned with a small host
  controller, but adds Rust/tooling complexity.
- **Native Swift/AppKit or SwiftUI:** best Mac integration, highest native
  development and packaging burden.
- **CLI plus daemon:** useful for scripting and later automation, but not the
  primary human interface.
- **Inside Bullpen:** rejected as the primary architecture because the manager
  must supervise both local and sandboxed Bullpen runtimes.

### Deferred runtime options

Gen 1 should support local and Microsandbox runtimes first. Other runtimes can
use the same adapter/profile model later.

- **Docker runtime:** useful for users who already trust Docker or for
  environments where Microsandbox is unavailable. It should be implemented as a
  third adapter, not as a replacement for the manager. Docker profiles would own
  image/tag, container name, volume mounts, ports, environment, health checks,
  logs, and restart policy. This is deferred because Docker Desktop and Docker
  daemon availability introduce their own host setup burden, especially on
  macOS.

### Decision criteria for later packaging

Use these criteria before adding a desktop wrapper or service installer:

- does it reduce first-run friction?
- does it preserve Linux/headless usefulness?
- does it avoid duplicated lifecycle logic?
- does it improve startup-after-login without surprising the user?
- does it make credential renewal easier?
- does it respect the user's desktop real estate?
- does it still let advanced users run the manager plainly from a terminal?

The CLI remains, but it becomes an escape hatch:

```bash
bullpen-manager start personal
bullpen-manager stop personal
bullpen-manager status
bullpen-manager open personal
```

No routine operation should require passing raw local, Microsandbox, or Docker
deployment flags.

## Architecture

### Components

1. **Manager web server**
   - Flask application running on the host.
   - Serves the manager UI on localhost.
   - Exposes JSON and Socket.IO APIs for live status, logs, and lifecycle
     operations.
   - Owns instance registry, profile state, reconciliation, health checks, port
     allocation, provider renewal status, and optional startup behavior.
   - Runs outside every managed Bullpen instance.

2. **Persistent registry**
   - Stores named instance profiles and observed runtime state.
   - Lives in host application support storage, not in a project checkout.
   - Suggested macOS path:
     `~/Library/Application Support/Bullpen Manager/registry.json`
   - Suggested portable path:
     `~/.config/bullpen-manager/registry.json`

3. **Runtime adapters**
   - Local adapter starts Bullpen directly on the host as a managed process.
   - Microsandbox adapter creates/replaces/stops sandbox runtimes and starts
     Bullpen inside them.
   - Deferred Docker adapter creates/replaces/stops containers and starts
     Bullpen inside them.
   - All adapters expose the same operations to the manager:
     start, stop, restart, health, logs, open URL, and provider status where
     applicable.
   - Phase 1 may call existing scripts (`bullpen.py`, `deploy-sandbox.py`) but
     should move shared lifecycle logic behind adapter APIs over time.

4. **Instance homes**
   - Each managed instance gets stable durable state.
   - Local instances use a host-local Bullpen home and workspace paths.
   - Sandboxed instances get a durable sandbox home directory.
   - Docker instances get a durable host directory mounted as the container's
     Bullpen home.
   - Suggested path:
     `~/.bullpen/manager/instances/<instance-id>/home`
   - For sandboxed instances, this maps to `/home/bullpen` inside the sandbox.
   - Provider auth, Bullpen global config, and logs remain there unless a local
     profile explicitly points to existing host credentials.

5. **Workspace configuration**
   - Each instance profile stores one or more workspace roots.
   - Local instances use host paths directly.
   - Sandboxed instances mount the selected root into the microVM.
   - Docker instances mount selected roots into the container.
   - Phase 1 should keep the current one-root sandbox mount model:
     `<workspace-root> -> /workspace`.
   - The manager should remember the mount and validate it before start.

6. **Base snapshot registry**
   - Tracks prepared base snapshots, versions, source image, Bullpen source
     version, agent CLI versions, and build date.
   - Supports "prepare if missing", "upgrade available", and "rebuild base"
     as managed actions for sandboxed instances.

7. **Image registry**
   - Deferred Docker support tracks Bullpen Docker images, tags, build dates,
     installed CLI versions, and profiles using each image.
   - Docker image management should mirror base snapshot management but remain
     separate because Docker has different build, cache, and daemon semantics.

8. **Vue manager UI**
   - Shares visual language with Bullpen where practical.
   - Provides setup, logs, profile editing, credential renewal, base management,
     and diagnostics.
   - Uses Socket.IO for live lifecycle updates.
   - Opens managed Bullpen instances in new tabs/windows.

9. **CLI**
   - Optional escape hatch for scripting and recovery.
   - Talks to the manager API when the manager is running.
   - May provide direct recovery commands when the manager is down.

### Process model

The manager web server is the long-lived host process for Gen 1. Managed
Bullpen instances are desired-state objects. On startup, the manager loads the
registry and reconciles each instance:

- if desired state is `running`, ensure the instance exists and Bullpen health
  passes
- if desired state is `stopped`, ensure it is not running
- if desired state is `paused`, do nothing automatically
- if desired state is `needs-attention`, keep it stopped until the user fixes
  the reported issue

This reconciliation is the key change. The user should not have to rerun an
incantation after laptop restart; the manager should see that the desired state
is running and bring the instance back when the manager is started. Optional
launch-on-login can automate starting the manager itself later.

## Persistent instance profile model

Each managed Bullpen instance is a named profile with stable identity and
mutable settings. The runtime type determines whether the manager starts
Bullpen on the host or inside Microsandbox.

Example sandboxed profile:

```json
{
  "schemaVersion": 1,
  "id": "personal",
  "displayName": "Personal Bullpen",
  "runtime": "microsandbox",
  "desiredState": "running",
  "sandboxName": "bullpen-personal",
  "base": "bullpen-microsandbox-local",
  "workspaceRoot": "/Users/bill/aistuff",
  "instanceHome": "/Users/bill/.bullpen/manager/instances/personal/home",
  "sandboxHome": "/Users/bill/.bullpen/manager/instances/personal/home",
  "ports": {
    "bullpen": 8080,
    "app": 3000
  },
  "resources": {
    "vcpus": 4,
    "memoryMiB": 4096,
    "hostNofile": 12000,
    "guestNofile": 65536,
    "networkMaxConnections": 8192
  },
  "auth": {
    "adminUser": "admin",
    "adminPasswordRef": "keychain://bullpen-manager/personal/admin",
    "providers": {
      "claude": { "enabled": true },
      "codex": { "enabled": true },
      "git": { "enabled": true }
    }
  },
  "startup": {
    "autoStartWhenManagerStarts": true,
    "restartIfUnhealthy": true,
    "openBrowserOnManualStart": true
  },
  "createdAt": "2026-05-26T00:00:00Z",
  "updatedAt": "2026-05-26T00:00:00Z"
}
```

Example local profile:

```json
{
  "schemaVersion": 1,
  "id": "local-dev",
  "displayName": "Local Dev Bullpen",
  "runtime": "local",
  "desiredState": "stopped",
  "workspaceRoot": "/Users/bill/aistuff",
  "instanceHome": "/Users/bill/.bullpen/manager/instances/local-dev/home",
  "ports": {
    "bullpen": 8081,
    "app": 3001
  },
  "process": {
    "python": "python3",
    "bullpenSource": "/Users/bill/aistuff/bullpen"
  },
  "auth": {
    "adminUser": "admin",
    "adminPasswordRef": "keychain://bullpen-manager/local-dev/admin",
    "providers": {
      "claude": { "mode": "host", "enabled": true },
      "codex": { "mode": "host", "enabled": true },
      "git": { "mode": "host", "enabled": true }
    }
  },
  "startup": {
    "autoStartWhenManagerStarts": false,
    "restartIfUnhealthy": true,
    "openBrowserOnManualStart": true
  },
  "createdAt": "2026-05-26T00:00:00Z",
  "updatedAt": "2026-05-26T00:00:00Z"
}
```

Deferred Docker profile shape:

```json
{
  "schemaVersion": 1,
  "id": "docker-lab",
  "displayName": "Docker Lab Bullpen",
  "runtime": "docker",
  "desiredState": "stopped",
  "image": "bullpen:local",
  "containerName": "bullpen-docker-lab",
  "workspaceRoot": "/Users/bill/aistuff",
  "instanceHome": "/Users/bill/.bullpen/manager/instances/docker-lab/home",
  "ports": {
    "bullpen": 8082,
    "app": 3002
  },
  "volumes": {
    "workspace": "/workspace",
    "home": "/home/bullpen"
  },
  "startup": {
    "autoStartWhenManagerStarts": false,
    "restartIfUnhealthy": true,
    "openBrowserOnManualStart": true
  }
}
```

Sensitive values are references, not plaintext. On macOS, use Keychain for the
Bullpen admin password and any future host-side secrets. Provider OAuth state
created inside a sandbox remains in that sandbox home. Provider state for local
instances may use host-native provider auth, but the UI must make that explicit.
Docker provider state should be treated like sandbox provider state by default:
stored in the profile's mounted instance home, not silently imported from the
host.

## Lifecycle model

### First install

User flow:

1. Clone or install Bullpen Manager.
2. Run one command to start the manager.
3. Manager checks host prerequisites:
   - Python runtime and Python dependencies
   - Bullpen source availability
   - required permissions for workspace and instance home paths
   - optional Microsandbox support if the user wants sandboxed instances
4. Browser opens the manager UI.
5. User creates the first instance profile through a setup wizard.
6. Manager starts the instance and opens Bullpen.

For local instances, the user should not need Microsandbox installed. For
sandboxed instances, the wizard checks Microsandbox availability and can guide
base preparation without making the local-only path pay that cost.

The first-run wizard should ask only for:

- profile name
- runtime type: local or Microsandbox
- workspace root
- admin username and password
- whether to auto-start when the manager starts
- which provider auth flows to set up now

Everything else uses safe defaults with an Advanced section.

### Daily start

User flow:

- Start the manager with the one known command, or use optional service
  integration once configured.
- Open the manager URL.
- Manager starts or replaces the runtime using the saved profile.
- Manager verifies Bullpen health.
- Manager opens the Bullpen instance if the action was manual and the profile
  requests it.

No flags. No remembered paths. No port arithmetic.

### Laptop restart

Expected behavior:

1. Laptop restarts.
2. Local Bullpen processes and Microsandbox runtimes are gone.
3. User starts the manager, or optional service integration starts it at login.
4. Manager loads profiles.
5. For profiles with `desiredState=running` and
   `autoStartWhenManagerStarts=true`, manager recreates the instance from saved
   config.
6. Manager verifies health and updates status.
7. If an instance cannot be restarted, manager marks it `needs-attention` and
   shows the reason in the UI.

This is the core replacement for up-arrow/enter. Gen 1 may still require one
terminal command to start the manager. It should not require remembering any
per-instance launch command.

### App restart

If the browser tab closes, managed instances keep running because the manager
process owns them. Reopening the manager URL reconnects to current state. If the
manager process restarts, it reconciles actual host processes and Microsandbox
state against desired state.

### Bullpen crash inside an instance

Manager health checks `http://127.0.0.1:<bullpen-port>/health`.

If health fails:

- collect recent instance logs
- collect sandbox proxy logs if present
- attempt configured restart policy
- if restart fails, mark the instance `needs-attention`
- preserve instance home and workspace

Restart policy options:

- `off`: report only
- `restart-bullpen`: restart the Bullpen process
- `replace-runtime`: for sandboxed instances, stop/remove the runtime and
  recreate it from the profile
- `restart-process`: for local instances, stop and restart the host process

Phase 1 may use full runtime replacement for sandboxed instances because the
current normal deploy creates a known runtime.

### Provider auth renewal

Provider auth is a lifecycle concern, not a deploy flag.

The manager should show provider status per instance:

- Not configured
- Verified
- Expired
- Verification failed
- Needs interactive login
- Unknown

Actions:

- Renew Claude
- Renew Codex
- Renew GitHub
- Test provider
- View last verification output

For sandboxed instances, renewal runs inside the target sandbox as the
`bullpen` user and writes only to that sandbox home. If the sandbox is stopped,
the manager starts a temporary maintenance runtime using the same profile,
performs auth, verifies it, then returns to the prior desired state.

For local instances, renewal either verifies host-native provider auth or runs
the provider's local setup flow in an explicit local instance context. The UI
must make clear when it is touching host credentials rather than sandbox-local
credentials.

Codex localhost callback replay and Claude IPv6 mitigation remain implementation
details inside the auth workflow. The UI should present simple instructions and
status, not expose the workaround.

### Base preparation and upgrades

The manager tracks base snapshot freshness separately from instance profiles.
This applies only to Microsandbox instances.

States:

- Missing
- Preparing
- Ready
- Update available
- Rebuild failed
- Deprecated

Actions:

- Prepare base
- Rebuild base
- Validate base
- Show installed versions
- Use this base for selected sandboxed instances

Starting a sandboxed instance should never surprise the user with a long
package-manager operation unless they explicitly allow "prepare missing base
automatically".

### Runtime replacement

Replacement should be a named action for sandboxed instances:

- Stop runtime
- Remove runtime object
- Keep instance home
- Keep workspace untouched
- Recreate runtime from profile
- Start Bullpen
- Verify health

The UI label should be "Restart instance" or "Repair by replacing runtime",
depending on context. The implementation can still call the current
Microsandbox replacement path for sandboxed profiles.

### Stop and delete

Stop:

- stops the runtime
- keeps profile
- keeps instance home
- keeps workspace
- sets desired state to `stopped`

Delete profile:

- stops runtime
- removes registry entry
- asks separately whether to delete instance home
- never deletes workspace roots

Deleting provider auth should be a separate explicit action.

## Multi-instance support

The manager must treat Bullpen instances as an unbounded inventory, not one
global singleton. Some instances are local host processes. Some are
Microsandbox-backed runtimes.

### Required capabilities

- create any number of named profiles
- assign stable instance names
- track runtime type: local or Microsandbox
- assign stable sandbox names for Microsandbox profiles
- allocate non-conflicting ports
- assign separate instance homes by default
- allow shared or separate base snapshots for sandboxed instances
- display all profiles and runtime states
- start, stop, restart, open, and delete each instance independently
- support bulk actions:
  - start all auto-start instances
  - stop all
  - verify all providers
  - rebuild base and roll selected sandboxed instances

### Port allocation

The manager owns port allocation. Users should not choose ports during normal
setup.

Default ranges:

- first instance: Bullpen `8080`, app `3000`
- next instances: allocate from configured ranges
  - Bullpen UI: `8081-8180`
  - app preview: `3001-3100`

The ranges are configurable. The manager must reserve port pairs in the
registry before starting an instance, then verify the ports are actually
available on the host immediately before launch.

#### Port state model

Track port state separately from instance state:

- `available`: no registry reservation and no listening process
- `reserved`: assigned to a known profile but the instance is stopped
- `starting`: reserved and a start operation is in progress
- `listening-managed`: occupied by the expected managed instance
- `listening-unmanaged`: occupied by another process
- `stale-managed`: reserved by a profile, but observed listener does not match
  the expected process/runtime
- `conflict`: two profiles or one profile and one unmanaged process claim the
  same port

Each profile stores:

```json
{
  "ports": {
    "bullpen": 8081,
    "app": 3001
  },
  "portReservation": {
    "owner": "local-dev",
    "updatedAt": "2026-05-26T00:00:00Z",
    "source": "auto"
  }
}
```

The registry is the source of intended ownership. The socket table is the
source of observed occupancy. Reconciliation compares both.

#### Allocation algorithm

When creating a profile:

1. Load registry under a file lock.
2. Build the reserved set from all profiles.
3. Probe the host socket table for currently listening ports.
4. Starting with preferred defaults, choose the first Bullpen/app pair where:
   - neither port is reserved by another profile
   - neither port is currently listening
   - Bullpen and app ports are different
5. Write the reservation into the profile before returning it to the UI.
6. Release the file lock.

When starting a profile:

1. Load registry under a file lock.
2. Confirm the profile still owns its reserved ports.
3. Probe the host socket table.
4. If a reserved port is free, proceed.
5. If a reserved port is occupied by the expected managed runtime, treat the
   instance as already running and verify health.
6. If a reserved port is occupied by anything else, block start and mark the
   profile `needs-attention`.
7. Offer repair actions:
   - choose new ports automatically
   - stop the managed stale runtime if the manager can prove ownership
   - open diagnostics for unmanaged listeners

When deleting a profile:

1. Stop the runtime if running.
2. Remove its port reservations from the registry.
3. Do not try to kill unrelated listeners that happen to use those ports later.

#### Conflict classification

Managed local process:

- Match by stored PID, command line, working directory, environment marker, and
  health URL where possible.

Managed Microsandbox runtime:

- Match by sandbox name, profile ID, expected published ports, and health URL.

Managed Docker runtime:

- Match by container name, labels, expected published ports, and health URL.

Unmanaged listener:

- Anything listening on the port that cannot be proven to belong to the profile.
  The manager should not kill it automatically.

Stale registry reservation:

- A port is reserved by a profile whose instance is stopped and no process is
  listening. This is not an error. It prevents surprise port churn.

Stale runtime:

- A port is listening and appears to belong to an old managed runtime that is no
  longer reachable or no longer matches registry state. The UI may offer a
  cleanup action, but only when ownership is proven.

#### Race handling

Port probing is inherently racy because another process can bind after the
manager probes. Therefore every adapter must handle bind failure as a normal
start failure:

- capture the failed port
- mark the profile `needs-attention`
- show the conflict in the UI
- offer automatic reallocation and retry

The manager should not silently change ports for an existing profile while a
user has it configured elsewhere. Automatic reallocation is allowed only during
profile creation or when the user explicitly clicks "Choose new ports".

#### UI behavior

The create flow should default to automatic port assignment and hide numeric
ports unless Advanced is open.

The instance detail view should show:

- Bullpen URL
- app preview URL
- reservation owner
- current observed listener
- conflict reason, if any
- "Choose new ports" action
- "Retry start" action

The diagnostics view should show all managed port reservations and currently
observed listeners in the manager's configured ranges.

### Naming

The user sees display names:

- Personal Bullpen
- Client A
- Release Lab

Internal names are stable and slugged:

- `bullpen-personal`
- `bullpen-client-a`
- `bullpen-release-lab`

Changing display name should not change internal identity unless the user
explicitly asks to rename the runtime.

### Credential isolation

Default for sandboxed instances: each sandbox has its own `/home/bullpen` and
its own provider auth.

Default for local instances: the profile declares whether provider auth is
host-native or profile-local. Host-native auth is convenient but should be
shown plainly because it touches the user's normal CLI auth state.

Optional advanced mode: multiple sandboxed instances may share a sandbox home
only after an explicit warning that provider auth, Bullpen config, logs, and
CLI caches will be shared.

## User interfaces

### Gen 1 web manager

Recommended screens:

1. **Overview**
   - all instances
   - runtime type: local or Microsandbox
   - desired state
   - actual state
   - health
   - ports
   - provider status
   - quick actions

2. **Create Instance**
   - profile name
   - runtime choice: local or Microsandbox
   - deferred Docker runtime shown only when implemented, not as Gen 1 promise
   - workspace root picker
   - auto-start-when-manager-starts toggle
   - admin credentials
   - provider setup choices
   - advanced resource and port settings
   - sandbox base choice only when runtime is Microsandbox

3. **Instance Detail**
   - current URLs
   - start/stop/restart/delete
   - health timeline
   - logs
   - workspace mount
   - resource settings
   - restart policy

4. **Credentials**
   - local-vs-sandbox credential mode
   - per-provider verification status
   - renew buttons
   - last verified time
   - last failure reason

5. **Base Snapshots**
   - installed base snapshots
   - versions of Python, Node, agent CLIs, gh, git
   - rebuild/validate actions
   - sandboxed instances using each base

6. **Docker Images** (deferred)
   - installed Bullpen images
   - image tags and build dates
   - rebuild/pull/validate actions
   - Docker instances using each image

7. **Diagnostics**
   - environment checks
   - Microsandbox runtime status
   - Docker daemon status when Docker support exists
   - local process manager status
   - port conflicts
   - recent manager events
   - export support bundle

The web manager should share Bullpen's look and feel where practical: Vue
components, icons, spacing, dark/light theme behavior, and live Socket.IO
updates. It should still look like a manager, not like another Bullpen board.
The visual relationship should say "same family, different job."

### Deferred desktop implementation variants

If a desktop wrapper is selected later, the UI technology should be chosen
deliberately.

Native Swift/AppKit or SwiftUI:

- best Mac integration
- strongest Keychain, login item, notifications, and permission story
- highest native-development cost

Electron:

- fastest full-window desktop shell for an existing web UI
- easy reuse of the web manager frontend
- heavier runtime and more packaging surface
- must avoid duplicating manager lifecycle logic in the renderer

Tauri:

- lighter desktop shell than Electron
- good fit for a small host-control app
- adds Rust build and updater complexity

Hybrid wrapper:

- native shell launches and supervises the same local web manager
- app window loads the local dashboard
- keeps product feel without splitting backend logic
- may be the best compromise if web manager ships first

### CLI

The CLI should be stable, short, and profile-oriented. In Gen 1, it is optional
and secondary to the web UI.

Examples:

```bash
bullpen-manager list
bullpen-manager create personal --runtime microsandbox --workspace-root /Users/bill/aistuff
bullpen-manager create local-dev --runtime local --workspace-root /Users/bill/aistuff
bullpen-manager start personal
bullpen-manager stop personal
bullpen-manager restart personal
bullpen-manager open personal
bullpen-manager logs personal
bullpen-manager auth personal codex
bullpen-manager doctor
```

Advanced flags may exist, but routine usage should not require them.

## State reconciliation

The manager keeps separate desired and observed state.

Desired state:

- `running`
- `stopped`
- `paused`

Observed state:

- `not-created`
- `starting`
- `running`
- `healthy`
- `unhealthy`
- `stopping`
- `stopped`
- `needs-attention`
- `unknown`

On manager startup and periodic interval:

1. Read registry.
2. Query local process state and Microsandbox runtime state.
3. Check managed ports.
4. Check Bullpen health for running instances.
5. Compare observed state to desired state.
6. Apply the profile's reconciliation policy.
7. Write updated observed state and event log.
8. Notify connected web clients over Socket.IO.

The event log should be structured and human-readable:

- `profile.created`
- `instance.start.requested`
- `instance.start.succeeded`
- `instance.health.failed`
- `instance.restart.succeeded`
- `auth.codex.needs-renewal`
- `base.prepare.failed`

## Security and trust model

- Manager runs as the local user, not root.
- Host exposure remains localhost-only by default.
- Admin passwords are stored in Keychain or equivalent secret storage.
- Provider OAuth state for sandboxed instances stays inside each sandbox home.
- Provider OAuth state for local instances is explicitly marked as host-native
  or profile-local.
- Workspace mounts are explicit and visible in the UI.
- The manager never deletes workspaces.
- The manager warns before sharing one sandbox home or instance home across
  profiles.
- Logs shown in the UI must redact known secrets and OAuth callback URLs.
- Support bundles must redact secrets by default.

## Migration from current commands

Phase 1 should wrap existing commands instead of rewriting everything. Local
profiles can wrap `bullpen.py`; sandboxed profiles can wrap `deploy-sandbox.py`.

Migration steps:

1. Add a small library boundary around deploy configuration construction and
   lifecycle actions, or invoke existing scripts as subprocesses with generated
   argument lists.
2. Create registry entries from the user's existing known-good commands.
3. Move admin password storage to Keychain or equivalent secret storage and
   reference it from the profile.
4. Move default sandbox home from `~/.bullpen/microsandbox-home` to per-profile
   homes for new sandboxed profiles.
5. Keep the old sandbox home as an imported profile if it exists.
6. Add one-click "Import existing sandboxed Bullpen" that detects:
   - sandbox name `bullpen`
   - home `~/.bullpen/microsandbox-home`
   - ports `8080` and `3000`
   - current workspace root if discoverable
7. Add "Import local Bullpen" for users who already run `bullpen.py` directly.

The old commands can remain documented as emergency recovery paths, not as the
primary user experience.

## Implementation phases

### Phase 0: Specification and decision

- Agree that instance lifecycle management is outside managed Bullpen
  instances.
- Choose Gen 1 web manager as the first shipping surface.
- Decide registry path and profile schema.
- Decide whether the manager code lives inside this repo initially or in a
  sibling package.

### Phase 1: Manager server and registry

- Implement Flask/Socket.IO manager server.
- Add Vue manager UI shell using Bullpen-compatible visual patterns.
- Add persistent registry.
- Support list/create/start/stop/restart/open/logs for local profiles.
- Generate `bullpen.py` invocations from local profiles.
- Store admin password in Keychain on macOS or a documented fallback elsewhere.

Done when:

- a user can run one manager command, open the manager URL, create a local
  Bullpen instance, and start it without deployment flags
- multiple local profiles start on distinct ports

### Phase 2: Microsandbox adapter

- Add Microsandbox runtime adapter.
- Support create/start/stop/restart/open/logs for sandboxed profiles.
- Generate `deploy-sandbox.py` invocations from sandboxed profiles.
- Support prepared base status and base preparation from the UI.
- Support import of existing default sandbox.
- Add provider status and renewal flows for sandboxed profiles.

Done when:

- from the same web manager, a user can create either a local or sandboxed
  Bullpen instance and start it without remembering command-line flags

### Phase 3: Reconciliation and repair

- Add desired-state reconciliation on manager startup.
- Add health checks and restart policy.
- Add setup wizard.
- Add instance detail pages.
- Add base snapshot screen.
- Add provider credential status and renewal actions.
- Add diagnostics and support bundle export.

Done when:

- a non-command-line user can create, start, stop, repair, and renew local and
  sandboxed instances from the web UI after starting the manager

### Phase 4: Optional service integration

- Add installer or `pipx` path.
- Add optional launchd user service management on macOS.
- Add optional systemd user service management on Linux.
- Add browser launch/open commands.
- Add host permission checks.

Done when:

- users who opt in can have the manager start at login or boot without manual
  command reconstruction

### Phase 5: Library extraction and deferred wrappers

- Move reusable local and sandbox deploy logic into stable Python package APIs.
- Keep `deploy-sandbox.py` as a compatibility wrapper.
- Remove duplicated command assembly from the manager.
- Reconsider Bullpen Desktop, Electron, Tauri, or hybrid wrappers only after
  the web manager lifecycle model works.

Done when:

- manager, CLI, and legacy commands use the same lifecycle library

### Phase 6: Deferred Docker runtime

- Add Docker runtime adapter.
- Support Docker profile creation from the same manager UI.
- Track Bullpen Docker images separately from Microsandbox base snapshots.
- Manage container create/start/stop/restart/open/logs.
- Support Docker volume mapping for workspace and instance home.
- Support Docker health checks and provider verification.

Done when:

- users who already have Docker available can launch a Docker-backed Bullpen
  instance from the same web manager without changing the local or Microsandbox
  flows

## Acceptance criteria

- User can create an instance profile once and start it later without remembering
  flags.
- User can choose local or Microsandbox runtime from the web UI.
- User can launch local Bullpen instances and sandboxed Bullpen instances from
  the same manager.
- The spec leaves a clear adapter path for Docker without making Docker a Gen 1
  dependency.
- User can start the manager with one terminal command and avoid per-instance
  command reconstruction.
- User can mark an instance as auto-start-when-manager-starts and have it come
  back when the manager is relaunched.
- User can manage at least ten named instances without port conflicts or shared
  state surprises.
- User can see which state is durable and which state is runtime-only.
- User can renew Claude, Codex, and GitHub auth per instance from a guided flow.
- User can rebuild or validate the prepared base without touching sandbox
  profiles.
- User can stop or delete an instance without risking workspace deletion.
- A failed restart leaves a visible actionable error, not a mystery dead port.
- The old local and sandbox deploy commands remain available for emergency use
  but are no longer the documented happy path.

## Open questions

- Should the Gen 1 manager live in this repository or a sibling package?
- Should local instances use host-native provider credentials by default, or
  profile-local homes by default?
- What is the safest cross-platform fallback for secret storage when Keychain is
  unavailable?
- Should the web manager embed Bullpen instance views in iframes, open them in
  new tabs, or support both?
- Should base snapshots be global to all profiles by default, or should users be
  able to pin a profile to an older base?
- How much of the Microsandbox SDK should be wrapped in a local service to avoid
  Python environment drift?
- Should optional Linux systemd user services ship in Gen 1 or wait?
- How should the manager detect and import a currently running detached sandbox
  when the SDK cannot execute commands inside it?
- Should Docker support depend on Docker Desktop, Colima, plain Docker Engine,
  or detect all of them?
- Should Docker profiles use built images from this repo, published images, or
  both?

## Design principle

`deploy-sandbox.py` proved the runtime can be built. The next layer must prove
the runtime can be lived with.

The unit of user intent is not a command line. It is a named Bullpen instance
with a remembered runtime type, remembered purpose, remembered mounts,
remembered ports, remembered credentials, and a desired state the computer can
reconcile on the user's behalf.
