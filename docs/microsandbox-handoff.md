# Microsandbox Handoff

**Updated:** 2026-05-07

**Archive note:** The temporary repro harnesses formerly stored under `tmp/`
were removed during repository cleanup. The conclusions worth preserving live in
the `investigations/` captures and this handoff note; commands below that point
at `tmp/` are historical breadcrumbs, not active scripts.

## Purpose

This note is the handoff point for the current Microsandbox installer and auth
work. It is meant to let a new session start from one clean operational
snapshot rather than replaying the full debugging history.

## Current Position

The Microsandbox installer is far enough along to:

- create and replace the sandbox
- boot Bullpen inside the sandbox
- run a sequential per-package install flow
- launch interactive provider setup under a PTY
- stop immediately when interactive provider setup fails

The current blocker is no longer broad Bullpen startup or sandbox plumbing.
The first auth failure was isolated to **Claude login inside the sandbox**,
specifically the post-code OAuth exchange after the user pastes the
browser-returned code. The standalone repro showed a concrete Microsandbox
IPv6/TLS failure mode and a narrow installer-side mitigation: disable guest
IPv6 before running Claude auth or Claude verification.

After that mitigation, Claude auth got past the previous blocker. The next
observed provider-flow problem is **Codex browser auth callback delivery**:
`codex login --device-auth` is not acceptable because it depends on a ChatGPT
Security Settings toggle, while plain `codex login` sends the host browser to a
`http://localhost:<port>/auth/callback?...` URL whose listener is inside the
sandbox, not on host localhost. The smallest current fix is to keep Codex on
browser auth and allow the user to paste that full callback URL into the
installer terminal, where the installer replays it against sandbox-localhost.

## What Is Working

### Installer flow

`deploy-sandbox.py --replace` now:

- creates the sandbox from the prepared base
- waits for Bullpen health
- verifies Bullpen bootstrap credentials
- runs the install setup loop package-by-package

The install flow asks one package at a time, not "ask all, then install all."

### Interactive setup handling

Interactive provider setup now runs through a PTY-backed path and correctly
propagates failure.

This fixed an earlier bug where:

- `claude auth login` could fail
- the installer would still continue into `==> Verifying Claude`

That installer bug is fixed. A failed interactive auth command now stops at the
auth step with:

```text
error: Sandbox interactive command failed: authenticate Claude
```

### Prepared base freshness

The prepared Microsandbox base was rebuilt during this debugging pass.

Current verified versions in the base:

- `claude`: `2.1.132`
- `codex-cli`: `0.129.0`
- `node`: `v22.22.2`
- `strace`: installed
- `ss`/`ip`: installed through `iproute2`

This ruled out the earlier suspicion that the base image was stale.

### Tests

Verified before this handoff:

```bash
python3 -m pytest tests/test_deploy_sandbox.py tests/test_agents.py
python3 -m py_compile deploy-sandbox.py
git diff --check
```

Result at handoff:

- `95 passed`

Additional focused checks during the standalone repro pass:

```bash
python3 -m py_compile deploy-sandbox.py tmp/claude_auth_microsandbox_repro.py
python3 -m pytest tests/test_deploy_sandbox.py -q
git diff --check
```

Result:

- `31 passed`

Latest focused verification after adding the scoped IPv6 mitigation:

```bash
python3 -m py_compile deploy-sandbox.py tmp/claude_auth_microsandbox_repro.py tmp/probe_existing_microsandbox_tls.py tmp/claude_network_mitigation_cycle.py tmp/microsandbox_vger.py tmp/run_microsandbox_vger.py
python3 -m pytest tests/test_deploy_sandbox.py -q
python3 tmp/claude_network_mitigation_cycle.py
```

Result:

- `32 passed`
- noninteractive mitigation cycle passed

Latest focused local verification after adding the Codex localhost callback
bridge:

```bash
python3 -m py_compile deploy-sandbox.py
python3 -m pytest tests/test_deploy_sandbox.py -q
```

Result:

