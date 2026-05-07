#!/usr/bin/env python3
"""
Microsandbox session with authenticated Claude Code CLI.

Usage:
    python3 msb_claude.py                    # create sandbox, install, seed creds, validate
    python3 msb_claude.py "your prompt"      # run a query on existing (or new) sandbox
    python3 msb_claude.py --destroy          # stop and remove the sandbox
"""

import asyncio
import json
import shlex
import socket
import subprocess
import sys

from microsandbox import Sandbox

SANDBOX_NAME = "claude-code"
IMAGE = "node:20-bookworm-slim"

SANDBOX_CONFIG = {
    "name": SANDBOX_NAME,
    "image": IMAGE,
    "memory_mib": 4096,
    "vcpu": 4,
    "network": {"policy": "allow_all"},
    "rlimits": [{"resource": "nofile", "soft": 65535, "hard": 65535}],
}


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def get_credentials() -> dict:
    """Read Claude Code OAuth credentials from macOS Keychain."""
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Keychain read failed: {r.stderr.strip()}")
    return json.loads(r.stdout.strip())


# ---------------------------------------------------------------------------
# Sandbox lifecycle
# ---------------------------------------------------------------------------

async def get_or_create_sandbox() -> tuple[Sandbox, bool]:
    """Return (sandbox, is_new). is_new means first-time setup is needed."""
    handles = await Sandbox.list()
    for h in handles:
        if h.name == SANDBOX_NAME:
            print(f"Found existing sandbox '{SANDBOX_NAME}' (status: {h.status})...")
            if h.status == "running":
                return await h.connect(), False
            else:
                # Stopped sandbox: Bun binaries crash on VM restart due to memory
                # remapping issues. Destroy and recreate cleanly.
                print(f"  Sandbox is stopped — Bun crashes on restart. Recreating...")
                await h.remove()
                break

    print(f"Creating sandbox '{SANDBOX_NAME}' from '{IMAGE}'...")
    sb = await Sandbox.create(SANDBOX_CONFIG)
    return sb, True


# ---------------------------------------------------------------------------
# IPv4 host override (Bun's Happy Eyeballs prefers IPv6, but the microVM's
# IPv6 path drops TLS connections silently — override with IPv4-only entries)
# ---------------------------------------------------------------------------

_ANTHROPIC_DOMAINS = [
    "api.anthropic.com",
    "claude.ai",
    "statsig.anthropic.com",
    "sentry.io",
]

def _patch_hosts_ipv4(current: str) -> str:
    entries = []
    for domain in _ANTHROPIC_DOMAINS:
        try:
            addrs = socket.getaddrinfo(domain, 443, socket.AF_INET)
            ip = addrs[0][4][0]
            entries.append(f"{ip}  {domain}")
        except Exception:
            pass
    if not entries:
        return current
    marker = "# ipv4-only: anthropic domains"
    if marker in current:
        return current  # already patched
    return current + f"\n{marker}\n" + "\n".join(entries) + "\n"


# ---------------------------------------------------------------------------
# Setup (one-time, runs while VM is fresh)
# ---------------------------------------------------------------------------

async def setup(sb: Sandbox) -> None:
    """Install ca-certificates + claude-code, seed credentials."""
    print("  Installing ca-certificates...")
    r = await sb.shell(
        "apt-get update -qq 2>&1 && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates 2>&1"
    )
    if not r.success:
        print(r.stdout_text[-2000:])
        raise RuntimeError(f"ca-certificates install failed (exit {r.exit_code})")

    print("  Installing @anthropic-ai/claude-code (~45s)...")
    r = await sb.shell("npm install -g @anthropic-ai/claude-code 2>&1")
    if not r.success:
        print(r.stdout_text[-2000:])
        raise RuntimeError(f"claude-code npm install failed (exit {r.exit_code})")

    print("  Seeding credentials from keychain...")
    creds = get_credentials()
    await sb.fs.mkdir("/root/.claude")
    await sb.fs.write("/root/.claude/.credentials.json", json.dumps(creds).encode())
    # Suppress onboarding prompts
    await sb.fs.write("/root/.claude.json", json.dumps({"hasCompletedOnboarding": True}).encode())

    print("  Patching /etc/hosts to force IPv4 (Bun hangs on IPv6 in microVM)...")
    _patch_hosts_ipv4(await sb.fs.read_text('/etc/hosts'))
    await sb.fs.write('/etc/hosts', _patch_hosts_ipv4(await sb.fs.read_text('/etc/hosts')).encode())
    print("  Setup done.")


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

async def run_query(sb: Sandbox, prompt: str, timeout: float = 120.0) -> str:
    # Run via bash -c so stdin is explicitly redirected from /dev/null.
    # When claude is launched with a piped stdin (the default when using
    # exec()), it waits up to 3s for input before erroring.
    cmd = f"HOME=/root claude -p {shlex.quote(prompt)} < /dev/null"
    r = await sb.exec("bash", {
        "args": ["-c", cmd],
        "timeout": timeout,
    })
    if not r.success:
        raise RuntimeError(
            f"claude exited {r.exit_code}\n"
            f"STDOUT: {r.stdout_text}\n"
            f"STDERR: {r.stderr_text}"
        )
    return r.stdout_text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    args = sys.argv[1:]

    if args == ["--destroy"]:
        for h in await Sandbox.list():
            if h.name == SANDBOX_NAME:
                print(f"Stopping and removing '{SANDBOX_NAME}'...")
                await h.kill()
                await h.remove()
                print("Done.")
                return
        print(f"Sandbox '{SANDBOX_NAME}' not found.")
        return

    prompt = args[0] if args else None

    sb, is_new = await get_or_create_sandbox()

    if is_new:
        await setup(sb)

        print("\nValidating...")
        r = await sb.shell("HOME=/root claude --version < /dev/null 2>&1")
        if not r.success:
            print(r.stdout_text)
            raise RuntimeError(f"claude --version failed (exit {r.exit_code})")
        print(f"  claude --version => {r.stdout_text.strip()}")

        print("  Running test query...")
        out = await run_query(sb, "Reply with exactly: hello from microsandbox")
        print(f"  Response: {out.strip()}")

        # Detach so the sandbox keeps running after this process exits.
        # Bun (claude's runtime) crashes on VM restart, so we must keep
        # the sandbox alive between queries.
        await sb.detach()
        print(f"\nSandbox detached and running. Query with:")
        print(f"  python3 {sys.argv[0]} \"your question here\"")

    elif prompt is None:
        r = await sb.shell("HOME=/root claude --version < /dev/null 2>&1")
        print(f"claude --version => {r.stdout_text.strip()}")
        await sb.detach()
    else:
        out = await run_query(sb, prompt)
        print(out.strip())
        await sb.detach()


asyncio.run(main())
