# Microsandbox Agent Runtime Specification

## Purpose

Bullpen Microsandbox mode runs Bullpen, Claude, Codex, git, shell
commands, and agent child processes inside a Microsandbox VM. The security
boundary is
the point of the feature: the agent runtime itself lives inside the hypervisor,
not merely its tool calls.

The design goal is to make the sandbox look like a normal Linux machine and
then leave provider CLIs as untouched as possible.

## Scope

This specification covers:

- Bullpen running inside Microsandbox
- Claude, Codex, and git running inside Microsandbox
- sandbox installation and first-run setup
- install-time TUI-driven selection of provider and git setup
- authentication during initial sandbox installation
- verification using the same noninteractive paths that Bullpen later uses for
  Agent Chat and workers
- persistent sandbox state needed across sandbox replacement

## Product Invariant

Bullpen must run agent CLIs inside the Microsandbox VM.

Provider login commands and provider runtime commands must execute as the same
sandbox user using the same durable home directory. That is the key runtime
invariant. The literal path may change; the invariant may not.

## Architecture

Microsandbox mode uses one long-running VM per Bullpen deployment.

```text
Host
  deploy-sandbox.py
  Browser
  <workspace directory>
  Persistent sandbox home directory

Microsandbox VM
  /app
  /workspace
  <sandbox user's durable home>

  Processes
    Bullpen server
    Claude Code CLI
    Codex CLI
    Git and GitHub CLI
    Agent-launched shell commands
```

The host is responsible for:

- launching or replacing the VM
- forwarding Bullpen ports
- bind-mounting the project workspace
- bind-mounting the sandbox user's durable home
- brokering browser-based login flows initiated from inside the sandbox
- allocating a PTY for interactive setup subprocesses
- opening detected login URLs on the host when requested
- supporting browser-based auth fallback paths needed by sandboxed provider
  logins

The VM is responsible for:

- running Bullpen
- running provider CLIs
- holding provider auth/config state in the sandbox user's home
- executing all agent-driven filesystem, shell, and git activity

## Sandbox Filesystem Model

The sandbox contains three important roots:

```text
/app
/workspace
<sandbox user's durable home>
```

`/workspace` is the mounted project. Agents do project work there.

`/app` contains Bullpen code. It may be read-only.

The sandbox user's durable home holds ordinary user-level state for software
running in the VM. In the current implementation that home is
`/home/bullpen`, because the sandbox user is `bullpen`. The abstract
requirement is not the string `/home/bullpen`; the requirement is that the same
sandbox user and the same durable home are used for both provider login and
provider runtime.

Provider CLIs use their normal Linux paths under that home. Examples include:

```text
~/.claude
~/.claude.json
~/.codex
~/.config/gh
~/.gitconfig
```

Bullpen also needs writable application state inside the VM. That state lives
under:

```text
~/.bullpen
```

This is required because Bullpen cannot rely on `/app` being writable, but it
still needs persistent writable state for its own operation.

## Functional Requirements

Bullpen Microsandbox mode must satisfy all of the following:

1. Bullpen runs inside Microsandbox.
2. Claude runs inside Microsandbox.
3. Codex runs inside Microsandbox.
4. Git runs inside Microsandbox.
5. Agent child processes run inside Microsandbox.
6. Project filesystem work happens inside `/workspace`.
7. The sandbox user has a durable writable home directory.
8. Claude login and Claude runtime use the same sandbox user and the same
   durable home.
9. Codex login and Codex runtime use the same sandbox user and the same
    durable home.
10. Git setup and Git runtime use the same sandbox user and the same durable
    home.
11. Initial sandbox installation includes a TUI that walks through Claude,
    Codex, and Git, asking whether to set up each one.
12. For each component selected in the TUI, initial sandbox installation runs
    the corresponding auth or setup ritual and then verifies it.
13. Verification uses a real noninteractive model-call path for agent
    providers, not account metadata.
14. A sandbox installation is not considered complete until every selected
    component verifies successfully.