- `41 passed`
- local callback URL detection and sandbox delivery helpers are unit-covered

## Claude Auth Finding

Claude login inside the sandbox failed during the auth flow itself when guest
IPv6 was available.

Observed behavior:

1. Installer reaches `==> Setting up Claude`
2. `claude auth login` launches inside the sandbox
3. Claude prints an auth URL
4. User opens the URL in a host browser and completes auth
5. User pastes the returned code into the terminal when prompted
6. Claude responds:

```text
Login failed: unknown certificate verification error
```

7. Installer exits immediately with:

```text
error: Sandbox interactive command failed: authenticate Claude
```

This failure reproduced even after rebuilding the prepared base and also
reproduced in a standalone auth-only repro that does not start Bullpen.

The root finding is now narrower:

- Microsandbox resolves Anthropic/Claude hosts to both `160.79.104.10` and
  `2607:6bc0::10`.
- Forced IPv4 TLS to those hosts succeeds inside Microsandbox.
- Forced IPv6 TLS to those hosts fails inside Microsandbox with EOF / SSL
  syscall errors.
- Claude Code's bundled Bun/native auth path opens both IPv6 and IPv4 sockets,
  then sends the post-code `platform.claude.com` TLS ClientHello on the IPv6
  socket and surfaces the immediate EOF as `unknown certificate verification
  error`.
- When guest IPv6 is disabled before auth, Claude uses IPv4 for the OAuth token
  exchange, completes login, and writes
  `/home/bullpen/.claude/.credentials.json`.

Important latest artifacts:

- failed normal repro with strace:
  `tmp/claude-auth-repro-1778174588.log`
- failed `BUN_OPTIONS=--dns-result-order=ipv4first` repro:
  `tmp/claude-auth-repro-1778174828.log`
- successful IPv6-disabled repro:
  `tmp/claude-auth-repro-1778174904.log`

Privacy note: the successful repro transcript includes verbose OAuth HTTP
headers and bearer material because `BUN_CONFIG_VERBOSE_FETCH=curl` was enabled
for diagnosis. Do not paste or publish that log.

## Standalone Repro Status

A narrow repro now exists at:

- [tmp/claude_auth_microsandbox_repro.py](/Users/bill/aistuff/bullpen/tmp/claude_auth_microsandbox_repro.py)

It intentionally avoids Bullpen startup and installer TUI plumbing. It uses:

- prepared base: `bullpen-microsandbox-local`
- sandbox name: `bullpen-claude-auth-repro`
- guest user: `bullpen`
- guest home: `/home/bullpen`
- host durable home under the repo:
  `tmp/microsandbox-claude-auth-home`
- workspace mount: the repo root, bound to `/workspace`

The repro does only:

1. create/replace a Microsandbox from the prepared base
2. prepare the `bullpen` user and mounted home/workspace
3. print identity and version diagnostics
4. prove direct TLS basics with `curl` and Node HTTPS
5. run `claude auth login` under a PTY
6. capture the terminal transcript with `script(1)`
7. capture a best-effort network log from inside the guest
8. inspect Claude file metadata after failure

Useful command:

```bash
python3 tmp/claude_auth_microsandbox_repro.py
```

Diagnostic-only variants:

```bash
python3 tmp/claude_auth_microsandbox_repro.py --trace-tls
python3 tmp/claude_auth_microsandbox_repro.py --insecure-disable-tls-verification
python3 tmp/claude_auth_microsandbox_repro.py --disable-ipv6
```

The insecure flag is only for classifying the failure. It is not a candidate
fix and should not be moved into the installer.

Important captured logs from this pass:

- `tmp/claude-auth-repro-1778170237.log`
- `tmp/claude-auth-repro-1778171556.log`
- `tmp/claude-auth-repro-1778171768.log`
- `tmp/claude-auth-repro-1778172354.log`

The latest enhanced run writes a transcript plus sibling network logs:

- `tmp/claude-auth-repro-<timestamp>.log`
- `tmp/claude-auth-repro-<timestamp>.net.log`
- `tmp/claude-auth-repro-<timestamp>.net-summary.log`
- optional strace logs if `strace` exists in the prepared base

In the current prepared base, `strace`, `ss`, and `ip` are available. The
harness captures `strace -ff -tt -s 256 -e trace=network` logs when possible
and polls `ss` during the run.

The current `--disable-ipv6` flag is diagnostic-only in the repro harness. The
installer-side mitigation is implemented separately in `deploy-sandbox.py`
before Claude auth and Claude verification.

## VGER Environment Probe

A broader environment probe now exists at:

- [tmp/microsandbox_vger.py](/Users/bill/aistuff/bullpen/tmp/microsandbox_vger.py)
- [tmp/run_microsandbox_vger.py](/Users/bill/aistuff/bullpen/tmp/run_microsandbox_vger.py)

VGER writes comparable artifacts under:

- `tmp/vger/host-net/summary.txt`
- `tmp/vger/host-net/vger.json`
- `tmp/vger/sandbox/summary.txt`
- `tmp/vger/sandbox/vger.json`

The sandbox VGER uses the same prepared base, sandbox user, durable home, and
workspace mount shape as the Claude auth repro. It does not perform OAuth and
does not touch Claude credentials.

Useful commands:

```bash
python3 tmp/microsandbox_vger.py --label host-net
python3 tmp/run_microsandbox_vger.py
```

### VGER Findings

Sandbox platform:

```text
Linux-6.12.68-aarch64-with-glibc2.36
Debian GNU/Linux 12 (bookworm)
```

Sandbox DNS:

```text
api.anthropic.com      -> 160.79.104.10, 2607:6bc0::10
claude.com             -> 160.79.104.10, 2607:6bc0::10
platform.claude.com    -> 160.79.104.10, 2607:6bc0::10
console.anthropic.com  -> 160.79.104.10, 2607:6bc0::10
```

The host network baseline resolves the same IPv4 edge, `160.79.104.10`, but
does not report the IPv6 address in this run.

Sandbox TLS verification succeeds outside Claude auth:

- Python `ssl` succeeds for all four hostnames
- `curl -Iv` succeeds for all four hostnames when it can use IPv4
- `openssl s_client -verify_return_error` succeeds for all four hostnames when
  it can use IPv4
- Node HTTPS succeeds for all four hostnames

Observed certificate issuers:

- `api.anthropic.com`: Google Trust Services `WE1`
- `claude.com`: Let's Encrypt `E7`
- `platform.claude.com`: Let's Encrypt `E7`
- `console.anthropic.com`: Let's Encrypt `E8`

Sandbox process constraints do not look obviously restrictive:

- `Seccomp: 0`
- `NoNewPrivs: 0`
- no effective capabilities, but normal user network/TLS probes work
- open files soft/hard limit: `65536`
- `/tmp` is writable tmpfs, not mounted `noexec`
- `/workspace` and `/home/bullpen` are `virtiofs`

Sandbox resolver details:

```text
/etc/resolv.conf:
nameserver 100.96.1.97
nameserver fd42:6d73:62:58::1

/etc/nsswitch.conf:
hosts: files dns
```

Claude binary details in the sandbox:

```text
/usr/local/bin/claude -> /usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
claude.exe: ELF 64-bit LSB executable, ARM aarch64, dynamically linked
```

`ldd` shows only ordinary glibc system libraries:

```text
librt.so.1
libc.so.6
libpthread.so.0
libdl.so.2
libm.so.6
```

`strings` in the Claude binary includes relevant CA path and Bun/BoringSSL
hints:

```text
/etc/ssl/certs/ca-certificates.crt
/usr/local/share/ca-certificates/ca-certificates.crt
/etc/pki/tls/certs/ca-bundle.crt
/etc/ssl/certs
/usr/share/ca-certificates
getBundledRootCertificates
getSystemCACertificates
getExtraCACertificates
--use-system-ca
unknown certificate verification error
BoringSSLError
unified/../../../packages/bun-usockets/src/crypto/root_certs.cpp
```

