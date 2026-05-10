# Implementation Plan — Microsandbox Agent Runtime

**Created:** 2026-05-07  
**Source:** [microsandbox-take-2.md](/Users/bill/aistuff/bullpen/docs/microsandbox-take-2.md)

---

## Objective

Implement the agreed Microsandbox runtime model with the smallest coherent
change set that can produce a first-light end-to-end test:

- Bullpen runs inside Microsandbox
- Claude, Codex, and GitHub-over-HTTPS git setup run inside Microsandbox
- install-time setup is a sequential TUI in `sandboxed-bullpen.py`
- setup happens per package: ask, run setup, verify, then advance
- provider auth is created inside the sandbox user's durable home
- provider setup state is created by native setup flows inside the VM

This implementation slice intentionally includes one acknowledged UX defect:

- Claude may require manual terminal fallback when the browser callback cannot
  reach localhost inside the sandbox

That is acceptable for first-light, but it should remain visible as a follow-up
item and not get normalized into the long-term UX.

This implementation slice intentionally excludes:

- Gemini setup
- installer resume-from-failure logic
- generic non-GitHub git auth support
- automatic localhost callback tunneling for Claude
- provider dashboards or provider status systems

---

## Decisions Carried Forward

These are no longer open questions for this plan:

1. **Claude first-light auth**
   - Use `claude auth login` inside the sandbox under a PTY.
   - Open the browser URL on the host when detected.
   - If callback delivery to localhost fails, rely on Claude Code's manual
     terminal fallback for now.

2. **Codex auth**
   - Use `codex login --device-auth`.

3. **Git setup scope**
   - GitHub only, over HTTPS, via GitHub CLI.
   - Use `gh auth login --git-protocol https`.

4. **Failure behavior under `--replace`**
   - If install-time setup fails after sandbox replacement, recovery is to rerun
     the full installer from the top.
   - No mid-sequence resume in this phase.

5. **Gemini**
   - Deferred.

---

## Current Code Surfaces

### Host launcher / sandbox orchestration

- [sandboxed-bullpen.py](/Users/bill/aistuff/bullpen/sandboxed-bullpen.py)
  - `build_arg_parser()`
  - `MicrosandboxRuntime.create()`
  - `run_sandbox_shell()`
  - `run_configured_sandbox_shell()`
  - `run_as_bullpen()`
  - `attach_as_bullpen()`
  - `run_install_tui()`
  - `run_auth_command()`
  - `run_test_provider_command()`
  - `install_codex_wrapper()`
  - `bootstrap_bullpen_credentials()`
  - `start_bullpen()`
  - `verify_admin_credentials()`
  - `verify_claude_auth()`
  - `verify_codex_auth()`
  - `verify_git_auth()`
  - `async_main()`

### Agent runtime adapters

- [server/agents/claude_adapter.py](/Users/bill/aistuff/bullpen/server/agents/claude_adapter.py)
- [server/agents/codex_adapter.py](/Users/bill/aistuff/bullpen/server/agents/codex_adapter.py)

These matter mostly for verification-command parity and Codex runtime flags.

### Existing tests

- [tests/test_sandboxed_bullpen.py](/Users/bill/aistuff/bullpen/tests/test_sandboxed_bullpen.py)
- [tests/test_agents.py](/Users/bill/aistuff/bullpen/tests/test_agents.py)

### Existing docs to update after implementation

- [README.md](/Users/bill/aistuff/bullpen/README.md)
- [docs/microsandbox.md](/Users/bill/aistuff/bullpen/docs/microsandbox.md)
- [docs/microsandbox-take-2.md](/Users/bill/aistuff/bullpen/docs/microsandbox-take-2.md)

---

## Implementation Shape

The implementation should preserve one strong separation:

- `sandboxed-bullpen.py` owns installation UX, browser brokering, PTY setup,
  and recovery messaging.
- Bullpen inside the VM remains the runtime service being installed.

Do not push the install TUI into the Bullpen web app in this slice.

Recommended internal structure additions inside `sandboxed-bullpen.py`:

- a small **interactive exec helper** for PTY-backed sandbox commands
- a **setup item abstraction** for Claude, Codex, and Git
- a **sequential install loop** that asks, runs setup, verifies, and advances
- distinct **setup** and **verification** entrypoints callable both from
  `--replace` and from repair commands

