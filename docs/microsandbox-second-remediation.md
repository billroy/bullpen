# Microsandbox Second Remediation Analysis

Date: 2026-05-10

## Context

This review was triggered by a Claude worker regression where workers failed
immediately with:

```text
[BLOCKED] Claude CLI is not available or not authenticated.
```

The root cause was a Microsandbox-era auth hardening change that made
`ClaudeAdapter.available()` depend on a narrow legacy OAuth-file preflight:
`~/.claude/.credentials.json` with `claudeAiOauth` token material. That was
incorrect for current Claude Code login behavior and caused Bullpen to reject
Claude before launching the CLI.

Commit `de4b576` repaired that immediate regression by:

- restoring Claude adapter availability to executable-only,
- only setting isolated `CLAUDE_CONFIG_DIR` when a usable legacy
  `.credentials.json` is actually copied,
- removing unsupported `ANTHROPIC_API_KEY` product support from Claude and
  Docker paths,
- preserving generic secret filtering for `ANTHROPIC_API_KEY`.

This document records a second-pass retrospective over the Microsandbox and
Docker deployment/auth changes to identify similar regression risks.

## Review Range

Primary review range:

```text
a7b069d Add Microsandbox deployment checkpoint
through
de4b576 fix: restore Claude worker auth handling
```

Reviewed surfaces:

- `sandboxed-bullpen.py`
- `deploy/microsandbox/prepare.sh`
- `deploy-docker.sh`
- `deploy/docker/entrypoint.sh`
- `server/agents/claude_adapter.py`
- `server/agents/codex_adapter.py`
- `tests/test_sandboxed_bullpen.py`
- `tests/test_agents.py`
- Microsandbox and Docker docs

Docker auth commits before the Microsandbox checkpoint were also considered
where they overlap the same deployment/auth behavior.

## Main Pattern

The strongest recurring issue is treating a file or directory presence check as
equivalent to provider auth truth.

That pattern caused the Claude worker regression directly:

- old behavior: Claude available if executable exists,
- regressed behavior: Claude available only if Bullpen recognizes a specific
  `.credentials.json` shape,
- actual desired behavior: Claude available if executable exists; Claude CLI is
  the source of truth for whether its login state can make a model call.

The same pattern still appears in Docker and Microsandbox setup. Some uses are
diagnostic and acceptable; others are product behavior and can skip setup,
print misleading warnings, or block a real verification path.

## Findings

### P1: Docker Still Treats Claude Metadata As Usable Credentials

Relevant code:

- `deploy-docker.sh:281` defines `claude_logged_in()` as only:

```bash
[[ -s "$DOCKER_HOME/.claude/.credentials.json" ]]
```

- `deploy-docker.sh:486` counts any `$DOCKER_HOME/.claude` directory as a
  detected credential source.
- `deploy-docker.sh:487` counts any `$DOCKER_HOME/.claude.json` file as a
  detected credential source.
- `deploy-docker.sh:515` skips the credential prompt when any provider
  credential source was detected.
- `deploy-docker.sh:578` warns if `claude_logged_in()` fails.

Risk:

Docker can skip credential prompting because metadata exists, then later warn
that Claude is not logged in because `.credentials.json` is absent. After
`ANTHROPIC_API_KEY` removal, this is sharper: there is no longer an API-key
fallback to mask the issue.

This can produce a deployment that looks mostly successful but has non-working
Claude workers.

Likely origin:

- `a67f305` introduced Docker Claude auth wiring and metadata seeding.
- `fd1ff71` made Docker login detection depend on `.credentials.json`.
- Later commits improved messaging but did not resolve the contradictory
  credential detection model.

Desired behavior:

Docker should distinguish:

- provider metadata copied into the Docker home,
- a verified provider login,
- provider setup skipped by user,
- provider unavailable but other providers usable.

Recommended remediation:

1. Stop counting `$DOCKER_HOME/.claude` and `$DOCKER_HOME/.claude.json` as
   sufficient provider credentials for prompt suppression.
2. Treat Claude Code auth as verified only by either:
   - a real `HOME="$DOCKER_HOME" claude --print ...` probe, or
   - a documented legacy `.credentials.json` check explicitly labeled as
     weaker and transitional.
3. If no verified provider auth exists, prompt for provider setup or print a
   clear "installed but unverified" warning.
4. Keep Docker deploy success independent of Claude if the user only wants
   Codex/Gemini, but make the provider matrix explicit.

Suggested tests:

- Docker deploy script does not treat `.claude.json` alone as usable Claude
  auth.
- Docker deploy script does not treat `.claude/` directory alone as usable
  Claude auth.
- Docker deploy script reports Claude as unverified unless a real login marker
  or probe succeeds.