Interpretation:

- the sandbox can verify the public Claude/Anthropic cert chains through normal
  Linux TLS stacks over IPv4
- DNS and the public edge IPv4 do not obviously differ from host IPv4
- Microsandbox's IPv6 path to the same public edge is broken for these hosts:
  forced IPv6 `curl`/`openssl` fail with connect/EOF style TLS errors
- Claude's Linux native/Bun/BoringSSL auth path chooses that broken IPv6 path
  for the post-code exchange unless guest IPv6 is disabled

## Targeted Forced-Family Probe

A narrow forced-family probe now exists at:

- [tmp/probe_existing_microsandbox_tls.py](/Users/bill/aistuff/bullpen/tmp/probe_existing_microsandbox_tls.py)
- [tmp/claude_network_mitigation_cycle.py](/Users/bill/aistuff/bullpen/tmp/claude_network_mitigation_cycle.py)

Useful commands:

```bash
python3 tmp/probe_existing_microsandbox_tls.py --cleanup
python3 tmp/claude_network_mitigation_cycle.py
```

`tmp/claude_network_mitigation_cycle.py` is the preferred noninteractive test
cycle. It creates a fresh Microsandbox through the same live `runtime.create()`
path as the installer, applies `disable_guest_ipv6_for_claude()` from
`deploy-sandbox.py`, verifies `all/default/eth0` IPv6 disable flags, proves
IPv4 TLS to `platform.claude.com` succeeds, and proves IPv6 no longer succeeds.

Latest cycle output:

```text
Before mitigation:
all=0
default=0
eth0=0

Claude auth network mitigation applied: guest IPv6 disabled for this sandbox.

ipv6 flags
all=1
default=1
eth0=1

curl4 platform: HTTP/2 200
openssl4 platform: Verification OK
curl6 platform expected-fail: Couldn't connect to server
cycle OK
```

Additional pretests run before proposing more installer changes:

1. `python3 tmp/claude_network_mitigation_cycle.py` twice back-to-back:
   both runs passed and proved the fresh create/mitigate/check/cleanup loop is
   repeatable.
2. `python3 tmp/claude_network_mitigation_cycle.py --sandbox-name bullpen --sandbox-home /Users/bill/.bullpen/microsandbox-home`:
   passed using the real installer sandbox name and default sandbox home shape.
3. `python3 tmp/claude_auth_microsandbox_repro.py --disable-ipv6`, interrupted
   before OAuth code entry:
   Claude's own bundled Bun pre-code fetch succeeded, and strace showed only
   IPv4 for that request:
   DNS queried A for `api.anthropic.com`, opened `AF_INET`, and sent the TLS
   ClientHello to `160.79.104.10`.
4. Installer path ordering inspected:
   `auth_claude()` calls `disable_guest_ipv6_for_claude()` immediately before
   `attach_as_bullpen(... claude auth login ...)`, and
   `verify_claude_auth()` calls the same mitigation before `claude --print`.

Observed inside a throwaway Microsandbox:

```text
api.anthropic.com:
  curl -4: HTTP response reached; endpoint returns expected 404 for HEAD /
  curl -6: Failed to connect
  openssl 160.79.104.10: Verification OK
  openssl [2607:6bc0::10]: unexpected eof while reading

platform.claude.com:
  curl -4: HTTP 200
  curl -6: OpenSSL SSL_connect: SSL_ERROR_SYSCALL
  openssl 160.79.104.10: Verification OK
  openssl [2607:6bc0::10]: unexpected eof while reading
```

This is the key receipt that the issue is not "IPv6 affects an IPv4
transaction." The failed Claude transaction was not actually using IPv4 for the
post-code token exchange. It opened IPv4 too, but sent the `platform.claude.com`
ClientHello on the IPv6 socket.

## Codex Auth Finding

After Claude auth moved past the IPv6/TLS failure, the Codex setup path exposed
a separate UX/runtime issue.