15. Provider CLIs manage their own files inside the sandbox home using their
    native conventions.
16. Bullpen does not impose provider-specific home-directory remapping unless a
    concrete provider bug makes that unavoidable.
17. Claude first-light auth may rely on the CLI's manual fallback when the
    browser callback cannot reach localhost; this is acceptable for early
    feasibility and remains an explicit UX defect to address.
18. Initial Git setup scope is GitHub over HTTPS via GitHub CLI only.
19. Failed install-time setup under `--replace` requires rerunning the full
    installer from the beginning rather than resuming mid-sequence.

## Initial Sandbox Installation

Initial sandbox installation is a guided TUI setup flow, not just VM creation.

The default installation sequence is:

1. Create or replace the Microsandbox VM.
2. Mount the selected project workspace into `/workspace`.
3. Mount the persistent sandbox home into the sandbox user's home directory.
4. Start Bullpen inside the VM.
5. Verify Bullpen health and admin credentials.
6. Present a TUI that walks through Claude, Codex, and Git in order.
7. For the current item, ask whether the user wants to set it up in this
   sandbox.
8. If the user selects yes, immediately run that item's setup or auth flow
   inside the sandbox as the sandbox user.
9. Immediately after setup, run that same item's verification step.
10. Then advance to the next item in the list.
11. Mark the sandbox ready only after every selected item verifies
    successfully.

From the user's perspective, installing Microsandbox means:

- Bullpen comes up in the VM
- the installer handles Claude, then Codex, then Git
- each item is asked, set up, and tested before the installer moves to the
  next one
- each selected item is authenticated or configured in the VM during install

The user should not have to perform a separate post-install “now go authenticate
things” ritual in the normal successful path. That work belongs to the initial
sandbox installation flow.

## Installation UX

The installer must drive the setup steps in order and show clear progress.

Required behavior:

1. After Bullpen itself is healthy, the installer enters provider setup.
2. The TUI presents Claude, Codex, and Git one at a time.
3. For the current item, the TUI asks whether to set it up now.
4. If the user declines the current item, the installer marks it skipped and
   advances to the next item.
5. If the user accepts the current item, the installer launches its setup flow
   inside the sandbox.
6. Interactive setup flows run under a PTY, with their output streamed to the
   TUI.
7. If the setup flow emits a login URL or device-auth instructions, the
   installer displays them and may open the URL on the host.
8. If Claude's browser callback cannot reach localhost inside the sandbox, the
   installer supports the CLI's manual fallback path in the terminal.
9. After the setup flow exits, the installer immediately runs verification for
   that same item.
10. Only after that item completes successfully does the installer advance to
    the next item.
11. The installer reports success only when every selected item has verified.

If a setup or verification step fails, installation fails with item-specific
output and a retry command. The sandbox may still exist, but it is not treated
as ready for Bullpen Agent Chat or workers until the full installer is rerun
successfully from the start. This phase does not include installer resume
logic.

## Browser-Assisted Authentication

Browser-based authentication is a host-assisted sandbox workflow.

For any provider whose setup flow requires browser interaction, Bullpen must:

1. launch the provider setup subprocess inside the sandbox under a PTY
2. stream subprocess output to the install TUI
3. detect login URLs or device-auth instructions in subprocess output
4. display the URL or code in the TUI
5. optionally open the URL on the host browser
6. keep the sandbox-side setup subprocess running until it completes or times
   out
7. immediately run verification after setup exits

The host acts only as browser and terminal bridge. Authentication state remains
inside the sandbox user's durable home.

For first-light Claude support, Bullpen may rely on Claude Code's manual
terminal fallback when the browser callback cannot reach localhost. That is
acceptable for early feasibility testing because it avoids building callback
tunneling before the sandbox-native auth model is proven. It is also an
explicitly subpar UX and should be treated as an open sore to fix.

## Setup and Authentication

Provider authentication and git setup are performed inside Microsandbox as the
sandbox user.

