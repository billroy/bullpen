#!/usr/bin/env python3
"""Minimal Claude auth repro inside Microsandbox.

This intentionally avoids Bullpen startup and installer TUI plumbing. It uses
the same prepared base, sandbox user, guest workspace mount, and durable guest
home shape as deploy-sandbox.py, then runs only Claude auth diagnostics.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import shlex
import socket
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SANDBOX = ROOT / "deploy-sandbox.py"


def load_deploy_sandbox() -> Any:
    spec = importlib.util.spec_from_file_location("deploy_sandbox_repro", DEPLOY_SANDBOX)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Unable to load {DEPLOY_SANDBOX}")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sb = load_deploy_sandbox()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce Claude auth inside a minimal Microsandbox")
    parser.add_argument("--sandbox-name", default="bullpen-claude-auth-repro")
    parser.add_argument("--base", default=sb.BASE_DEFAULT)
    parser.add_argument("--workspace", default=str(ROOT))
    parser.add_argument("--sandbox-home", default=str(ROOT / "tmp" / "microsandbox-claude-auth-home"))
    parser.add_argument("--log", default="")
    parser.add_argument("--no-replace", action="store_true")
    parser.add_argument("--cleanup", action="store_true", help="Stop and remove the repro sandbox after the run")
    parser.add_argument("--trace-tls", action="store_true", help="Add Node --trace-tls output to the auth repro")
    parser.add_argument("--disable-ipv6", action="store_true", help="Diagnostic only: disable IPv6 in the guest before Claude auth")
    parser.add_argument(
        "--insecure-disable-tls-verification",
        action="store_true",
        help="Diagnostic only: set NODE_TLS_REJECT_UNAUTHORIZED=0 for Claude auth",
    )
    return parser.parse_args()


def make_config(args: argparse.Namespace) -> Any:
    sandbox_home = Path(args.sandbox_home).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve()
    root = ROOT.resolve()
    for path, label in ((sandbox_home, "sandbox home"), (workspace, "workspace")):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise sb.DeployError(f"Refusing to use {label} outside {root}: {path}") from exc
    workspace.mkdir(parents=True, exist_ok=True)
    sandbox_home.mkdir(parents=True, exist_ok=True)
    return sb.DeployConfig(
        sandbox_name=args.sandbox_name,
        workspace=workspace,
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


def output_text(result: Any) -> str:
    stdout = getattr(result, "stdout_text", "") or getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr_text", "") or getattr(result, "stderr", "") or ""
    return "\n".join(part for part in (stdout, stderr) if part)


async def copy_guest_file(sandbox: Any, guest_path: str, host_path: Path) -> None:
    result = await sb.run_sandbox_shell(sandbox, f"cat {shlex.quote(guest_path)}", check=False)
    host_path.parent.mkdir(parents=True, exist_ok=True)
    host_path.write_text(output_text(result), encoding="utf-8", errors="replace")


def summarize_proc_net_log(path: Path) -> list[str]:
    counts: dict[tuple[str, int | str, str], int] = {}
    first: dict[tuple[str, int | str, str], str] = {}
    last: dict[tuple[str, int | str, str], str] = {}
    local_ports: dict[tuple[str, int | str, str], set[str]] = {}
    current_ts = ""
    if not path.is_file():
        return []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("--- "):
            current_ts = line.strip("- ")
            continue
        parts = line.split()
        if len(parts) < 4 or not parts[0].endswith(":") or ":" not in parts[2]:
            continue
        local, remote, state = parts[1], parts[2], parts[3]
        host_hex, port_hex = remote.rsplit(":", 1)
        if host_hex in {"00000000", "00000000000000000000000000000000", "0100007F"}:
            continue
        try:
            if len(host_hex) == 8:
                ip = socket.inet_ntop(socket.AF_INET, bytes.fromhex(host_hex)[::-1])
            elif len(host_hex) == 32:
                ip = socket.inet_ntop(socket.AF_INET6, bytes.fromhex(host_hex))
            else:
                ip = host_hex
            port: int | str = int(port_hex, 16)
        except Exception:
            ip = host_hex
            port = port_hex
        key = (ip, port, state)
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, current_ts)
        last[key] = current_ts
        local_ports.setdefault(key, set()).add(local.rsplit(":", 1)[-1])
    lines = []
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        ip, port, state = key
        ports = ",".join(sorted(local_ports[key]))
        lines.append(f"{ip}:{port} state={state} count={count} first={first[key]} last={last[key]} local_ports={ports}")
    return lines


async def run_probe(sandbox: Any, config: Any, title: str, command: str) -> None:
    print(f"\n### {title}", flush=True)
    result = await sb.run_as_bullpen(sandbox, config, command, check=False)
    text = output_text(result).rstrip()
    if text:
        print(text, flush=True)


async def interactive_auth(
    runtime: Any,
    sandbox: Any,
    config: Any,
    *,
    log_path: Path,
    trace_tls: bool,
    insecure_disable_tls_verification: bool,
) -> int:
    attach = getattr(sandbox, "attach", None)
    if not callable(attach) or runtime.AttachOptions is None:
        raise sb.DeployError("Microsandbox SDK attach is required for this repro.")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise sb.DeployError("Claude auth repro requires an interactive terminal.")

    status_path = f"/tmp/claude-auth-repro-status-{int(time.time())}"
    run_id = int(time.time())
    guest_log_path = f"/home/bullpen/logs/claude-auth-repro-{run_id}.typescript"
    guest_net_log_path = f"/home/bullpen/logs/claude-auth-repro-{run_id}.net.log"
    guest_strace_log_path = f"/home/bullpen/logs/claude-auth-repro-{run_id}.strace.log"
    node_options = "--trace-tls" if trace_tls else ""
    insecure_env = "export NODE_TLS_REJECT_UNAUTHORIZED=0\n" if insecure_disable_tls_verification else ""
    auth_command = (
        "set -u\n"
        f"{sb.claude_tls_env_prefix()};\n"
        "export BUN_CONFIG_VERBOSE_FETCH=curl\n"
        f"{insecure_env}"
        "export NODE_DEBUG=tls,https,net\n"
        f"export NODE_OPTIONS={shlex.quote(node_options)}\n"
        "export DEBUG=claude:*,anthropic:*\n"
        "cd /workspace\n"
        f"NET_LOG={shlex.quote(guest_net_log_path)}\n"
        "(\n"
        "  while :; do\n"
        "    printf '\\n--- %s ---\\n' \"$(date -u +%s.%N)\"\n"
        "    if command -v ss >/dev/null 2>&1; then\n"
        "      ss -tnp state established 2>/dev/null || true\n"
        "    else\n"
        "      cat /proc/net/tcp /proc/net/tcp6 2>/dev/null || true\n"
        "    fi\n"
        "    sleep 0.1\n"
        "  done\n"
        ") > \"$NET_LOG\" 2>&1 &\n"
        "net_monitor_pid=$!\n"
        "cleanup_repro_monitor() { kill \"$net_monitor_pid\" 2>/dev/null || true; wait \"$net_monitor_pid\" 2>/dev/null || true; }\n"
        "trap cleanup_repro_monitor EXIT\n"
        "echo '--- claude auth login starting ---' >&2\n"
        f"if command -v strace >/dev/null 2>&1; then\n"
        f"  strace -ff -tt -s 256 -e trace=network -o {shlex.quote(guest_strace_log_path)} claude auth login\n"
        "else\n"
        "  echo 'strace unavailable in sandbox' >&2\n"
        "  claude auth login\n"
        "fi\n"
        "status=$?\n"
        "cleanup_repro_monitor\n"
        "trap - EXIT\n"
        "echo \"--- claude auth login exited: ${status} ---\" >&2\n"
        "exit \"$status\"\n"
    )
    configured = f"{sb.sandbox_env_prefix(config)}; {auth_command}"
    command = (
        f"mkdir -p /home/bullpen/logs; rm -f {shlex.quote(guest_log_path)} {shlex.quote(status_path)}; "
        f"script -q -e -c {shlex.quote('bash -lc ' + shlex.quote(configured))} {shlex.quote(guest_log_path)}; "
        "status=$?; "
        f"printf '%s\\n' \"$status\" > {shlex.quote(status_path)}; "
        "exit \"$status\""
    )
    options = runtime.AttachOptions(
        args=("-lc", command),
        user="bullpen",
        env={},
    )
    try:
        result = attach("bash", options)
        if hasattr(result, "__await__"):
            await result
    except Exception:
        pass

    status_result = await sb.run_sandbox_shell(
        sandbox,
        f"test -s {shlex.quote(status_path)} && cat {shlex.quote(status_path)}",
        check=False,
    )
    status_text = output_text(status_result).strip()
    if status_text:
        try:
            exit_code = int(status_text.splitlines()[-1])
        except ValueError:
            exit_code = 1
    else:
        exit_code = 1
    await copy_guest_file(sandbox, guest_log_path, log_path)
    net_log_path = log_path.with_suffix(".net.log")
    await copy_guest_file(sandbox, guest_net_log_path, net_log_path)
    summary = summarize_proc_net_log(net_log_path)
    if summary:
        summary_path = log_path.with_suffix(".net-summary.log")
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
        print(f"Network summary: {summary_path}", flush=True)
    strace_listing = await sb.run_sandbox_shell(
        sandbox,
        f"ls {shlex.quote(guest_strace_log_path)}* 2>/dev/null || true",
        check=False,
    )
    for guest_strace_path in output_text(strace_listing).splitlines():
        if guest_strace_path.strip():
            suffix = guest_strace_path.rsplit("/", 1)[-1].replace("claude-auth-repro-", "")
            await copy_guest_file(sandbox, guest_strace_path.strip(), log_path.with_name(f"{log_path.stem}.{suffix}"))
    await sb.run_sandbox_shell(sandbox, f"rm -f {shlex.quote(status_path)}", check=False)
    return exit_code


async def main_async() -> int:
    args = parse_args()
    config = make_config(args)
    sb.build_runtime_env(config)
    log_path = Path(args.log).expanduser().resolve() if args.log else ROOT / "tmp" / f"claude-auth-repro-{int(time.time())}.log"
    try:
        log_path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise sb.DeployError(f"Refusing to write log outside {ROOT.resolve()}: {log_path}") from exc

    runtime = sb.MicrosandboxRuntime()
    await runtime.ensure_installed()
    if config.replace:
        await sb.replace_existing_sandbox(runtime, config)

    print(f"Creating repro sandbox: {config.sandbox_name}", flush=True)
    sandbox = await runtime.create(config)
    try:
        await sb.prepare_runtime_dirs(sandbox, config)
        await sb.verify_mount_access(sandbox, config)
        if args.disable_ipv6:
            await sb.run_sandbox_shell(
                sandbox,
                "sysctl -w net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1 net.ipv6.conf.eth0.disable_ipv6=1 || true",
                check=False,
            )
        await run_probe(sandbox, config, "identity and versions", "id; printf 'HOME=%s\\n' \"$HOME\"; command -v claude; claude --version; node --version")
        await run_probe(
            sandbox,
            config,
            "diagnostic tool availability",
            "for tool in ss strace openssl getent; do "
            "path=\"$(command -v \"$tool\" 2>/dev/null || true)\"; "
            "if [ -n \"$path\" ]; then printf '%s=%s\\n' \"$tool\" \"$path\"; else printf '%s=missing\\n' \"$tool\"; fi; "
            "done",
        )
        await run_probe(
            sandbox,
            config,
            "trust store and direct TLS probes",
            "ls -l /etc/ssl/certs/ca-certificates.crt; "
            "curl -fsSIL https://console.anthropic.com >/dev/null && echo 'curl console OK'; "
            "node -e \"require('https').get('https://console.anthropic.com', r => { console.log('node console status', r.statusCode); r.resume(); }).on('error', e => { console.error(e); process.exit(1); })\"",
        )
        print(f"\n### claude auth login\nLog: {log_path}", flush=True)
        exit_code = await interactive_auth(
            runtime,
            sandbox,
            config,
            log_path=log_path,
            trace_tls=args.trace_tls,
            insecure_disable_tls_verification=args.insecure_disable_tls_verification,
        )
        await run_probe(
            sandbox,
            config,
            "post-auth claude file metadata",
            "find /home/bullpen -maxdepth 2 \\( -path '/home/bullpen/.claude*' -o -path '/home/bullpen/.config' \\) -print -exec ls -ld {} \\; 2>/dev/null",
        )
        print(f"\nClaude auth exit code: {exit_code}", flush=True)
        return exit_code
    finally:
        if args.cleanup:
            await runtime.stop(config.sandbox_name)
            await runtime.remove(config.sandbox_name)


def main() -> int:
    try:
        return asyncio.run(main_async())
    except sb.DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