Observed behavior:

1. `codex login --device-auth` inside the sandbox can fail with:

```text
Enable device code authorization for Codex in ChatGPT Security Settings, then run "codex login --device-auth" again.
```

2. Plain `codex login` avoids that device-auth setting, but its browser OAuth
   flow returns to a URL shaped like:

```text
http://localhost:1455/auth/callback?code=...&scope=...&state=...
```

3. That URL is host-localhost from the browser's point of view. The listening
   Codex process is inside the sandbox, so the callback is not delivered unless
   it is bridged.

The current installer-side approach is intentionally narrow:

- Codex setup now runs `codex login`, not `codex login --device-auth`.
- `auth_codex()` tells the user that if the browser lands on a localhost
  callback URL, paste the full URL into the installer terminal.
- The interactive `exec_stream` path detects pasted
  `http://localhost|127.0.0.1/.../auth/callback?code=...` URLs and runs `curl`
  inside the sandbox against that exact URL, delivering it to the sandbox-local
  Codex listener.
- The bridge does not read or transform the OAuth code beyond replaying the
  callback URL to the waiting sandbox-local listener.

Current local coverage proves:

- callback URL detection accepts only localhost callback URLs with `code`
  material
- callback delivery runs `curl` inside the sandbox path rather than forwarding
  the pasted URL to the provider process
- async and sync sandbox execution result shapes are accepted

What this does not prove yet:

- a fresh Microsandbox created through the same `runtime.create()` path can run
  a sandbox-local `127.0.0.1:<port>/auth/callback` listener
- a real Codex OAuth server accepts the callback after replay
- the full installer's interactive terminal pump handles the exact pasted URL
  in the live `codex login` process
- Codex verification after login succeeds in the same sandbox

## What Has Been Ruled Out

These are important because they narrow the search space.

### Not a generic sandbox startup problem

The sandbox can be created, Bullpen can boot, and health checks pass.

### Not the earlier installer control-flow bug

Failure handling in the interactive auth path is now correct.

### Not stale Claude bits in the prepared base

The base was rebuilt and now contains current Claude Code `2.1.132`.

### Not a broad HTTPS or CA-bundle failure in the sandbox

Standalone repro diagnostics inside the sandbox showed:

- `/etc/ssl/certs/ca-certificates.crt` exists
- `curl -fsSIL https://console.anthropic.com` works
- Node HTTPS to `https://console.anthropic.com` works
- Claude/Bun itself can make a successful TLS request to
  `HEAD https://api.anthropic.com/`

That means the observed cert failure is **specific to Claude CLI's auth flow**,
not a general inability to validate TLS inside the sandbox.

### Not fixed by Node CA env

Claude auth and verify already set:

- `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`
- `SSL_CERT_DIR=/etc/ssl/certs`
- `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt`

Those were not enough.

### Not fixed by Bun system CA flag

The installed Claude Code package points `/usr/local/bin/claude` at a native
standalone executable:

```text
/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
```

The binary reports Bun fetch diagnostics as `User-Agent: Bun/1.3.14`.

A minimal code change was tried:

```bash
export BUN_OPTIONS="${BUN_OPTIONS:+$BUN_OPTIONS }--use-system-ca"
```

This environment did reach the Claude process, but `claude auth login` still
failed immediately after code entry with:

```text
Login failed: unknown certificate verification error
```

### Not fixed by disabling Node TLS verification

The repro-only flag:

```bash
--insecure-disable-tls-verification
```

sets:

```bash
NODE_TLS_REJECT_UNAUTHORIZED=0
```

Even with that diagnostic flag, the post-code auth failure remained:

```text
Login failed: unknown certificate verification error
```

This strongly suggests the failing verifier is not ordinary Node TLS.

### Bun fetch logging initially only showed the pre-code probe

The repro sets:

```bash
BUN_CONFIG_VERBOSE_FETCH=curl
```

Before the IPv6 finding, failed runs emitted a successful pre-code request:

