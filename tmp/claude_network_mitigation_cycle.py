#!/usr/bin/env python3
"""Noninteractive Microsandbox cycle for the Claude IPv6 mitigation."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import shlex
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SANDBOXED_BULLPEN = ROOT / "sandboxed-bullpen.py"


def load_sandboxed_bullpen() -> Any:
    spec = importlib.util.spec_from_file_location("sandboxed_bullpen_network_cycle", SANDBOXED_BULLPEN)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Unable to load {SANDBOXED_BULLPEN}")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sb = load_sandboxed_bullpen()


def output_text(result: Any) -> str:
    stdout = getattr(result, "stdout_text", "") or getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr_text", "") or getattr(result, "stderr", "") or ""
    return "\n".join(part for part in (stdout, stderr) if part)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Claude IPv6 mitigation in a fresh Microsandbox")
    parser.add_argument("--sandbox-name", default="bullpen-claude-network-cycle")
    parser.add_argument("--base", default=sb.BASE_DEFAULT)
    parser.add_argument("--sandbox-home", default=str(ROOT / "tmp" / "microsandbox-claude-network-cycle-home"))
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", dest="cleanup", action="store_false")
    return parser.parse_args()


def make_config(args: argparse.Namespace) -> Any:
    sandbox_home = Path(args.sandbox_home).expanduser().resolve()
    sandbox_home.mkdir(parents=True, exist_ok=True)
    return sb.DeployConfig(
        sandbox_name=args.sandbox_name,
        workspace=ROOT,
        bullpen_port=sb.BULLPEN_PORT_DEFAULT,
        app_port=sb.APP_PORT_DEFAULT,
        admin_user=sb.ADMIN_USER_DEFAULT,
        admin_password="cycle-test",
        base=args.base,
        sandbox_home=sandbox_home,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url=sb.BULLPEN_GITHUB_REPO_URL_DEFAULT,
        local_project_path_default=ROOT / "tmp" / "unused-project",
    )


async def main_async() -> int:
    args = parse_args()
    config = make_config(args)
    sb.build_runtime_env(config)
    runtime = sb.MicrosandboxRuntime()
    await runtime.ensure_installed()
    await sb.replace_existing_sandbox(runtime, config)

    print(f"Creating cycle sandbox: {config.sandbox_name}", flush=True)
    sandbox = await runtime.create(config)
    try:
        await sb.prepare_runtime_dirs(sandbox, config)
        await sb.verify_mount_access(sandbox, config)

        print("Before mitigation:", flush=True)
        before = await sb.run_sandbox_shell(
            sandbox,
            "for name in all default eth0; do path=/proc/sys/net/ipv6/conf/${name}/disable_ipv6; "
            "[ -e \"$path\" ] && printf '%s=%s\\n' \"$name\" \"$(cat \"$path\")\"; done",
            check=False,
        )
        print(output_text(before).strip(), flush=True)

        await sb.disable_guest_ipv6_for_claude(sandbox)

        probe_command = r'''
set -e
echo "ipv6 flags"
for name in all default eth0; do
  path="/proc/sys/net/ipv6/conf/${name}/disable_ipv6"
  [ -e "$path" ] || continue
  value="$(cat "$path")"
  echo "$name=$value"
  [ "$value" = 1 ]
done
echo "dns"
getent ahosts platform.claude.com | sed -n '1,6p'
echo "curl4 platform"
curl -4 -fsSIL --connect-timeout 8 https://platform.claude.com/ | sed -n '1,5p'
echo "openssl4 platform"
timeout 8s openssl s_client -connect 160.79.104.10:443 -servername platform.claude.com -brief </dev/null 2>&1 | sed -n '1,8p'
echo "curl6 platform expected-fail"
if curl -6 -fsSIL --connect-timeout 4 https://platform.claude.com/ >/tmp/curl6.out 2>/tmp/curl6.err; then
  cat /tmp/curl6.out
  echo "unexpected IPv6 success" >&2
  exit 1
fi
sed -n '1,4p' /tmp/curl6.err
echo "cycle OK"
'''
        result = await sb.run_sandbox_shell(sandbox, f"bash -lc {shlex.quote(probe_command)}", check=False)
        text = output_text(result)
        print(text, end="" if text.endswith("\n") else "\n")
        returncode = getattr(result, "returncode", None)
        if returncode is None:
            returncode = getattr(result, "exit_code", None)
        if returncode not in (None, 0):
            return int(returncode)
        return 0
    finally:
        if args.cleanup:
            await runtime.stop(config.sandbox_name)
            try:
                await runtime.remove(config.sandbox_name)
            except Exception:
                await asyncio.sleep(1)
                await runtime.remove(config.sandbox_name)


def main() -> int:
    try:
        return asyncio.run(main_async())
    except sb.DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