The implementation should keep provider setup inside the sandbox and avoid
reintroducing host-auth import assumptions into the normal path.

---

## Tranche 1 — Installer Foundations

**Goal:** Make `sandboxed-bullpen.py` capable of driving an interactive setup
session inside Microsandbox without yet changing all provider flows.

### T1.1 Add explicit command surface for setup and verification

Refactor [sandboxed-bullpen.py](/Users/bill/aistuff/bullpen/sandboxed-bullpen.py)
CLI parsing so it supports:

- deploy / replace flow
- `auth claude`
- `auth codex`
- `auth git`
- `test-provider claude`
- `test-provider codex`
- `test-provider git`

Recommended approach:

- preserve `python3 sandboxed-bullpen.py --replace` as the main install entry
- add subcommands or equivalent dispatch for auth/test operations

### T1.2 Add sandbox-state error classification

Introduce a helper that distinguishes:

- sandbox missing
- sandbox running but Bullpen unhealthy
- sandbox and Bullpen healthy

This should be used by auth/test commands and by the installer.

### T1.3 Add PTY-backed interactive exec helper

The current launcher uses `run_sandbox_shell()` / `run_as_bullpen()` for
noninteractive shell execution. Add a new helper that uses the Microsandbox SDK
streaming execution path with `tty=True`.

Recommended helper responsibilities:

- run command as sandbox user `bullpen`
- stream stdout/stderr line-by-line to the host terminal
- optionally detect URLs / auth instructions
- optionally open URLs on the host browser
- allow terminal input passthrough when the provider CLI prompts
- return exit status and captured output

This helper should be the only path used for interactive auth flows.

### T1.4 Preserve current deploy baseline while adding the new primitive

Do not yet delete the existing deploy sequence in this tranche. First add the
new command surface and PTY helper in a way that can be tested in isolation.

### T1.5 Tests

Add or update tests in
[tests/test_sandboxed_bullpen.py](/Users/bill/aistuff/bullpen/tests/test_sandboxed_bullpen.py)
for:

- CLI dispatch for auth/test commands
- sandbox state classification
- interactive exec helper command construction
- PTY enabled for interactive setup commands

**Checkpoint:** targeted launcher tests green.

---

## Tranche 2 — Keep The Happy Path Sandbox-Native

**Goal:** Keep the installer’s default model sandbox-native.

### T2.1 Keep provider setup inside the VM

The default `--replace` installer path should:

- create the sandbox
- boot Bullpen
- ask package-by-package whether to configure Claude, Codex, and Git
- run each selected provider’s setup flow inside the sandbox
- verify each selected provider with a real noninteractive command

### T2.2 Keep only the sandbox-home preparation that still matters

Keep:

- sandbox home permissions
- `~/.bullpen` creation
- logs directory creation
- Bullpen app credential bootstrap

Exclude from the normal path:

- external auth source selection
- external auth file import
- external GitHub token import

### T2.3 Reframe install preconditions

The installer should not fail up front because provider setup has not happened
yet. Instead, it should:

- boot the sandbox
- start Bullpen
- enter the sequential install TUI

### T2.4 Tests

Update tests to reflect:

- default install enters setup without preexisting provider state
- provider setup is deferred to install-time auth steps
- provider-related environment import is not the normal path

**Checkpoint:** deploy boots cleanly before provider setup.

---

## Tranche 3 — Claude Setup And Verification

**Goal:** Get one full sandbox-native provider flow working end to end.

Claude should be implemented first because it is the hardest path and drives the
first-light value of the architecture.

### T3.1 Implement `auth claude`

Run:

```bash
claude auth login
```

inside the sandbox as user `bullpen` under a PTY.

The launcher should:

- stream auth output live
- detect and display the login URL
- optionally open that URL on the host browser
- permit Claude’s manual terminal fallback if localhost callback delivery fails

### T3.2 Implement `test-provider claude`

Run the same noninteractive path Bullpen relies on later:

```bash
claude --print --output-format stream-json --verbose \
  --no-session-persistence --setting-sources user \
  --model claude-sonnet-4-6 "Reply OK only."
```