```text
[fetch] curl --http1.1 "https://api.anthropic.com/" -X HEAD ...
[fetch] < 404 Not Found
```

On the successful IPv6-disabled diagnostic run, the same fetch logging emitted
the full post-code OAuth sequence and all requests succeeded:

- `POST https://platform.claude.com/v1/oauth/token`
- `GET https://api.anthropic.com/api/oauth/profile`
- `GET https://api.anthropic.com/api/oauth/claude_cli/roles`
- `GET https://api.anthropic.com/api/organization/claude_code_first_token_date`

Do not share that successful transcript verbatim because it includes OAuth
bearer material in verbose request headers.

### Guest network polling only saw early API sockets

The enhanced repro run from `tmp/claude-auth-repro-1778172687.log` captured a
large `/proc/net/tcp*` polling log and decoded it to one non-loopback remote:

```text
160.79.104.10:443 state=05 count=1773 first=1778172689.439053417 last=1778172751.949645530 local_ports=96DE,96EC,96F4
```

The auth command exited at `1778172904` / `2026-05-07 16:55:04+00:00`.

Interpretation:

- the visible remote sockets were early Anthropic API probe residue
- there was no long-lived post-code remote socket visible in `/proc/net`
- because `strace` and `ss` are missing from the prepared base, this does not
  rule out a very short post-code `connect()`/TLS attempt
- adding `strace` to the prepared base is now the best next diagnostic step if
  `/proc/net` remains too coarse

### Not credential persistence

After failed auth, the durable sandbox home contains only baseline Claude state:

```text
/home/bullpen/.claude
/home/bullpen/.claude/telemetry
/home/bullpen/.claude/backups
/home/bullpen/.claude.json
```

No `/home/bullpen/.claude/.credentials.json` is created in failed runs. The
successful IPv6-disabled diagnostic run did create:

```text
/home/bullpen/.claude/.credentials.json
```

## Important Code Changes Already Landed

Primary file:

- [deploy-sandbox.py](/Users/bill/aistuff/bullpen/deploy-sandbox.py)

Important current behavior in that file:

- removed the obsolete external-auth import path
- fixed fresh workspace startup so missing `/workspace/.bullpen/config.json`
  does not crash the installer
- uses `attach()` for interactive setup when available
- applies Claude-specific TLS env only to Claude auth and verify commands, not
  to global sandbox startup
- currently also applies `BUN_OPTIONS=--use-system-ca` in the Claude-specific
  TLS env prefix; this was tested and is not sufficient, but it is still a
  reasonable harmless diagnostic/hardening knob unless later evidence says to
  remove it
- disables guest IPv6 immediately before Claude auth and Claude verification.
  This is intentionally scoped to Claude setup/check paths and is based on the
  forced-family probe plus the successful IPv6-disabled repro.
- Codex setup no longer forces `codex login --device-auth`. It uses
  `codex login` and runs through an intercepted exec stream so a host-browser
  `http://localhost:<port>/auth/callback?...` redirect can be pasted into the
  installer. The installer then replays that callback URL inside the sandbox
  with `curl`, where Codex's local callback listener is actually running.
  This is callback routing only.
- records and checks the real exit status of interactive setup commands

Tests updated in:

- [tests/test_deploy_sandbox.py](/Users/bill/aistuff/bullpen/tests/test_deploy_sandbox.py)

Spec and plan documents already in place:

- [docs/microsandbox-take-2.md](/Users/bill/aistuff/bullpen/docs/microsandbox-take-2.md)
- [docs/microsandbox-implementation-plan.md](/Users/bill/aistuff/bullpen/docs/microsandbox-implementation-plan.md)

## Best Next Step

Do **not** reopen broad installer architecture questions.

The next task is to verify the full installer path with the narrow IPv6
mitigation:

```bash
python3 deploy-sandbox.py --replace ...
```

