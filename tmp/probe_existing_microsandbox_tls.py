#!/usr/bin/env python3
"""Run targeted TLS family probes in an existing Microsandbox."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import shlex
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SANDBOXED_BULLPEN = ROOT / "sandboxed-bullpen.py"


def load_sandboxed_bullpen() -> Any:
    spec = importlib.util.spec_from_file_location("sandboxed_bullpen_tls_probe", SANDBOXED_BULLPEN)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Unable to load {SANDBOXED_BULLPEN}")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sb = load_sandboxed_bullpen()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe forced IPv4/IPv6 TLS inside an existing Microsandbox")
    parser.add_argument("--sandbox-name", default="bullpen-tls-family-probe")
    parser.add_argument("--base", default=sb.BASE_DEFAULT)
    parser.add_argument("--sandbox-home", default=str(ROOT / "tmp" / "microsandbox-tls-family-probe-home"))
    parser.add_argument("--no-replace", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--host", action="append", default=["api.anthropic.com", "platform.claude.com"])
    return parser.parse_args()


def output_text(result: Any) -> str:
    stdout = getattr(result, "stdout_text", "") or getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr_text", "") or getattr(result, "stderr", "") or ""
    return "\n".join(part for part in (stdout, stderr) if part)


async def main_async() -> int:
    args = parse_args()
    runtime = sb.MicrosandboxRuntime()
    await runtime.ensure_installed()
    config = sb.DeployConfig(
        sandbox_name=args.sandbox_name,
        workspace=ROOT,
        bullpen_port=sb.BULLPEN_PORT_DEFAULT,
        app_port=sb.APP_PORT_DEFAULT,
        admin_user=sb.ADMIN_USER_DEFAULT,
        admin_password="",
        base=args.base,
        sandbox_home=Path(args.sandbox_home).expanduser().resolve(),
        replace=not args.no_replace,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url=sb.BULLPEN_GITHUB_REPO_URL_DEFAULT,
        local_project_path_default=ROOT / "tmp" / "unused-project",
    )
    config.sandbox_home.mkdir(parents=True, exist_ok=True)
    sb.build_runtime_env(config)
    if config.replace:
        await sb.replace_existing_sandbox(runtime, config)
    sandbox = await runtime.create(config)

    hosts = " ".join(args.host)
    command = f"""
set -u
for host in {hosts}; do
  echo "### $host"
  echo "# getent"
  getent ahosts "$host" || true
  for family in 4 6; do
    echo "# curl -$family"
    curl -$family -fsSIL --connect-timeout 8 "https://$host/" >/tmp/curl-family-probe.out 2>/tmp/curl-family-probe.err
    status=$?
    echo "curl_exit=$status"
    sed -n '1,5p' /tmp/curl-family-probe.out || true
    sed -n '1,8p' /tmp/curl-family-probe.err || true
  done
  for target in 160.79.104.10 '[2607:6bc0::10]'; do
    echo "# openssl $target"
    timeout 8s openssl s_client -connect "$target:443" -servername "$host" -brief </dev/null >/tmp/openssl-family-probe.out 2>&1
    status=$?
    echo "openssl_exit=$status"
    sed -n '1,12p' /tmp/openssl-family-probe.out || true
  done
done
"""
    try:
        await sb.prepare_runtime_dirs(sandbox, config)
        result = await sb.run_sandbox_shell(sandbox, f"bash -lc {shlex.quote(command)}", check=False)
        print(output_text(result), end="")
    finally:
        if args.cleanup:
            await runtime.stop(config.sandbox_name)
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    await runtime.remove(config.sandbox_name)
                    break
                except Exception as exc:
                    if "still running" not in str(exc).lower():
                        raise
                    await asyncio.sleep(0.5)
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except sb.DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
