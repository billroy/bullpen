# Microsandbox network cap 8192 validation run

Date: 2026-05-25

## Setup

- Sandbox: `bullpen`
- Runtime PID: `85205`
- Host command confirmed `network.max_connections=8192`
- Host deploy wrapper used `ulimit -n 12000`
- Guest `nofile` target: `1048576` during this manual run
- IPv6 disabled in the guest, matching the prior Claude TLS mitigation

## Result

A Bullpen ticket batch of roughly 15 tickets x 10 decrement/pass counts
completed successfully under the raised Microsandbox network connection cap.
No new worker log files under `.bullpen/logs` were created during the checked
window, and the layout was clean after the batch.

Manual host socket censuses showed:

- During load: `REMOTE443=1696`, `FD_TOTAL=1914`
- Immediately after batch completion: `REMOTE443=486`, `FD_TOTAL=703`
- After about one minute quiet: `REMOTE443=311`, `FD_TOTAL=528`
- Later preserved post-quiet snapshot: `REMOTE443=309`, `FD_TOTAL=526`
- `SYN_SENT=0` and `CLOSE_WAIT=0` in the post-quiet snapshots

## Interpretation

This is the first successful raised-cap run after the 2048-cap run saturated
exactly at its configured ceiling. It supports using an explicit
`network.max_connections=8192` deployment default for the current Bullpen
Microsandbox workload, while keeping the value configurable because
`max_connections` is a fuse rather than a throughput target.

The sockets also drained after workload completion, which argues against a
simple monotonically leaking host socket table in this run.

## Files

- `runtime-command.txt`: host `msb` command line, including network config
- `runtime-postquiet-socket-tally.txt`: preserved host FD/TCP tally after quiet
- `passive-host.log`, `passive-host.err`, `manifest.txt`: passive monitor
  artifacts from `/private/tmp/bullpen-netcap8192-20260525-154636`
- `bullpen.log`, `bullpen-proxy.log`: sandbox Bullpen logs copied from
  `~/.bullpen/microsandbox-home/logs`
- `msb-runtime.log`: Microsandbox runtime log