Do not use `python3 deploy-sandbox.py auth claude` as the next validation
after a failed deploy process exits. With the current Microsandbox SDK,
`Sandbox.get()` can see that the named sandbox exists but does not return a
handle with `exec()`/`attach()`, so the command cannot operate on the existing
detached sandbox. The full installer path has the live sandbox object returned
by `Sandbox.create()`, so it remains the meaningful validation path.

What is already known:

1. the auth URL generation works
2. the browser-returned code is accepted by the CLI prompt
3. the failure happens immediately after code entry
4. normal `curl`, Node HTTPS, and Bun fetch TLS to Anthropic endpoints can work
5. the failing path ignores Node-style TLS bypass knobs
6. no credentials are persisted

What still needs to be learned:

1. whether the full installer flow accepts the new scoped IPv6 mitigation
2. whether Claude verification succeeds reliably after auth in the same sandbox
3. whether Microsandbox upstream has an IPv6 routing/bridging issue that should
   be reported separately
4. whether the mitigation should become Claude-only, sandbox-wide during setup,
   or prepared-base-level after more evidence

## Recommended Immediate Work Item

Continue with the full installer command path, focused on Codex callback
delivery:

- run the same `python3 deploy-sandbox.py --replace ...` command used for
  the normal Microsandbox install
- choose Claude only if the sandbox home does not already contain valid Claude
  auth; otherwise skip it
- choose Codex
- complete the host browser auth URL
- if the browser lands on a `http://localhost:<port>/auth/callback?...` URL,
  paste that full URL into the installer terminal
- confirm the installer prints
  `Delivered localhost auth callback inside the sandbox.`
- confirm the setup loop moves past Codex verification

Useful next harness improvements, still narrow:

- redact verbose OAuth request headers in the repro logs before copying them
  into `tmp/`
- add an explicit post-disable probe that records whether `/proc/sys/net/ipv6`
  values are actually `1`
- keep the forced-family TLS probe around as the VGER-style receipt for the
  Microsandbox IPv6 issue
- add a terminal-pump unit or pseudo-TTY test that verifies pasted callback URLs
  are consumed by the bridge and are not forwarded to the provider process
- either remove the `auth` / `test-provider` subcommands or teach them to
  create/recover an executable sandbox handle; they are not reliable against a
  detached sandbox with the current SDK

Do not widen that search beyond the sandbox or the project tree without
explicit approval.

The goal is to make Claude OAuth login work inside Microsandbox. Moving users
to a different billing/auth path is not an acceptable substitute for fixing the
OAuth path.

## Privacy / Boundary Rule For The Next Session

Hard rule:

> Do not access files outside `/Users/bill/aistuff/bullpen` without asking
> first.

This includes broad searches under `/Users/bill`, even if the intent is only
diagnostic.

If additional host-side inspection becomes necessary, ask first and keep the
scope narrow and explicit.

## Suggested Opening Prompt For The Next Session

Use this as the starting instruction for a fresh session:

> Read [docs/microsandbox-handoff.md](/Users/bill/aistuff/bullpen/docs/microsandbox-handoff.md) first. We isolated `claude auth login` inside Microsandbox to a broken guest IPv6 TLS path: Claude's post-code OAuth request chooses IPv6, gets EOF, and reports `unknown certificate verification error`. The standalone repro succeeds when guest IPv6 is disabled, and `deploy-sandbox.py` now disables guest IPv6 with the same `sysctl` keys before Claude auth/verify only. After that, Codex exposed a separate localhost callback problem: plain `codex login` returns the host browser to `http://localhost:<port>/auth/callback?...`, but the listener is inside the sandbox. `deploy-sandbox.py` now lets the user paste that callback URL into the installer terminal and replays it inside sandbox-localhost; the local unit tests cover callback URL detection and delivery helper behavior, but the live Codex OAuth replay still needs validation. Do not redesign the installer. Stay inside the project directory unless you ask first. The next validation is the full `deploy-sandbox.py --replace ...` installer path, not `auth claude`, because `Sandbox.get()` does not provide an executable handle for the detached sandbox in this SDK.