This should run inside the sandbox as user `bullpen`.

### T3.3 Wire Claude into `--replace`

In the per-package install loop:

- ask whether to set up Claude
- if yes, run `auth claude`
- immediately run `test-provider claude`
- only advance on verification success

### T3.4 Clarify failure messaging

If Claude auth/setup fails, error output should make clear whether:

- browser flow was not completed
- manual fallback was not completed
- verification failed after login

The retry instruction should always be:

```bash
python3 sandboxed-bullpen.py auth claude
python3 sandboxed-bullpen.py test-provider claude
```

### T3.5 Tests

Add launcher tests for:

- Claude auth command shape
- Claude verify command shape
- host-browser URL detection hook
- `--replace` sequencing: ask Claude -> auth Claude -> verify Claude
- failure path blocks progression

**Checkpoint:** Claude auth and verify both work in a live first-light sandbox.

---

## Tranche 4 — Codex Setup And Verification

**Goal:** Add the easier second provider on the same scaffolding.

### T4.1 Implement `auth codex`

Run:

```bash
codex login --device-auth
```

inside the sandbox as user `bullpen` under a PTY.

The launcher should:

- stream device-auth instructions
- surface the URL and code cleanly
- optionally open the URL on the host browser

### T4.2 Reuse existing Codex verification shape

The current deploy script already has a plausible Codex preflight. Reuse that
shape rather than inventing a new one:

- same runtime env as Bullpen uses later
- same `BULLPEN_CODEX_SANDBOX=none`
- same executable path and wrapper behavior if the wrapper remains necessary

### T4.3 Decide whether the existing Codex wrapper survives this slice

The current code installs a Codex wrapper to protect refresh persistence in
Microsandbox.

Recommended implementation rule:

- if the wrapper is still needed for runtime correctness, keep it
- but make Codex auth itself happen in the sandbox-native installation flow

Do not block the whole slice on eliminating the wrapper if the wrapper solves a
real Microsandbox refresh issue.

### T4.4 Wire Codex into `--replace`

In the per-package install loop:

- ask whether to set up Codex
- if yes, run `auth codex`
- immediately run `test-provider codex`
- only advance on verification success

### T4.5 Tests

Add tests for:

- Codex auth command uses `--device-auth`
- Codex verification matches runtime path
- install loop sequencing around Codex
- wrapper integration, if retained

**Checkpoint:** Codex auth and verify work after Claude on the same installer.

---

## Tranche 5 — GitHub HTTPS Git Setup

**Goal:** Add the agreed Git scope and no more.

### T5.1 Define Git setup steps concretely

Git in this slice means:

1. configure `git config --global user.name`
2. configure `git config --global user.email`
3. run `gh auth login --git-protocol https`
4. run `gh auth setup-git`

Prompts for `user.name` / `user.email` may come from:

- install TUI input, or
- environment/defaults already provided by the user

Do not expand scope to SSH or generic non-GitHub remotes here.

### T5.2 Implement `auth git`

`auth git` should run the GitHub CLI auth flow inside the sandbox under a PTY
and then apply `gh auth setup-git`.

### T5.3 Implement `test-provider git`

Use a verification path that proves the configured repo can use HTTPS auth.

Recommended layered verification:

1. `gh auth status --hostname github.com`
2. if the current repo remote is GitHub and reachable, run a non-mutating git
   operation such as:

```bash
git ls-remote origin HEAD
```

This second step matters because it exercises git through the configured
credential helper rather than only checking GH CLI account state.

### T5.4 Wire Git into `--replace`

In the per-package install loop:

- ask whether to set up Git
- if yes, run `auth git`
- immediately run `test-provider git`

### T5.5 Tests

Add tests for:

- Git setup command sequence
- Git verification command sequence
- install loop sequencing around Git
- GitHub-only scope assumptions

**Checkpoint:** GitHub HTTPS setup succeeds inside the sandbox without host key
or credential import.

---

## Tranche 6 — Sequential Install TUI

**Goal:** Replace the current deploy “boot and preflight” flow with the agreed
per-package installer.

### T6.1 Add setup item abstraction

Recommended simple structure inside
[sandboxed-bullpen.py](/Users/bill/aistuff/bullpen/sandboxed-bullpen.py):