- Docker deploy script can still proceed when Codex or Gemini credentials are
  verified and Claude is unverified.

### P2: Claude First-Light Still Gates On `.credentials.json`

Relevant code:

- `sandboxed-bullpen.py:1216` defines `verify_claude_credentials_file()`.
- It requires `/home/bullpen/.claude/.credentials.json`.
- `sandboxed-bullpen.py:1456` runs this verifier before the real Claude model
  call in first-light.

Risk:

This can recreate the same class of auth-format regression just fixed in the
main Claude adapter. If a future Claude Code login succeeds but stores auth in
a different location or format, first-light fails before the real source of
truth (`claude --print`) is allowed to decide.

The file check is useful for the current Microsandbox OAuth path, but it should
be diagnostic, not authoritative.

How the current path works:

1. First-light creates a sandbox with `/home/bullpen` bind-mounted to the
   configured Microsandbox home.
2. `auth_claude()` runs `claude auth login` inside the sandbox as the
   `bullpen` user.
3. Current Claude Code versions are expected to write OAuth material to
   `/home/bullpen/.claude/.credentials.json`.
4. `verify_claude_credentials_file()` then parses that file and requires either
   `accessToken` or `refreshToken`.
5. Only after that file check passes does `verify_claude_auth()` run a real
   `claude --print` probe.

That ordering is the problem. It treats a currently observed implementation
artifact as the contract. The contract Bullpen actually needs is: "Can the
headless Claude CLI make a minimal noninteractive model call from the same user
and home directory Bullpen workers will use?"

Blast radius of the proposed change:

- Positive: first-light becomes robust to Claude Code changing where it stores
  login state, as long as the real CLI can still make the model call.
- Positive: the installer stops blocking on stale assumptions before the real
  provider check runs.
- Neutral for current `.credentials.json` users: the same file can still be
  inspected and reported.
- Risk: if `claude --print` succeeds while writing no durable credentials,
  first-light may pass even though later runs fail after process/session state
  expires. That risk can be controlled by doing durability checks after the
  real probe, not before it.
- Risk: diagnostics may be less immediately specific unless we preserve the
  file inspection as warning text when real verification fails.

The proposed fix is not to punt auth validation to ordinary worker runtime. It
is to perform config-time validation using the provider's actual headless
runtime path. In other words, first-light and install setup should still fail
before deployment completes when Claude cannot run. They should fail because
the real `claude --print` config-time probe failed, not because Bullpen guessed
wrong from a private file format.

Likely origin:

- `f47efab` added the persisted-credentials check during the final
  Microsandbox stabilization pass.

Desired behavior:

The real model call should be the authoritative config-time verification. File
inspection can supplement diagnostics, especially when the current CLI is
expected to write `.credentials.json`, but it should not block if
`claude --print` works.

Recommended remediation:

1. Rename `verify_claude_credentials_file()` to something like
   `inspect_claude_credentials_file()`.
2. Run `verify_claude_auth()` as the authoritative config-time gate.
3. Run the credentials-file inspection as diagnostics:
   - before the probe only if it is non-fatal,
   - after a failed probe to improve the error message,
   - after a successful probe to record what durable artifact was observed.
4. If the real probe succeeds but no durable auth file is visible, emit a
   warning such as:
   `Claude verified via real model call, but no .credentials.json file was found;
   future Claude Code versions may be using a different auth store.`
5. Update docs to say `.credentials.json` is an observed current OAuth artifact,
   not a product contract.

Suggested tests:

- First-light can pass when real Claude probe succeeds even if
  `.credentials.json` is absent.
- First-light reports missing `.credentials.json` as diagnostic context when
  real Claude probe fails.
- First-light still fails at config time when the real Claude probe fails.
- The existing legacy `.credentials.json` validation still catches malformed
  files when used as a diagnostic.

### P3: Install Summary Says "Configured" For Providers That Were Only Verified

Relevant code:

- `sandboxed-bullpen.py:1348` checks existing provider auth.
- `sandboxed-bullpen.py:1355` appends already-verified providers to
  `summary.selected_items`.
- `sandboxed-bullpen.py:1556` prints `Configured during install`.

Risk:

The summary overstates what the installer changed. This is operationally
confusing when diagnosing whether auth was newly created, already present, or
skipped.

Likely origin:

- `da48038` introduced the interactive setup flow.
- `f47efab` added the skip-if-already-verified behavior.

Desired behavior:

The summary should distinguish:

- already verified,
- configured during this install,
- skipped by user,
- failed verification.

Recommended remediation:

1. Extend `CredentialSummary` with `verified_items` and `configured_items`.
2. Add already-verified providers to `verified_items`, not
   `selected_items`.
3. Rename output labels to be precise.

Suggested tests:

- Already-verified provider appears under "Already verified."
- Newly authenticated provider appears under "Configured during install."
- Skipped provider appears under "Skipped."

## Out-Of-Spec Behavior Review

### `ANTHROPIC_API_KEY`

`ANTHROPIC_API_KEY` leaked into product behavior as an unsupported Claude auth
path. That was removed from live product paths in `de4b576`.

Remaining appearances are acceptable generic secret hygiene:

- `sandboxed-bullpen.py` redaction list,
- `docs/worker-types.md` secret-filtering examples,
- a test asserting Docker does not support it.

If a future architecture review approves API-key support, it should be added as
a first-class provider mode with explicit billing/auth semantics, not as an
environment-variable fallback.

### Provider Auth Source Of Truth

Provider auth should not be inferred from arbitrary files unless the provider
contract explicitly says so.

Recommended standard:

- Availability means executable discovery.
- Auth verification means a minimal real provider call.
- File checks are diagnostics or migration aids.
- Deployment summaries must distinguish copied metadata from verified auth.

## Provider CLI Volatility And Interface Hardening

The first draft recommended pinning provider CLI versions. That is useful for
reproducibility, but it is not a complete or always-practical primary strategy.
The provider CLIs change quickly, sometimes multiple times per day, and updates
can include security fixes, auth-flow changes, model routing changes, and
server-side compatibility work. A rigid pin can reduce one class of regression
while creating another: running stale tooling against fast-moving provider
services.

The better architectural lesson is to harden Bullpen's provider command
interfaces so new CLI versions can change without silently violating Bullpen's
assumptions.

Recommended interface hardening:

1. Treat provider CLIs as unstable external processes.
   - Never infer contract truth from private files if a real CLI probe is
     available.
   - Prefer explicit command output, exit status, and documented flags.

2. Add provider capability probes.
   - At deploy/setup time, record CLI path, version, supported flags, auth
     status probe result, and minimal model-call result.
   - Store these diagnostics in a structured file in the deployment home, for
     example `/home/bullpen/provider-diagnostics.json`.

3. Normalize failure categories at the adapter boundary.
   - Missing executable.
   - Auth required.
   - Permission/trust prompt required.
   - Network/TLS/DNS failure.
   - Rate limit/capacity.
   - CLI contract changed.

4. Make adapters defensive around output formats.
   - Parse structured output where possible.
   - Surface unknown structured events rather than dropping them if they look
     like errors or retries.
   - Keep raw tail output in diagnostics for failed probes.

5. Add compatibility tests around command construction.
   - Tests should assert Bullpen's expected CLI contract: flags, stdin usage,
     output mode, environment, and timeout behavior.
   - Tests should not assert private provider storage unless the test is
     explicitly documenting a legacy migration path.

6. Keep version pinning as an operator control, not the only safety mechanism.
   - Continue installing latest by default if that is the chosen operational
     policy.
   - Allow override variables for emergency pinning or staged validation.
   - Always print/store installed versions so regressions can be correlated
     with provider CLI changes.

This approach fits the real-world update cadence better than "pin everything"
as a blanket rule. Bullpen should be strict about its own boundary contracts,
and flexible about provider implementation details.

## Deferred Findings

The following findings are real risks but are deferred from the immediate
remediation tranche.

### Deferred: Microsandbox Disables IPv6 Sandbox-Wide For A Claude-Specific Problem

Relevant code:

- `sandboxed-bullpen.py:1018` defines `disable_guest_ipv6_for_claude()`.
- That function writes `/etc/sysctl.d/99-bullpen-claude-ipv4.conf`.
- It disables:

```text
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.eth0.disable_ipv6 = 1
```

- `sandboxed-bullpen.py:1521` applies this during general deploy before
  mount checks, Codex setup, Git setup, Bullpen startup, and user app usage.

Reason to defer:

This was added to address a live Claude OAuth TLS failure inside Microsandbox.
Changing it without a fresh live validation cycle risks reopening the original
installer failure. It should be reviewed deliberately as a networking-policy
decision, not bundled into the auth cleanup.

Risk:

A Claude OAuth workaround becomes global sandbox network policy. If any of the
following need IPv6, the sandbox is silently incompatible:

- Codex,
- Gemini,
- GitHub,
- npm/pip/apt mirrors,
- the user's app,
- any preview app started inside the sandbox.

Potential remediation later:

- Scope the mitigation narrowly to Claude auth/verify if reliable reversal is
  possible.
- Or make it an explicit deploy/network policy with clear output.
- Or find a provider-local IPv4 workaround for Claude OAuth.

### Deferred: Codex Wrapper Lock Can Wait Forever

Relevant code:

- `sandboxed-bullpen.py:1096` spins until `mkdir "$LOCK_DIR"` succeeds.
- It removes the lock only when the stored PID is no longer alive.
- There is no timeout.

