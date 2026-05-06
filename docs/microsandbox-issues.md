# Microsandbox deploy — known issues and fixes

This document captures problems we have hit running Bullpen on Microsandbox,
the fixes that have landed, and the sharp edges that remain. The architecture
spec lives in [microsandbox.md](microsandbox.md); this is the operational
companion.

The unifying observation: Microsandbox's microVM exposes timing and resource
characteristics that Docker hides. Several distinct-looking symptoms (Claude
retry storms, slow page loads, intermittent TLS errors) trace to a small
number of root causes at the platform layer, not in Bullpen code.

## Fixes that have landed

### File-descriptor exhaustion masquerading as TLS / DNS errors

**Symptom.** Live Agent chats and worker dispatches occasionally entered a
multi-minute storm of `[claude api_retry attempt=N/10 error=unknown]` events
before either eventually succeeding or timing out. The pattern was
process-deterministic — a given claude run either fully worked or
fully failed; on failed runs every API call from that process emitted
"unknown certificate verification error" in claude's debug logs.

**Root cause.** The microVM's default soft `RLIMIT_NOFILE = 1024` (hard 4096)
that `pam_limits.so` applied to the `bullpen` user during
`su -s /bin/bash bullpen` was too tight under realistic agent load. Each
chat or worker dispatch spawns:

- the claude binary (Node)
- `mcp_tools.py` for the Bullpen MCP, which opens its own Socket.IO
  connection back to the Bullpen server
- parallel Anthropic API streams (a haiku side-call for labeling plus the
  main sonnet call)
- per-run isolated `CLAUDE_CONFIG_DIR` in `/tmp` with copy-in / sync-back
  of `.credentials.json`

When several of these run concurrently — which they routinely do — the
kernel intermittently returned errors from `open()`, `socket()`, or
`close()` syscalls. Node's TLS layer surfaced those as
`"unknown certificate verification error"` (the SDK's generic label when
no X509 reason code matches a known bucket); plain Node `fetch()` exposed
the same pressure as `EAI_AGAIN` from `getaddrinfo`. Claude's own
classifier, having no HTTP status to look at, labeled the result
`error=unknown` and entered its 10-attempt exponential-backoff retry
loop. The user-visible "8 retries before answer" was this loop running
to near-completion.

The diagnosis path eliminated several plausible-looking theories before
landing here: OAuth refresh stampedes, missing CA bundles
(`SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`), IPv6 routing,
Werkzeug + simple-websocket failures, and DNS misconfiguration. Each
looked like a hit at one stage and was ruled out by an isolated test.

**Fix.** [`sandboxed-bullpen.py`](../sandboxed-bullpen.py) now writes
`/etc/security/limits.d/bullpen-fd.conf` during `prepare_runtime_dirs`:

```
bullpen soft nofile 65536
bullpen hard nofile 65536
```

`pam_limits.so` is loaded by `/etc/pam.d/su`, so this raises the ceiling
end-to-end through every `su -s /bin/bash bullpen` invocation. A bash
`ulimit -n` in the launcher shell was tried first and does *not* work —
pam_limits resets it during the su transition.

The deploy step also probes `ulimit -Hn` after writing the file and
warns to stderr if the hard limit didn't take, so deploys against
future base images that wire pam differently make the regression
visible instead of silent.

Commit: `d4778b6`.

### Claude OAuth handling

The OAuth path between the host's `~/.claude/.credentials.json` and the
sandbox's `/home/bullpen/.claude/.credentials.json` (bind-mounted from
`~/.bullpen/microsandbox-home/.claude/`) accumulated several fixes
during early Microsandbox bring-up:

- **Accept refreshable OAuth in the adapter availability check**
  (`f7aa0b1`). The pre-flight `_has_claude_auth()` rejected credentials
  whose access token had expired even when a valid refresh token was
  present, surfacing as a misleading "Claude CLI is not authenticated"
  error inside long-lived sandboxes. A refresh token alone is enough
  for claude to mint a new access token on demand.