```python
SetupItem(
    key="claude",
    label="Claude",
    auth_fn=...,
    verify_fn=...,
)
```

Equivalent items for:

- Codex
- Git

### T6.2 Implement sequential TUI loop

For each item in order:

1. ask yes/no
2. if no, record skipped and continue
3. if yes, run setup
4. run verification
5. if verification succeeds, continue
6. if setup or verification fails, abort installer

Do not implement resume.

### T6.3 Integrate with `--replace`

After:

- sandbox creation
- mount verification
- Bullpen start
- Bullpen health verification
- Bullpen admin credential verification

then enter the install TUI.

Installer success means:

- all selected items verified
- sandbox detached and healthy

### T6.4 Tests

Add tests for:

- ordered presentation: Claude -> Codex -> Git
- no later prompt until current item is skipped or verified
- full-install success path
- full-install abort on selected-item failure

**Checkpoint:** `python3 sandboxed-bullpen.py --replace` performs the full
install-time setup loop.

---

## Tranche 7 — Cleanup, Documentation, And Removal Of Obsolete Paths

**Goal:** Remove old assumptions once the new flow is proven.

### T7.1 Remove obsolete provider-seeding code from normal operation

After the new install flow is working, remove or quarantine old logic for:

- Claude external source selection
- Claude auth-file import
- Codex auth-file import
- external GitHub auth import

If transitional compatibility hooks remain, document them as non-default and
not part of the normal Microsandbox install path.

### T7.2 Update docs

Update:

- [README.md](/Users/bill/aistuff/bullpen/README.md)
- [docs/microsandbox.md](/Users/bill/aistuff/bullpen/docs/microsandbox.md)

to describe:

- sandbox-native auth
- per-package install TUI
- Claude manual fallback limitation
- GitHub-over-HTTPS-only Git scope

### T7.3 Add operational note for the Claude UX defect

Document the current open sore explicitly:

- Claude first-light may require copying or pasting a code/URL back into the
  terminal when localhost callback delivery fails inside the VM

This should be listed as follow-up work, not buried as normal behavior.

### T7.4 Final tests

Run:

- targeted launcher/unit tests
- provider command tests
- `tests/test_sandboxed_bullpen.py`
- `tests/test_agents.py`

**Checkpoint:** docs and code agree on the new Microsandbox install model.

---

## Risk Areas

### 1. Claude auth UX remains rough

This is the main known product blemish in the slice. It is acceptable for
first-light but should be tracked explicitly as follow-up work.

### 2. Codex wrapper may still be necessary

The spec aims for minimal CLI interference, but if the current wrapper is still
solving real Microsandbox refresh persistence problems, removing it too early
would be self-defeating.

### 3. Git verification depends on repo shape

`git ls-remote origin HEAD` is a strong verification for GitHub HTTPS auth, but
the installer needs a graceful behavior when:

- the repo has no `origin`
- the remote is not GitHub
- the user selected Git setup in a workspace that is not a git repo

Recommended v1 behavior:

- if no usable GitHub remote is present, verify `gh auth status` and global git
  config, then warn that remote verification was skipped

### 4. Interactive auth under PTY can still surprise us

The SDK supports `tty=True`, but provider-specific prompt behavior may still
need one or two rounds of polish once exercised in a real sandbox.

---

## Suggested Ticket Breakdown

1. Launcher command surface + PTY exec helper
2. Sandbox-state classification and failure messaging
3. Keep provider setup state inside the VM
4. Claude auth command
5. Claude verify command
6. Codex auth command
7. Codex verify command
8. GitHub HTTPS git setup command
9. Git verify command
10. Sequential install TUI wiring
11. Docs update and obsolete-path cleanup

These should be executed in order. Tickets 4 and 5 are the first meaningful
first-light milestone.

---

## Implementation Readiness

This feature is ready for implementation planning and ticketing.

Nothing material remains architecturally ambiguous for this slice. The main
remaining uncertainty is quality-of-experience, not technical direction:

- Claude manual fallback is ugly, but accepted for first-light
- Git is intentionally narrowed to GitHub-over-HTTPS via `gh`
- Gemini is out of scope
- install failure semantics are explicitly “rerun from the top”

That is enough clarity to start implementation without reopening the design.