Bullpen must expose installation-time launcher commands that run each selected
component's native setup flow inside the VM. These commands are primarily used
by the installer, but they also provide a repair path later if a component
needs to be set up again.

Claude login launcher:

```bash
python3 deploy-sandbox.py auth claude
```

Equivalent sandbox action:

```bash
msb exec bullpen -- su -s /bin/bash bullpen -c 'claude auth login'
```

Claude setup is expected to use Bullpen's browser-assisted auth path. The
installer must be prepared to open the login URL on the host. In this phase,
Bullpen may rely on Claude Code's manual fallback when the browser callback
cannot reach localhost.

Codex login launcher:

```bash
python3 deploy-sandbox.py auth codex
```

Equivalent sandbox action:

```bash
msb exec bullpen -- su -s /bin/bash bullpen -c 'codex login --device-auth'
```

Codex setup should prefer device auth by default. That avoids unnecessary
browser-callback complexity in the common path.

Git setup launcher:

```bash
python3 deploy-sandbox.py auth git
```

Git setup configures git for use inside the sandbox as the sandbox user. That
includes any required identity, credential, or remote-auth ritual Bullpen
chooses to support for GitHub over HTTPS via GitHub CLI.

The launcher contract is:

- attach to the running sandbox
- run as the sandbox user
- use the sandbox user's durable home
- allocate a PTY for any interactive setup flow
- stream provider output
- return the provider CLI exit status

## Verification

Verification must run inside Microsandbox and use the same runtime context
Bullpen will later use:

- same sandbox user
- same durable home
- same CLI
- same relevant command-line flags or environment

Metadata commands are not verification. For Claude, `claude auth status` is
useful for inspection but is not sufficient proof that Bullpen's noninteractive
runtime path works.

Claude verification launcher:

```bash
python3 deploy-sandbox.py test-provider claude
```

Equivalent sandbox action:

```bash
msb exec bullpen -- su -s /bin/bash bullpen -c \
  'claude --print --output-format stream-json --verbose \
    --no-session-persistence --setting-sources user \
    --model claude-sonnet-4-6 "Reply OK only."'
```

Codex verification launcher:

```bash
python3 deploy-sandbox.py test-provider codex
```

The exact Codex verification command should be the same noninteractive command
Bullpen later uses when driving Codex in Microsandbox mode, with any required
Bullpen-specific environment applied.

Git verification launcher:

```bash
python3 deploy-sandbox.py test-provider git
```

Git verification should prove that git is usable inside the sandbox for the
current workspace and that GitHub-over-HTTPS auth via GitHub CLI succeeds for
the expected remote operations.

Verification behavior:

- print concise success or failure
- include provider error text useful for diagnosis
- return nonzero on failure
- run immediately after the corresponding setup step during initial install

## Runtime Behavior

After installation completes, Bullpen launches selected agent providers inside
the Microsandbox VM using the same sandbox user and durable home that were used
during setup.

### Claude

Bullpen launches Claude inside Microsandbox as the sandbox user.

Baseline Claude invocation includes:

```text
--print
--output-format stream-json
--verbose
--dangerously-skip-permissions
--no-session-persistence
--setting-sources user
--strict-mcp-config
--mcp-config <Bullpen MCP config>
```

### Codex

Bullpen launches Codex inside Microsandbox as the sandbox user.

Codex runs with:

```text
BULLPEN_CODEX_SANDBOX=none
```

This disables nested Codex sandboxing inside the Microsandbox VM.

### Git

Bullpen launches git operations inside Microsandbox as the sandbox user.

## Worker and Agent Chat Behavior

Workers and Agent Chat use the provider runtimes that were selected,
authenticated, and verified during installation.

If a provider later becomes unauthenticated or otherwise unusable, Bullpen
surfaces the provider's output in the existing places users already look:

- Agent Chat output
- worker output
- worker log/history output

Bullpen must show a concrete repair command, for example:

```text
Claude authentication failed inside Microsandbox.
Run:  python3 deploy-sandbox.py auth claude
Then: python3 deploy-sandbox.py test-provider claude
```

## CLI Surface

Microsandbox support requires these commands in `deploy-sandbox.py`:

```bash
python3 deploy-sandbox.py --replace
python3 deploy-sandbox.py auth claude
python3 deploy-sandbox.py auth codex
python3 deploy-sandbox.py auth git
python3 deploy-sandbox.py test-provider claude
python3 deploy-sandbox.py test-provider codex
python3 deploy-sandbox.py test-provider git
```

Expected behavior:

- `--replace` performs VM creation and launches the install TUI
- the install TUI walks through Claude, Codex, and Git one at a time
- each item is asked, optionally set up, and verified before the TUI advances
  to the next item
- `auth <provider>` re-runs provider login inside the sandbox
- `test-provider <provider>` re-runs provider verification inside the sandbox

Failure handling must distinguish at least these cases:

- no sandbox is running
- the sandbox is running but Bullpen inside it is unhealthy
- the sandbox and Bullpen are healthy but the selected setup or verification
  step failed

Provider commands print a clear recovery message for the specific failure mode
and return nonzero.

## Security Requirements

Microsandbox mode must preserve these boundaries:

- Bullpen runs inside the VM
- Claude runs inside the VM
- Codex runs inside the VM
- agent shell commands run inside the VM
- provider login runs inside the VM
- provider verification runs inside the VM
- project filesystem access happens through `/workspace`
- Bullpen application state is persisted in the sandbox user's durable home

The host is allowed to orchestrate the sandbox and assist with browser-based
login interaction, but it does not become the runtime location for Claude or
Codex in Microsandbox mode.

## Implementation Requirements

1. `deploy-sandbox.py --replace` must launch the install TUI, not stop after
   merely booting Bullpen.
2. The install TUI must walk through Claude, Codex, and Git in order.
3. The install TUI must process one item at a time.
4. For each item, the TUI must ask whether to set it up.
5. If selected, setup must run inside the sandbox before the TUI advances.
6. If selected, verification must run immediately after setup and before the
   TUI advances.
7. Interactive setup flows must run under a PTY.
8. Browser-based setup flows must support URL display plus optional host
   browser opening.
9. Claude setup may rely on manual terminal fallback when localhost callback
   delivery fails; this must be documented as temporary.
10. Installation success must require verification of every selected item.
11. Bullpen runtime commands for Claude, Codex, and git must use the
   same sandbox user and durable home used during setup.
12. Provider CLIs must run against their native filesystem layout under the
   sandbox home.
13. `~/.bullpen` must exist and be writable inside the sandbox home for Bullpen
   application state.
14. Codex runtime must include `BULLPEN_CODEX_SANDBOX=none`.
15. Codex setup should prefer `codex login --device-auth`.
16. Git setup scope is GitHub over HTTPS via GitHub CLI only.
17. Failed install-time setup under `--replace` requires rerunning the full
    installer from the start rather than resuming mid-sequence.

## Acceptance Tests

### Initial Installation

1. Run `python3 deploy-sandbox.py --replace`.
2. Confirm that the installer boots the VM and starts Bullpen.
3. Confirm that the TUI presents Claude first.
4. Select Claude.
5. Confirm that Claude login launches immediately.
6. Complete Claude login.
7. Confirm that the installer surfaces the browser URL on the host side.
8. If Claude's browser callback cannot reach localhost, confirm that the
   installer supports the CLI's manual fallback path in the terminal.
9. Confirm that Claude verification runs automatically and succeeds before the
   TUI advances.
10. Confirm that the TUI then presents Codex.
11. Select Codex.
12. Confirm that Codex login launches immediately in device-auth mode.
13. Complete Codex login.
14. Confirm that Codex verification runs automatically and succeeds before the
    TUI advances.
15. Confirm that the TUI then presents Git.
16. Skip Git.
17. Confirm that skipped items are recorded as skipped.
18. Confirm that the install reports success only after selected items verify.