- **Seed credentials with refresh tokens even if access expired**
  (`bf96a92`). Mirror of the same relaxation on the deploy/seed path,
  so a host whose only on-disk creds had a stale access token but a
  valid refresh would still seed a usable file.
- **Surface api_retry events; persist refreshed credentials**
  (`cde9a6a`). Two fixes: (1) render `system/api_retry` stream-json
  events instead of dropping them, so a stuck refresh or transport
  storm is visible in the UI rather than looking like a silent hang;
  (2) add `AgentAdapter.finalize_env(env, run_tmp)` and override it
  in the Claude adapter to mirror a refreshed `.credentials.json` from
  the isolated `CLAUDE_CONFIG_DIR` back to the source path. Without
  this, every chat send started from the same expired access token,
  refreshed, then discarded the new token along with the run-tmp dir.
- **Prevent OAuth refresh stampedes** (`544209b`). Process-local
  `threading.Lock` around refreshes triggered when the source
  credentials are expiring within the skew window, so concurrent
  chats / workers don't all refresh in parallel and trip rate
  limits.
- **Provide system CA bundle to Claude** (`61bf4c5`). Sets
  `SSL_CERT_FILE` and `SSL_CERT_DIR` in the claude subprocess env.
  See "Open issues" below — Node ignores these env vars, so this
  is largely a no-op for `claude`, but it's harmless and may help
  child OpenSSL-based tools claude shells out to.

## Open issues and sharp edges

### Residual transport-level retries

