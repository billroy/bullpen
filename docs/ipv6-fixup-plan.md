# Microsandbox IPv6 Fixup Plan

## Summary

Bullpen currently disables IPv6 inside Microsandbox sandboxes before Claude
auth and verification. This was not an arbitrary workaround: on the installed
`msb 0.4.4` runtime, a fresh sandbox can be configured with guest IPv6 even
when the host-side path is not usable. That made Claude Code auth vulnerable to
choosing an IPv6 route that failed during TLS, which surfaced as a misleading
certificate error.

The upstream Microsandbox project has since landed a relevant fix:

- `5f7888d fix(network): gate address families on host route availability (#671)`

That change is included in Microsandbox `v0.4.5` and `v0.4.6`. It makes IPv4
and IPv6 optional end-to-end and emits/configures each address family only when
the user explicitly supplied an address or the host has a route for that
family.

Do not remove Bullpen's IPv6 mitigation until we are running a Microsandbox
build that includes both:

- upstream address-family gating from #671
- our still-open HTTP performance fix, PR #780:
  https://github.com/superradcompany/microsandbox/pull/780

## Why IPv6 Was Disabled

The original failure happened during Claude login inside Microsandbox. The
flow reached the post-code OAuth exchange and then Claude Code reported:

```text
Login failed: unknown certificate verification error
```

The investigation isolated this to guest IPv6:

- Anthropic/Claude hosts resolved to both IPv4 and IPv6 addresses.
- Forced IPv4 TLS to those hosts succeeded inside Microsandbox.
- Forced IPv6 TLS to those hosts failed inside Microsandbox with EOF /
  SSL syscall errors.
- Claude Code's auth path opened both address families and, in the failing
  post-code exchange, sent TLS traffic over the broken IPv6 path.
- Disabling guest IPv6 forced Claude onto IPv4 and allowed auth to complete.

That evidence is captured in `docs/microsandbox-handoff.md`.

## Current Recheck

The installed runtime on this machine is:

```text
msb 0.4.4
```

A fresh disposable sandbox from the prepared Bullpen base, without running
Bullpen's IPv6 mitigation, still shows the lower-level defect:

```text
all=0
default=0
eth0=0

inet6 fd42:6d73:62:f3::2/64 scope global tentative
default via fd42:6d73:62:f3::1 dev eth0

curl -4 https://platform.claude.com/ -> HTTP 200
curl -6 https://platform.claude.com/ -> Failed to connect
openssl [2607:6bc0::10]:443 -> unexpected eof while reading
```

So the mitigation is still justified for the currently installed `0.4.4`
runtime.

One important nuance: current Claude Code `2.1.150` successfully completed a
normal noninteractive `claude --print --verbose --output-format stream-json`
call even with guest IPv6 temporarily re-enabled. That means ordinary model
calls may now fall back cleanly. It does not prove fresh auth is safe on
`0.4.4`, and it does not fix the sandbox advertising an unusable IPv6 path.

## Upstream Status

The local Microsandbox source checkout was refreshed from
`superradcompany/microsandbox`. Upstream `origin/main` contains:

```text
5f7888d fix(network): gate address families on host route availability (#671)
```

The commit summary says the old behavior emitted both `MSB_NET_IPV4` and
`MSB_NET_IPV6` regardless of host route availability, configuring IPv6 in the
guest even on hosts where that family was not usable. The fix makes each
address family active only if:

- the user supplied an explicit address, or
- the host kernel has a route for that family.

This is the upstream-level fix we would have wanted for the Claude auth issue.

However, Bullpen also depends on the separate Microsandbox HTTP performance
patch:

```text
https://github.com/superradcompany/microsandbox/pull/780
```

That PR is still open. Upgrading to stock `v0.4.6` would pick up the IPv6 fix,
but may lose the local HTTP performance fix that made Bullpen load in
milliseconds instead of 15-20 seconds.

## Remediation Plan

1. Keep the current Bullpen IPv6 mitigation while the active runtime is patched
   `msb 0.4.4`.

2. Build a local Microsandbox runtime that combines:
   - upstream `v0.4.6` or current `origin/main`
   - Bullpen HTTP performance PR #780, if it is not yet merged

3. Install that combined runtime as the local `msb` used by the Bullpen
   deploy tooling.

4. Rebuild the prepared Bullpen Microsandbox base.

5. Create a fresh disposable sandbox that has never run Bullpen's IPv6
   mitigation.

6. Verify untouched network state on this host:

```bash
for k in all default eth0; do
  cat "/proc/sys/net/ipv6/conf/$k/disable_ipv6"
done

ip -6 addr show dev eth0
ip -6 route
getent ahosts platform.claude.com
curl -4 -sS -o /dev/null -w '%{http_code} %{remote_ip}\n' https://platform.claude.com/
curl -6 -sS -o /dev/null -w '%{http_code} %{remote_ip} %{errormsg}\n' https://platform.claude.com/
```

Expected result on this host after #671:

- no guest global IPv6 address/default route unless the host truly has a usable
  IPv6 route
- IPv4 HTTPS succeeds
- forced IPv6 is either unavailable because no IPv6 route exists, or succeeds
  if the host genuinely has usable IPv6

7. Verify Bullpen's core Microsandbox behavior:
   - Bullpen page load remains low-millisecond through proxied ports
   - `CodexAdapter` still uses `/usr/local/bin/codex`
   - Codex stderr is empty
   - Claude `--print --verbose --output-format stream-json` succeeds

8. If the clean runtime proves address-family gating works, remove
   `disable_guest_ipv6_for_claude()` from `deploy-sandbox.py` and update
   `tests/test_deploy_sandbox.py` accordingly.

9. Run the full Bullpen test suite:

```bash
python3 -m py_compile deploy-sandbox.py
python3 -m pytest -q
git diff --check
```

10. Perform one optional fresh Claude auth proof if credentials can be safely
    refreshed without disrupting the working sandbox. This is useful but should
    not be required to classify the upstream network fix if the clean sandbox
    no longer advertises unusable IPv6.

## Decision Rule

Remove the Bullpen-side IPv6 disable only after a fresh sandbox built with the
combined fixed Microsandbox runtime proves that unusable guest IPv6 is no
longer advertised on this host.

Until then, keep the mitigation. It is not scar tissue for the installed
runtime; it is a local guard around a real `0.4.4` Microsandbox networking
defect.
