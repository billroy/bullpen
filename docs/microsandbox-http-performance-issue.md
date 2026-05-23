# Microsandbox HTTP Performance Issue Post-Mortem

Date: 2026-05-23

Upstream PR: https://github.com/superradcompany/microsandbox/pull/780

## Summary

Bullpen pages that loaded in under a second from a normal host-local server were
taking 15 to 20 seconds to load when served through a Microsandbox published
port. The delay appeared as long TTFB stalls on ordinary localhost requests for
HTML, CSS, and JavaScript assets.

The issue was not caused by Bullpen's static asset structure, Flask, nginx,
browser caching, authentication, or the application workload. A minimal HTTP
server inside a sandbox reproduced the same multi-second host-to-guest stalls,
which isolated the problem to the Microsandbox published-port forwarding path.

The root cause was a missing wakeup in Microsandbox networking. The host-side
published-port listener accepted a TCP connection and queued it for the
`PortPublisher`, but did not wake the smoltcp poll loop. If that loop was asleep
in `poll(2)`, the accepted connection could sit in the inbound queue until some
unrelated wake or timer caused the loop to run again.

## Impact

- Initial Bullpen page loads inside Microsandbox took roughly 15 to 20 seconds.
- HAR traces showed request wait/TTFB plateaus, including stalls around 10
  seconds.
- The same Bullpen code and assets loaded normally from a host-local server.
- The problem made the sandboxed development environment feel broken even when
  the guest service itself was healthy.

## What Made This Hard

Several plausible explanations fit the early symptoms but did not survive
testing:

- asset count or unbundled browser modules
- Bullpen application startup time
- Flask static serving behavior
- nginx or reverse proxy behavior
- browser cache behavior
- authentication or session handling
- sandbox CPU or filesystem speed

The decisive clue was that requests made from inside the guest returned in low
milliseconds while equivalent host-to-published-port requests stalled. That
split moved the investigation away from Bullpen and toward the boundary between
the host listener and the guest network stack.

## Evidence

The original browser HAR showed a very slow page load through the sandbox
published port:

- total wall time was approximately 16.7 seconds
- localhost static requests had large wait/TTFB plateaus
- request blocking/waiting dominated the trace

The minimal diagnostic server reproduced the stall without Bullpen involved. It
served simple HTTP responses from inside the sandbox, yet host requests through
the published port still observed the same class of delay. That ruled out the
application stack and made the forwarding path the active suspect.

After applying the Microsandbox patch locally, a follow-up HAR showed the
published-port path behaving normally:

- `DOMContentLoaded`: about 98 ms
- `load`: about 152 ms
- local static/html requests excluding the websocket: median total about 29 ms
- local wait/TTFB excluding the websocket: median about 1 ms, p95 about 1.9 ms
- no 10-second localhost request plateaus

The follow-up HAR was a warm-cache validation, with local assets returning 304s,
so it should not be treated as a cold-load benchmark. It was still strong
evidence that the pathological published-port stall had been removed.

## Root Cause

In Microsandbox's published-port path, host TCP accepts are handled outside the
smoltcp poll loop. The accepted host stream is placed onto an inbound channel
for later handling by `PortPublisher`.

Before the patch, queueing the accepted connection did not wake the poll loop:

```rust
let conn = InboundConnection { stream, guest_port };
if inbound_tx.send(conn).await.is_err() {
    break;
}
```

The poll loop only noticed the queued connection after another wake source or
timer caused it to run. In the observed workload, that delay could be seconds.

This also explains why later relay wakeups were insufficient. The relay task can
wake the poll loop after reading host socket data, but that task is only spawned
after the poll loop drains the inbound connection queue and creates the smoltcp
socket. The missing wake was therefore earlier: immediately after the accept
task successfully queued the inbound connection.

## Proposed Fix

The upstream PR changes the accept/queue edge so that a successful inbound queue
send wakes `shared.proxy_wake` immediately:

```rust
async fn queue_inbound_connection<T>(
    inbound_tx: &mpsc::Sender<T>,
    conn: T,
    shared: &SharedState,
) -> bool {
    if inbound_tx.send(conn).await.is_err() {
        return false;
    }

    shared.proxy_wake.wake();
    true
}
```

The TCP listener now uses that helper instead of sending directly to the channel.
The PR also adds a focused unit test proving that queueing an inbound connection
makes the proxy wake file descriptor readable.

## Validation

The upstream patch was validated in the Microsandbox checkout with:

```bash
cargo fmt --check
cargo check -p microsandbox-network
cargo test -p microsandbox-network queue_inbound_connection_wakes_poll_loop
cargo test -p microsandbox-network --lib
cargo clippy -p microsandbox-network -- -D warnings
```

The local Bullpen environment was then run with a patched `msb` binary. The
diagnostic server no longer showed multi-second TTFB plateaus, and Bullpen
returned to low-millisecond load timings through the same published-port path.

## Local Operating Note

This machine currently has a transparent local replacement of the Microsandbox
Python wheel's bundled `msb` binary while waiting for an upstream release with
the fix. The details, verification command, and undo steps are recorded in:

```text
docs/microsandbox-local-msb-patch.md
```

Normal Bullpen sandbox deploy commands should continue to work without an
`MSB_PATH` override or wrapper script.

## Lessons

The important experiment was not another Bullpen-side performance tweak. It was
the boundary test that compared guest-local responses with host-to-published-port
responses, then reproduced the same behavior with the smallest possible HTTP
server. That separated symptom from cause and prevented the fix from becoming an
application-level workaround for a transport-level wakeup bug.
