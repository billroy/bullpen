#!/usr/bin/env python3
"""Experiment: try to run Microsandbox inside Microsandbox.

Success criterion:
    An outer Debian/Ubuntu Microsandbox installs the Linux Microsandbox CLI and
    successfully runs an inner Alpine sandbox command.

Example:
    python3 tmp/nested_msb_experiment.py
    python3 tmp/nested_msb_experiment.py --outer-image ubuntu:24.04
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import re
import shlex
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OUTER_IMAGE = "debian:bookworm"
DEFAULT_INNER_IMAGE = "alpine"
DEFAULT_OUTER_NAME = "bullpen-nested-msb-experiment"
SANDBOX_NAME_RE = re.compile(r'\b(msb-[0-9a-f]{8,})\b')


@dataclass
class StepResult:
    label: str
    exit_code: int | None
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code in (None, 0)


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def output_text(result: Any, name: str) -> str:
    return getattr(result, f"{name}_text", "") or getattr(result, name, "") or ""


def exit_code(result: Any) -> int | None:
    code = getattr(result, "exit_code", None)
    if code is None:
        code = getattr(result, "returncode", None)
    status = getattr(result, "exit_status", None)
    if code is None and status is not None:
        code = getattr(status, "code", None)
    success = getattr(result, "success", None)
    if success is False and code is None:
        code = 1
    return code


async def run_step(sandbox: Any, label: str, command: str, *, check: bool = True) -> StepResult:
    print(f"\n==> {label}", flush=True)
    result = await maybe_await(sandbox.exec("bash", ["-lc", command]))
    step = StepResult(
        label=label,
        exit_code=exit_code(result),
        stdout=output_text(result, "stdout"),
        stderr=output_text(result, "stderr"),
    )
    if step.stdout:
        print(step.stdout, end="" if step.stdout.endswith("\n") else "\n")
    if step.stderr:
        print(step.stderr, end="" if step.stderr.endswith("\n") else "\n", file=sys.stderr)
    if check and not step.ok:
        raise RuntimeError(f"{label} failed with exit code {step.exit_code}")
    return step


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Try running msb inside an msb sandbox")
    parser.add_argument("--outer-image", default=DEFAULT_OUTER_IMAGE)
    parser.add_argument("--inner-image", default=DEFAULT_INNER_IMAGE)
    parser.add_argument("--outer-name", default=DEFAULT_OUTER_NAME)
    parser.add_argument("--cpus", type=int, default=2)
    parser.add_argument("--memory-mib", type=int, default=2048)
    parser.add_argument("--timeout", default="90s", help="Timeout for the inner msb run command")
    parser.add_argument("--keep-outer", action="store_true", help="Leave the outer sandbox running for inspection")
    parser.add_argument(
        "--microsandbox-version",
        help="Version to pip install inside the outer sandbox. Defaults to the host SDK version.",
    )
    return parser


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    microsandbox = importlib.import_module("microsandbox")
    version = args.microsandbox_version or str(await maybe_await(microsandbox.version()))

    if hasattr(microsandbox, "is_installed"):
        installed = await maybe_await(microsandbox.is_installed())
        if not installed:
            await maybe_await(microsandbox.install())

    try:
        await maybe_await(microsandbox.Sandbox.remove(args.outer_name))
    except Exception:
        pass

    print(
        textwrap.dedent(
            f"""
            Nested Microsandbox experiment
              outer: {args.outer_image} ({args.outer_name})
              inner: {args.inner_image}
              SDK:   microsandbox=={version}
            """
        ).strip()
    )

    sandbox = await maybe_await(
        microsandbox.Sandbox.create(
            args.outer_name,
            image=microsandbox.Image.oci(args.outer_image),
            replace=True,
            detached=True,
            cpus=args.cpus,
            memory=args.memory_mib,
            network=microsandbox.Network.allow_all(),
        )
    )

    try:
        await run_step(
            sandbox,
            "outer host diagnostics",
            r"""
            set -euo pipefail
            uname -a
            cat /etc/os-release | sed -n '1,6p'
            echo
            echo "virtualization devices:"
            ls -l /dev/kvm /dev/vhost-vsock /dev/vsock 2>&1 || true
            echo
            echo "cpu virtualization flags:"
            grep -Eom1 '(^| )(vmx|svm)( |$)' /proc/cpuinfo || true
            """,
        )
        await run_step(
            sandbox,
            "install Python and Microsandbox inside outer sandbox",
            f"""
            set -euo pipefail
            export DEBIAN_FRONTEND=noninteractive
            apt-get update
            apt-get install -y --no-install-recommends ca-certificates python3 python3-venv python3-pip
            rm -rf /var/lib/apt/lists/*
            python3 -m venv /opt/nested-msb-venv
            /opt/nested-msb-venv/bin/python -m pip install --upgrade pip
            /opt/nested-msb-venv/bin/python -m pip install {shlex.quote("microsandbox==" + version)}
            /opt/nested-msb-venv/bin/python - <<'PY'
import microsandbox
from microsandbox._runtime import msb_path
print("python-sdk", microsandbox.version())
print("msb-path", msb_path())
PY
            """,
        )
        nested_command = f"""
            set -euo pipefail
            MSB_BIN="$(
              /opt/nested-msb-venv/bin/python - <<'PY'
from microsandbox._runtime import msb_path
print(msb_path())
PY
            )"
            "$MSB_BIN" --version
            "$MSB_BIN" run --timeout {shlex.quote(args.timeout)} {shlex.quote(args.inner_image)} -- /bin/sh -lc 'echo INNER_OK; cat /etc/os-release | sed -n "1,4p"; uname -a'
        """
        nested = await run_step(
            sandbox,
            "run inner Alpine sandbox from inside outer sandbox",
            nested_command,
            check=False,
        )
        if nested.ok and "INNER_OK" in nested.stdout:
            print("\nRESULT: SUCCESS - inner Alpine command ran inside outer Microsandbox.")
            return 0
        names = sorted(set(SANDBOX_NAME_RE.findall(nested.stdout + "\n" + nested.stderr)))
        for name in names:
            quoted = shlex.quote(name)
            await run_step(
                sandbox,
                f"nested sandbox diagnostics for {name}",
                f"""
                set -u
                MSB_BIN="$(
                  /opt/nested-msb-venv/bin/python - <<'PY'
from microsandbox._runtime import msb_path
print(msb_path())
PY
                )"
                echo "inspect:"
                "$MSB_BIN" inspect {quoted} 2>&1 || true
                echo
                echo "system logs:"
                "$MSB_BIN" logs --source system {quoted} 2>&1 || true
                echo
                echo "cleanup:"
                "$MSB_BIN" remove {quoted} 2>&1 || true
                """,
                check=False,
            )
        print("\nRESULT: FAILURE - inner Alpine command did not complete successfully.")
        return nested.exit_code or 1
    finally:
        if args.keep_outer:
            print(f"\nKeeping outer sandbox for inspection: {args.outer_name}")
        else:
            try:
                await maybe_await(sandbox.stop())
            except Exception:
                pass
            try:
                await maybe_await(microsandbox.Sandbox.remove(args.outer_name))
            except Exception:
                pass


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