Even with the FD ceiling raised, claude can still emit a small number of
`error=unknown` `api_retry` events at low rate (often 0–2 per chat).
These are *not* the cert-verification storm fixed above — claude's
debug log shows a different underlying error class. They behave like
ordinary network jitter: claude's exponential backoff catches them
within seconds. They are at the level of "this happens occasionally
on any network" rather than a Microsandbox-specific bug. We have no
focused investigation here yet; if they grow to a UX problem, set
`ANTHROPIC_LOG=debug` in [`claude_adapter.py`'s `prepare_env`](../server/agents/claude_adapter.py)
to surface the actual error message on stderr.

### Werkzeug 500s on websocket upgrade are cosmetic

The Bullpen log inside the sandbox accumulates entries like:

```
GET /socket.io/?EIO=4&transport=websocket HTTP/1.1" 500 -
Error on request:
  ...
  AssertionError: write() before start_response
```

These look alarming but are **not actual failures**. Confirmed via
isolated test: a stripped-down Flask-SocketIO server in the same
sandbox produced 60/60 successful client connects while logging
60 of these 500 entries. The pattern is werkzeug's WSGI runner
trying to write a closing zero-byte chunk *after* `simple-websocket`
has already hijacked the socket for the upgrade. Cosmetic noise.

We could quiet this by switching `async_mode` from `threading` to
`eventlet` (already in `requirements.txt`), but that requires
auditing every blocking call in the codebase for eventlet
compatibility — and threading mode demonstrably works once the
upgrade is complete. Not worth the regression risk.

### Claude has no serializing wrapper; Codex does

Codex runs through [`/home/bullpen/bin/codex`](../sandboxed-bullpen.py) — a
wrapper installed by `install_codex_wrapper` that grabs an `mkdir`-based
lock at `/var/lib/bullpen/codex.lock` and admits one codex invocation at
a time. Even under heavy load only one codex is alive.

Claude has no equivalent. Live Agent chats and worker dispatches each
spawn their own claude in parallel. Under any kind of resource pressure
claude trips before codex does, structurally — it has many more
concurrent FDs, sockets, and subprocesses in flight per equivalent user
action.

If FD pressure recurs from another source (e.g. a future change that
adds more parallelism), wrapping claude the way codex is wrapped would
make its behavior match codex's reliability under pressure. Not
necessary today; flagging it because it's the structural answer if the
symptom comes back.

### IPv6 ULA networking

The microVM gets an IPv6 ULA address (`fd42:6d73:62:3a::2/64`) and an
IPv6 default gateway. Outbound IPv6 to public destinations does **not**
work cleanly: TCP connect to e.g. `2607:6bc0::10` (Anthropic's IPv6
address) succeeds, but the TLS handshake dies with `SSL_ERROR_SYSCALL`
mid-handshake. Looks like an MTU / silent-drop issue at the host
gateway.

Practical impact is small: Node's `getaddrinfo` returns IPv4 first per
`/etc/gai.conf`, and Node's `fetch` (`undici`) does Happy Eyeballs and
falls back to IPv4 when the v6 attempt isn't responsive. Both end up
on `160.79.104.10` (v4) which is reliable. Tools that explicitly
prefer v6 (`curl -6`) will fail visibly.

If we ever do see Node taking the v6 path and breaking, set
`NODE_OPTIONS=--dns-result-order=ipv4first` in
[`claude_adapter.py`'s `prepare_env`](../server/agents/claude_adapter.py).
This was tested in isolation during diagnosis and works as a one-line
hammer-fix; we deliberately did not ship it because it papers over a
Microsandbox networking issue rather than fixing it, and the v4 path
is reached by default anyway.

### Browser dual-stack delay on "localhost"

The deploy prints `UI: http://localhost:8080`. Browsers on macOS
resolve `localhost` to both `::1` and `127.0.0.1` and try IPv6 first
(Happy Eyeballs). Microsandbox's host-side port forward listens on
v4 only, so the v6 attempt times out (low single-digit seconds on
modern macOS) before the browser falls back to v4. The user sees
this as several seconds of "nothing happens after pressing Enter".

Workaround: use `http://127.0.0.1:8080` instead. Could also be fixed
by making `sandboxed-bullpen.py` print the v4 literal in the success
output.

### Microsandbox bind-mount syscall errors under load

Under sustained heavy I/O against the `/home/bullpen` bind mount
(host `~/.bullpen/microsandbox-home`), Node has been observed to
abort with:

```
node::fs::ReadFileUtf8 ... Assertion failed:
  (0) == (uv_fs_close(nullptr, &req, file, nullptr))
```

— libuv asserting on an unexpected `close()` syscall return. We saw
this only during heavy diagnostic loops (rapidly spawning tens of
`node` processes via `msb exec`); it does not appear to surface
under normal Bullpen activity. If it ever does, suspect bind-mount
or virtio-fs queue-depth issues at the Microsandbox layer rather
than anything fixable in Bullpen code.

### `msb exec` accumulates FDs in the calling shell

Repeated `msb exec` invocations from the host appear to leak file
descriptors in the shared shell session inside the guest. After a
long enough diagnostic session, basic operations like
`chown -R /home/bullpen/test-harness` start failing with
`Too many open files`. A sandbox restart clears it.

This was visible only during the diagnostic deep-dive; users
exercising the system through the browser don't trigger it. It is
*not* the same FD pressure as the bullpen-user RLIMIT issue fixed
above — that one was per-process limits applied via pam; this one
is shared sandbox-session state.

### Per-run `CLAUDE_CONFIG_DIR` is architecturally fragile

[`server/agents/claude_adapter.py`](../server/agents/claude_adapter.py)
creates a fresh `/tmp/bullpen-claude-XXX/claude-config/` per
invocation, copies the credentials in, runs claude, then syncs any
refreshed credentials back to source via `finalize_env`. The
motivation is real (avoid hooks/plugins/sessions polluting agent
runs), but the implementation has two latent risks:

1. If the bullpen process is killed between a successful refresh
   and `finalize_env`, the refreshed access token (and rotated
   refresh token, if Anthropic rotated) lives only in the
   doomed `run_tmp`, never reaches source. Source still has the
   pre-refresh tokens. If refresh tokens rotate, the next run
   has a dead refresh token and can't recover.
2. The `_CLAUDE_OAUTH_REFRESH_LOCK` is a process-local
   `threading.Lock` — it serializes inside one Bullpen process
   but doesn't span any other concurrent claude. Multiple
   bullpen processes would race here; we don't run that way
   today, but it's a future hazard.

The architectural answer is to drop the per-run isolated dir and
let claude write directly to `/home/bullpen/.claude/`, with
`--no-session-persistence` and `--setting-sources user` keeping
hooks/sessions out. That's not urgent; flagged because every
diagnostic session that ends abnormally leaves an orphan
`/tmp/bullpen-claude-*` and a defunct claude / python in the
process table.

### Compound retry amplification

[`server/events.py`](../server/events.py)'s `_run_chat` retries the
entire claude subprocess up to `_CLAUDE_MCP_STARTUP_RETRIES = 3`
times if MCP startup looks unhealthy. Claude's own SDK retries
each API call up to 10 times. Multiplied, a single platform-level
hiccup can cascade into 30 retry events. The FD-pressure fix
removes the most common trigger; if the residual transport-error
class above grows, consider tightening one of these retry
budgets or making the outer retry conditional on specific
failure shapes.

### `SSL_CERT_FILE` is a no-op for Node

The fix in `61bf4c5` sets `SSL_CERT_FILE` and `SSL_CERT_DIR` in the
claude subprocess env. These are honored by OpenSSL-linked
libraries; **Node ignores them** and uses its bundled CA store.
Node's equivalent is `NODE_EXTRA_CA_CERTS`. The current setting
doesn't hurt anything (and may help OpenSSL-based tools claude
shells out to, e.g. `git`), but we should not look at it as
evidence that claude has the system CA bundle wired up.

If a corporate-proxy-style CA situation ever arises, the right
move is to also set `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt`
in [`claude_adapter.py`'s `prepare_env`](../server/agents/claude_adapter.py).

## Diagnosis pointers

A few observations from the deep-dive that future debugging should not
have to re-derive.

### `error=unknown` does not mean "we don't know what happened"

It means "the error has no HTTP `status` field." Decoded from the
claude binary, the classifier `Qh9` returns one of `"rate_limit"`,
`"authentication_failed"`, `"server_error"`, or `"unknown"` based on
HTTP status. `"unknown"` is the default for transport-level errors
where no HTTP response was received: DNS failures, TCP resets,
TLS handshake aborts, fetch timeouts. The actual underlying error
*is* available — set `ANTHROPIC_LOG=debug` and read claude's stderr.

### To get the real error from claude

Add to [`claude_adapter.py`'s `prepare_env`](../server/agents/claude_adapter.py)
temporarily:

```python
env.setdefault("ANTHROPIC_LOG", "debug")
```

`ANTHROPIC_LOG=debug` makes the SDK print every request, response,
and error to claude's stdout — which Bullpen captures and stores.
The error object's `message` field tells you the actual TLS / DNS /
HTTP cause that the bucket label `error=unknown` is hiding.

### To probe network reliability inside the sandbox

```bash
msb exec bullpen -- bash -c '
  for i in 1 2 3 4 5; do
    curl -sS -o /dev/null -w "[$i] http=%{http_code} tcp=%{time_connect}s tls=%{time_appconnect}s total=%{time_total}s\n" \
      --max-time 15 https://api.anthropic.com/v1/models
  done
'
```

A clean run is 5/5 with sub-250ms totals. Variance suggests the
microVM network or upstream is in a stressed state.

## Verifying the FD-limit fix after redeploy

After `python3 sandboxed-bullpen.py --replace`:

```bash
msb exec bullpen -- su -s /bin/bash bullpen -c 'ulimit -Hn'
# expect: 65536
```

If that prints `4096`, the limits.d drop-in didn't apply. The deploy
also emits a `warn: bullpen RLIMIT_NOFILE hard limit is N, expected
65536` to stderr when this happens, so it should be visible during
deploy without needing an after-the-fact check.

## References

- Architecture spec: [microsandbox.md](microsandbox.md)
- Fix commit: `d4778b6` — `fix: lift Microsandbox bullpen RLIMIT_NOFILE via pam_limits`
- Related earlier commits: `f7aa0b1`, `bf96a92`, `cde9a6a`, `544209b`, `61bf4c5`
- Claude adapter: [server/agents/claude_adapter.py](../server/agents/claude_adapter.py)
- Codex serializing wrapper, for reference: `install_codex_wrapper` in
  [sandboxed-bullpen.py](../sandboxed-bullpen.py)