Reason to defer:

This is a boundedness and operability issue, not the immediate Claude auth
regression family. It should be handled in a Codex-wrapper hardening tranche.

Risk:

Any live-but-stuck Codex process can block all later Codex calls indefinitely.
PID reuse can also keep a stale lock alive incorrectly. Because this is inside
the wrapper, Bullpen will see a hanging provider rather than a clear setup or
runtime error.

Potential remediation later:

- Replace the directory spin lock with `flock` if available.
- Add a timeout.
- Record lock owner PID, command, and timestamp.
- On timeout, print a clear error explaining the lock path and owner.

### Deferred: Microsandbox Base Installs Latest Provider CLIs

Relevant code:

- `deploy/microsandbox/prepare.sh:136` installs latest
  `@anthropic-ai/claude-code`.
- `deploy/microsandbox/prepare.sh:137` installs latest `@openai/codex`.
- `deploy/microsandbox/prepare.sh:138` installs latest
  `@google/gemini-cli`.

Reason to defer:

Pinning all provider CLIs is not obviously correct given the speed of provider
updates and security fixes. This should be addressed as interface hardening and
operator-controlled version policy rather than as a quick pinning patch.

Risk:

Provider CLI behavior can change under Bullpen without a Bullpen code change.
That can affect auth storage, flags, output events, and failure modes.

Potential remediation later:

- Add diagnostic recording of installed provider CLI versions.
- Add override variables for emergency pinning.
- Add provider capability probes.
- Define a regular provider upgrade validation checklist.

## Recommended Remediation Order

1. Fix Docker credential detection and messaging.
   - This is the closest remaining cousin of the Claude regression.
   - It also matters immediately after API-key removal.

2. Replace blocking Microsandbox Claude `.credentials.json` validation with a
   config-time real provider probe plus diagnostics.
   - The real model call should be authoritative during setup, not delayed
     until ordinary worker runtime.
   - This prevents the same auth-format regression from reappearing in
     first-light.

3. Clean up install summary semantics.
   - Lower severity but easy to make precise.

4. Add provider interface diagnostics.
   - Record versions, paths, probe results, and failure categories.
   - This addresses fast-moving provider CLIs without pretending private files
     are stable contracts.

Deferred after the immediate tranche:

- IPv6 mitigation policy.
- Codex wrapper lock timeout.
- Provider CLI version pin/override policy.

## Suggested Ticket Breakdown

### Ticket 1: Docker Provider Auth Detection Cleanup

Scope:

- stop treating `.claude` and `.claude.json` as verified credentials,
- report provider verification status separately from copied metadata,
- preserve multi-provider deploys,
- add regression tests.

### Ticket 2: Claude First-Light Verification Source Of Truth

Scope:

- make real `claude --print` the authoritative config-time gate,
- make `.credentials.json` validation diagnostic, not blocking,
- update docs/tests.

### Ticket 3: Provider Setup Summary Semantics

Scope:

- split already-verified/configured/skipped result categories,
- update tests and final success output.

### Ticket 4: Provider Interface Diagnostics

Scope:

- record provider CLI versions and paths,
- record setup-time probe results,
- classify common provider failure modes,
- expose diagnostics for support/debugging.

### Deferred Ticket: Microsandbox IPv6 Mitigation Policy

Scope:

- decide scoped mitigation vs explicit global policy,
- implement chosen behavior,
- update deploy output and docs.

### Deferred Ticket: Codex Wrapper Lock Timeout

Scope:

- bounded lock acquisition,
- better lock diagnostics,
- tests for stale/live lock behavior.

### Deferred Ticket: Provider CLI Version Policy

Scope:

- decide latest-by-default versus pinned defaults,
- add emergency override variables if useful,
- document provider upgrade validation,
- expose version diagnostics.

## Regression Test Themes

Future tests should prefer behavior over implementation artifacts:

- Claude workers do not block merely because `.credentials.json` is absent.
- Docker deploy does not treat metadata as verified auth.
- First-light can pass on a real provider probe even if diagnostic file checks
  are absent.
- Provider setup summaries accurately name what happened.
- Provider wrappers fail boundedly with clear messages.
- Provider CLI version changes are visible in diagnostics.

## Closing Assessment

The immediate Claude worker regression is fixed, but the broader Microsandbox
work introduced several places where operational assumptions became product
contracts. The highest-risk remaining issues are all in setup/auth
classification rather than core worker execution:

- file presence treated as auth,
- provider-specific workaround applied globally,
- installer status messages collapsing distinct states.

The next remediation pass should focus on making provider state explicit:
installed, metadata copied, verified, configured, skipped, failed. That gives
Bullpen room to support multiple runtimes without turning temporary workarounds
into permanent behavior.