### Claude Runtime

1. Complete initial installation.
2. Send a Claude Agent Chat message.
3. Run a Claude worker.
4. Replace the sandbox while preserving the durable home.
5. Confirm that Claude still runs without requiring a new login when persisted
   credentials remain valid.

### Codex Runtime

1. Complete initial installation.
2. Run a Codex Agent Chat session or Codex worker.
3. Confirm that Codex runs inside Microsandbox with
   `BULLPEN_CODEX_SANDBOX=none`.
4. Replace the sandbox while preserving the durable home.
5. Confirm that Codex still runs without requiring a new login when persisted
   credentials remain valid.

### Git Runtime

1. Complete initial installation with Git selected.
2. Confirm that Git setup runs during install.
3. Confirm that Git verification runs during install.
4. Perform a sandboxed git operation in `/workspace`.

### Verification Semantics

1. Make Claude account metadata available but break the actual model-call path.
2. Confirm that Claude verification fails.
3. Confirm that installation does not report success.

### Failure Modes

1. Invoke a provider command when no sandbox is running.
2. Confirm that Bullpen reports the sandbox-missing recovery path.
3. Start the sandbox but leave Bullpen unhealthy.
4. Confirm that provider commands report the Bullpen-unhealthy recovery path.
5. Start a setup flow and force provider auth failure.
6. Confirm that Bullpen reports the provider-specific failure and retry path.
7. Confirm that recovery is documented as rerunning the full installer from
   the beginning.

### Automated Tests

- installer presents Claude, Codex, and Git in order
- installer does not ask about a later item until the current item's setup and
  verification path is complete or skipped
- installer records selected and skipped items
- installer invokes Claude auth when Claude is selected
- installer invokes Claude verification when Claude is selected
- Claude auth runs under a PTY
- Claude auth surfaces the login URL to the host side
- Claude auth supports the CLI's manual fallback when localhost callback
  delivery fails
- installer invokes Codex auth when Codex is selected
- installer invokes Codex verification when Codex is selected
- Codex auth uses device-auth mode by default
- installer invokes Git setup when Git is selected
- installer invokes Git verification when Git is selected
- installation fails if a selected item's verification fails
- failed setup under `--replace` requires rerunning the full installer
- provider commands distinguish sandbox-missing from Bullpen-unhealthy failures
- provider launcher commands run as the sandbox user
- provider launcher commands use the sandbox user's durable home
- `~/.bullpen` is writable inside the sandbox home
- Codex runtime includes `BULLPEN_CODEX_SANDBOX=none`

## User Documentation

User-facing docs should describe Microsandbox mode this way:

> Microsandbox mode treats the sandbox as the agent machine. Bullpen, Claude,
> Codex, git, shell commands, and agent child processes all run inside
> the VM. During initial sandbox installation, Bullpen presents a setup TUI
> that walks through Claude, Codex, and Git, asking whether to set up
> each one. For every selected item, Bullpen performs setup inside the sandbox
> and verifies it before marking the sandbox ready.

The normal setup example is:

```bash
python3 deploy-sandbox.py --replace
```

That command should perform the full installation flow, including the setup TUI
and setup plus verification for each selected item.

## Commentary

### Architectural judgment

The core architectural call in this spec is sound: credentials are created and
stored inside the sandbox user's durable home, and Bullpen later runs the same
CLIs under that same sandbox identity. That directly matches how these tools
expect to work and eliminates the brittle legacy setup path.

The strongest line in the document remains the simplest one: same sandbox user,
same durable home, for both login and runtime. That is the right invariant to
design around and the right invariant to test.

The verification requirement is also correct. Real noninteractive model calls
must be the source of truth. Metadata commands like `claude auth status` are
useful for inspection but are not health checks.

### Browser-based auth: concrete design

This is the part that needs to be specified more concretely than the main body
currently does.

The install TUI should treat browser-based auth as a host-assisted sandbox
workflow:

