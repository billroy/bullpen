#!/usr/bin/env python3
"""Run VGER inside the minimal Microsandbox runtime shape."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SANDBOX = ROOT / "deploy-sandbox.py"


def load_deploy_sandbox() -> Any:
    spec = importlib.util.spec_from_file_location("deploy_sandbox_vger", DEPLOY_SANDBOX)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Unable to load {DEPLOY_SANDBOX}")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sb = load_deploy_sandbox()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VGER inside Microsandbox")
    parser.add_argument("--sandbox-name", default="bullpen-vger")
    parser.add_argument("--base", default=sb.BASE_DEFAULT)
    parser.add_argument("--sandbox-home", default=str(ROOT / "tmp" / "microsandbox-vger-home"))
    parser.add_argument("--no-replace", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    return parser.parse_args()


def make_config(args: argparse.Namespace) -> Any:
    sandbox_home = Path(args.sandbox_home).expanduser().resolve()
    root = ROOT.resolve()
    try:
        sandbox_home.relative_to(root)
    except ValueError as exc:
        raise sb.DeployError(f"Refusing to use sandbox home outside {root}: {sandbox_home}") from exc
    sandbox_home.mkdir(parents=True, exist_ok=True)
    return sb.DeployConfig(
        sandbox_name=args.sandbox_name,
        workspace=root,
        bullpen_port=sb.BULLPEN_PORT_DEFAULT,
        app_port=sb.APP_PORT_DEFAULT,
        admin_user=sb.ADMIN_USER_DEFAULT,
        admin_password="",
        base=args.base,
        sandbox_home=sandbox_home,
        replace=not args.no_replace,
        open_browser=False,
        install_bullpen_project=False,
        root=root,
        bullpen_source=root,
        github_repo_url=sb.BULLPEN_GITHUB_REPO_URL_DEFAULT,
        local_project_path_default=root / "tmp" / "unused-project",
    )


async def main_async() -> int:
    args = parse_args()
    config = make_config(args)
    sb.build_runtime_env(config)
    runtime = sb.MicrosandboxRuntime()
    await runtime.ensure_installed()
    if config.replace:
        await sb.replace_existing_sandbox(runtime, config)
    print(f"Creating VGER sandbox: {config.sandbox_name}", flush=True)
    sandbox = await runtime.create(config)
    try:
        await sb.prepare_runtime_dirs(sandbox, config)
        await sb.verify_mount_access(sandbox, config)
        command = (
            "set -e; "
            "cd /workspace; "
            "rm -rf /workspace/tmp/vger/sandbox; "
            "python3 /workspace/tmp/microsandbox_vger.py --label sandbox --out-dir /workspace/tmp/vger"
        )
        await sb.run_as_bullpen(sandbox, config, command, label="run VGER in Microsandbox")
    finally:
        if args.cleanup:
            await runtime.stop(config.sandbox_name)
            await runtime.remove(config.sandbox_name)
    print(ROOT / "tmp" / "vger" / "sandbox" / "summary.txt")
    print(ROOT / "tmp" / "vger" / "sandbox" / "vger.json")
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except sb.DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
