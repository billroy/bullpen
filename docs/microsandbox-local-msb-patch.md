# Local Microsandbox `msb` Patch

Date: 2026-05-23

This machine has a local Microsandbox SDK binary override installed while we wait
for the published-port wake fix to land upstream.

## What Changed

The Python Microsandbox wheel's bundled `msb` binary was replaced in place:

```text
/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/site-packages/microsandbox/_bundled/bin/msb
```

The original bundled binary was preserved here:

```text
/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/site-packages/microsandbox/_bundled/bin/msb.unpatched-0.4.4.20260523
```

The replacement binary is a locally built `msb 0.4.4` from the Microsandbox
`v0.4.4` source, with a small patch in the network published-port path:

- pass `SharedState` into `PortPublisher::new`
- pass it into each TCP published-port listener task
- call `shared.proxy_wake.wake()` immediately after an accepted host connection
  is queued with `inbound_tx.send(conn)`

That makes the smoltcp poll loop wake immediately for host-to-guest published
port connections instead of waiting for an unrelated timer/wake.

## Why

Bullpen page loads through Microsandbox were spending 10+ seconds in TTFB for
ordinary localhost static assets. A minimal diagnostic HTTP server inside the
sandbox reproduced the same behavior, proving the cause was not Bullpen, Flask,
nginx, or static asset architecture.

After the patched binary was installed and Bullpen was redeployed, the browser
HAR showed:

- `DOMContentLoaded`: about `98ms`
- `load`: about `152ms`
- local static asset p95 server wait: about `1.9ms`
- no 10-second localhost request plateaus

## How To Use

Use the normal deploy command. No `MSB_PATH`, wrapper script, or special
environment variable is needed:

```bash
python3 deploy-msb.py --replace \
  --sandbox-name bullpen-pr-workflow-test \
  --workspace /Users/bill/aistuff/pr-workflow-test \
  --bullpen-port 8080 \
  --app-port 3000 \
  --admin-password codex-proof-password \
  --no-open
```

To confirm a running sandbox is using the installed bundled binary:

```bash
ps -ax -o pid,command | rg 'bullpen-pr-workflow-test|_bundled/bin/msb|target/debug/msb'
```

Expected for the transparent patched environment: the sandbox process should use
the `_bundled/bin/msb` path, not an explicit `MSB_PATH` override.

## How To Undo

Stop any running sandbox first, then restore the original binary:

```bash
python3 - <<'PY'
import asyncio
import inspect
import microsandbox

async def maybe(value):
    if inspect.isawaitable(value):
        return await value
    return value

async def main():
    try:
        sandbox = await maybe(microsandbox.Sandbox.get("bullpen-pr-workflow-test"))
        stop = getattr(sandbox, "stop", None)
        if callable(stop):
            await maybe(stop())
    except Exception:
        pass

asyncio.run(main())
PY
```

```bash
cp -p \
  /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/site-packages/microsandbox/_bundled/bin/msb.unpatched-0.4.4.20260523 \
  /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/site-packages/microsandbox/_bundled/bin/msb
```

Then redeploy normally. If Microsandbox is upgraded or reinstalled, this local
binary replacement may be overwritten by the package manager; in that case, use
the upstream release once it contains the published-port wake fix.