1. Bullpen starts the provider login command inside the sandbox under a PTY.
2. Bullpen streams that PTY output to the install TUI.
3. Bullpen watches the output for a login URL or device-auth instructions.
4. When a URL is detected, Bullpen offers to open it on the host browser and
   also prints it for manual copy/open.
5. Bullpen keeps the sandbox-side auth subprocess running until it either
   completes or times out.
6. On subprocess exit, Bullpen immediately runs the provider verification step
   in the sandbox.

That general pattern works for all providers. The hard part is the callback path
for providers that use OAuth with a localhost redirect.

The right first-light rule is:

- If the provider supports a device-auth or copy/paste flow, prefer that.
- If the provider supports a manual terminal fallback when the browser callback
  cannot reach localhost, prefer that before building callback-tunnel
  machinery.

For Claude specifically, `claude auth login --help` exposes `--claudeai`,
`--console`, `--email`, and `--sso`, but not an obvious device-code or
print-URL flag. The more important fact is that recent Claude Code builds
support a manual terminal fallback when the browser callback cannot reach
localhost. That makes Claude feasible for first-light without callback
tunneling, at the cost of a notably rough UX. The spec should treat that as a
temporary compromise, not the desired end state.

For Codex, `codex login --help` exposes `--device-auth` and `--with-api-key`.
That means Codex should not require localhost callback forwarding in the common
path. The install TUI should prefer `codex login --device-auth` for interactive
setup because it is simpler and clearer.

Gemini is no longer part of this implementation slice and should be deferred
until one concrete Microsandbox-compatible setup path is proven.

### Browser-auth implementation requirements implied by this

If Bullpen adopts the browser-auth design above, the implementation needs a
small host-side auth helper with these responsibilities:

- run an interactive sandbox auth subprocess under a PTY
- parse stdout/stderr for URLs or auth instructions
- optionally open a detected URL on the host
- return the provider subprocess exit status and captured output to the TUI

That helper is part of the host launcher, not part of the provider CLIs and not
part of the Bullpen server inside the VM.

The clean mental model is:

- provider auth state lives in the sandbox
- provider auth interaction is brokered by the host

That still preserves the product boundary because the provider runtime is inside
the VM; the host is only acting as the user's browser and local terminal bridge.

### PTY handling should be mandatory

The review comment about TTY behavior is right. Interactive auth commands should
always run under a PTY. That should be promoted from an implementation note to a
hard requirement for install-time auth.

Without a PTY, CLIs may:

- change their login flow
- suppress prompts
- suppress URLs
- buffer output in confusing ways

So the install TUI should never launch Claude, Codex, or GitHub CLI auth in a plain
pipe-only subprocess.

### Git setup should stay narrow

The first supported path is now concrete:

- configure `user.name` and `user.email` inside the sandbox
- use GitHub CLI with HTTPS auth inside the sandbox
- verify the chosen mechanism with the repository's actual remote operations

What should not be added is any dependency on importing the host's SSH key,
credential helper, or git auth cache into the sandbox.

### Failure-state handling

The commentary correctly points out a missing distinction between:

- no sandbox is running
- the sandbox is running but Bullpen inside it is unhealthy

Those need different error messages and different recovery actions. The CLI
surface should reflect that distinction.

Because `--replace` destroys and recreates the sandbox, this phase should not
attempt mid-installer resume. If setup fails, the recovery path is to rerun the
full installer and re-establish the install-time invariants from the top.

### Recommended implementation order

The suggested build order is good and worth following:

1. Get `--replace` reliably booting the VM, mounting the durable home, starting
   Bullpen, and checking health.
2. Get one verification path working end to end, starting with Claude.
3. Get one browser-auth path working end to end, including PTY handling and
   Claude's manual fallback path.
4. Build the per-package install TUI on top of those working primitives.
5. Add Codex and Git setup flows using the same scaffolding.

That order reduces the chance that the TUI hides lower-level auth and process
control bugs.
