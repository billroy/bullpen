# Microsandbox Network Cap 2048 Run

Date: 2026-05-25

This investigation captures a Bullpen load run in the `bullpen` Microsandbox after restarting it with:

- host runtime `ulimit -n 4096`
- guest `nofile=1048576`
- guest IPv6 disabled
- Microsandbox network config `max_connections=2048`

## Finding

Raising Microsandbox `network.max_connections` from the default 256 allowed the same Bullpen/Claude ticket load to progress much farther, but the run eventually saturated the new cap as well.

The host runtime reached:

```text
ESTABLISHED 2049
LISTEN 2
SYN_SENT 0
CLOSE_WAIT 0
OTHER 0
REMOTE443 2048
TOTAL 2051
FD_TOTAL 2265
```

At that point the guest canary began seeing global outbound connect failures again, including both Anthropic and `example.com`:

```text
Failed to connect to api.anthropic.com port 443 after 18 ms
Failed to connect to example.com port 443 after 182 ms
```

This strengthens the prior hypothesis: the intermittent Bullpen/Claude stalls are bounded by Microsandbox's internal smoltcp/proxy connection accounting, not by host `ulimit`, guest file descriptors, DNS, or TLS certificate verification.

## Evidence

- `guest-canary-light.log`: guest-side canary log with layout snapshots, `ss` samples, and periodic curl checks.
- `runtime-snapshot.txt`: host runtime command line showing `max_connections=2048`, host TCP/FD snapshot, and a post-restart worker log error scan.
- `host-light-manifest.txt`: host monitor metadata.
- `host-runtime-light.log`: incomplete host monitor artifact; the reliable host snapshot is preserved in `runtime-snapshot.txt`.

## Notes

Post-restart Bullpen worker logs did not contain `api_retry`, `ConnectionRefused`, `UNKNOWN_CERTIFICATE`, `Unable to connect`, `error=unknown`, `ECONNREFUSED`, or `Failed to connect` signatures during the checked window. The canary captured the network-cap saturation first.
