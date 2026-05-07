#!/usr/bin/env python3
"""Deploy Bullpen into a Microsandbox microVM.

The script intentionally mirrors deploy-docker.sh where that behavior makes
sense, but uses the Microsandbox Python SDK as the runtime boundary.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib
import inspect
import os
import platform
import queue
import re
import select
import shlex
import shutil
import socket
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BULLPEN_GITHUB_REPO_URL_DEFAULT = "https://github.com/billroy/bullpen.git"
BULLPEN_PORT_DEFAULT = 8080
APP_PORT_DEFAULT = 3000
ADMIN_USER_DEFAULT = "admin"
SANDBOX_NAME_DEFAULT = "bullpen"
BASE_DEFAULT = "bullpen-microsandbox-local"
HEALTH_TIMEOUT_SECONDS = 20
SYSTEM_CA_CERT_FILE = "/etc/ssl/certs/ca-certificates.crt"
SYSTEM_CA_CERT_DIR = "/etc/ssl/certs"


class DeployError(RuntimeError):
    """User-facing deployment error."""


@dataclass
class DeployConfig:
    sandbox_name: str
    workspace: Path
    bullpen_port: int
    app_port: int
    admin_user: str
    admin_password: str
    base: str
    sandbox_home: Path
    replace: bool | None
    open_browser: bool
    install_bullpen_project: bool
    root: Path
    bullpen_source: Path
    github_repo_url: str
    local_project_path_default: Path
    action: str = "deploy"
    target: str | None = None
    runtime_env: dict[str, str] = field(default_factory=dict)


@dataclass
class CredentialSummary:
    selected_items: list[str] = field(default_factory=list)
    skipped_items: list[str] = field(default_factory=list)


SECRET_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "BULLPEN_BOOTSTRAP_PASSWORD",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GEMINI_API_KEY",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
}


class MicrosandboxRuntime:
    def __init__(self) -> None:
        try:
            self.module = importlib.import_module("microsandbox")
        except ImportError as exc:
            raise DeployError(
                "The microsandbox Python package is required. Install it with: "
                "python3 -m pip install microsandbox"
            ) from exc

        try:
            self.Sandbox = getattr(self.module, "Sandbox")
            self.Snapshot = getattr(self.module, "Snapshot")
            self.Volume = getattr(self.module, "Volume")
            self.Network = getattr(self.module, "Network")
            self.AttachOptions = getattr(self.module, "AttachOptions", None)
            self.ExecOptions = getattr(self.module, "ExecOptions", None)
            self.Stdin = getattr(self.module, "Stdin", None)
            self.StdoutEvent = getattr(self.module, "StdoutEvent", None)
            self.StderrEvent = getattr(self.module, "StderrEvent", None)
            self.ExitedEvent = getattr(self.module, "ExitedEvent", None)
        except AttributeError as exc:
            raise DeployError("The installed microsandbox package is missing the expected SDK API.") from exc

    async def ensure_installed(self) -> None:
        is_installed = getattr(self.module, "is_installed", None)
        install = getattr(self.module, "install", None)
        if not callable(is_installed):
            return

        installed = is_installed()
        if inspect.isawaitable(installed):
            installed = await installed
        if installed:
            return
        if not callable(install):
            raise DeployError("Microsandbox runtime is not installed and this SDK cannot install it.")
        result = install()
        if inspect.isawaitable(result):
            await result

    async def exists(self, name: str) -> bool:
        get = getattr(self.Sandbox, "get", None)
        if not callable(get):
            return False
        try:
            result = get(name)
            if inspect.isawaitable(result):
                await result
            return True
        except Exception:
            return False

    async def get(self, name: str) -> Any | None:
        get = getattr(self.Sandbox, "get", None)
        if not callable(get):
            return None
        try:
            result = get(name)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception:
            return None

    async def stop(self, name: str) -> None:
        sandbox = await self.get(name)
        if sandbox is None:
            return
        stop = getattr(sandbox, "stop", None)
        if not callable(stop):
            return
        result = stop()
        if inspect.isawaitable(result):
            await result

    async def remove(self, name: str) -> None:
        remove = getattr(self.Sandbox, "remove", None)
        if not callable(remove):
            return
        result = remove(name)
        if inspect.isawaitable(result):
            await result

    async def create(self, config: DeployConfig) -> Any:
        prepared_base = await self.prepared_base_snapshot_path(config.base)
        volumes = {
            "/app": self.Volume.bind(str(config.bullpen_source), readonly=True),
            "/workspace": self.Volume.bind(str(config.workspace)),
            "/home/bullpen": self.Volume.bind(str(config.sandbox_home)),
        }
        network = self.Network.allow_all()
        result = self.Sandbox.create(
            config.sandbox_name,
            snapshot=prepared_base,
            detached=True,
            replace=bool(config.replace),
            ports={
                config.bullpen_port: config.bullpen_port,
                config.app_port: config.app_port,
            },
            volumes=volumes,
            network=network,
            env=config.runtime_env,
        )
        if inspect.isawaitable(result):
            return await result
        return result

    async def status(self, name: str) -> str | None:
        get = getattr(self.Sandbox, "get", None)
        if not callable(get):
            return None
        result = get(name)
        if inspect.isawaitable(result):
            result = await result
        status = getattr(result, "status", None)
        if callable(status):
            status = status()
            if inspect.isawaitable(status):
                status = await status
        if status is None:
            return None
        return str(status)

    async def get_prepared_base(self, base: str) -> Any | None:
        get = getattr(self.Snapshot, "get", None)
        if callable(get):
            try:
                result = get(base)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception:
                pass
        return None

    async def prepared_base_exists(self, base: str) -> bool:
        return await self.get_prepared_base(base) is not None

    async def prepared_base_snapshot_path(self, base: str) -> str:
        snapshot = await self.get_prepared_base(base)
        if snapshot is None:
            raise DeployError(
                f"Prepared Microsandbox base '{base}' was not found. "
                "Run ./deploy/microsandbox/prepare.sh first."
            )
        path = getattr(snapshot, "path", None)
        if path is None:
            open_snapshot = getattr(snapshot, "open", None)
            if callable(open_snapshot):
                opened = open_snapshot()
                if inspect.isawaitable(opened):
                    opened = await opened
                path = getattr(opened, "path", None)
        if not path:
            raise DeployError(f"Prepared Microsandbox base '{base}' has no local snapshot path.")
        return str(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy Bullpen inside a Microsandbox microVM")
    parser.add_argument("--sandbox-name", default=SANDBOX_NAME_DEFAULT)
    parser.add_argument("--workspace")
    parser.add_argument("--bullpen-port", default=str(BULLPEN_PORT_DEFAULT))
    parser.add_argument("--app-port", default=str(APP_PORT_DEFAULT))
    parser.add_argument("--admin-user", default=ADMIN_USER_DEFAULT)
    parser.add_argument("--admin-password")
    parser.add_argument("--base", default=BASE_DEFAULT)
    parser.add_argument("--sandbox-home", default=str(Path.home() / ".bullpen" / "microsandbox-home"))
    parser.add_argument("--replace", action="store_true", default=False)
    parser.add_argument("--no-replace", action="store_true", default=False)
    parser.add_argument("--open", dest="open_browser", action="store_true", default=True)
    parser.add_argument("--no-open", dest="open_browser", action="store_false")
    parser.add_argument("--install-bullpen-project", action="store_true", default=False)
    subparsers = parser.add_subparsers(dest="command")
    auth_parser = subparsers.add_parser("auth", help="Run sandbox-native setup/auth for one item")
    auth_parser.add_argument("target", choices=("claude", "codex", "git"))
    test_parser = subparsers.add_parser("test-provider", help="Run sandbox-native verification for one item")
    test_parser.add_argument("target", choices=("claude", "codex", "git"))
    return parser


def parse_port(name: str, value: str) -> int:
    if not str(value).isdigit():
        raise DeployError(f"{name} must be numeric")
    port = int(value)
    if port < 1 or port > 65535:
        raise DeployError(f"{name} must be between 1 and 65535")
    return port


def prompt_password() -> str:
    while True:
        pw1 = getpass.getpass("Admin password: ")
        if not pw1:
            print("Password cannot be blank.", file=sys.stderr)
            continue
        pw2 = getpass.getpass("Confirm admin password: ")
        if pw1 == pw2:
            return pw1
        print("Passwords did not match; try again.", file=sys.stderr)


def abs_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def resolve_script_root() -> Path:
    return Path(__file__).resolve().parent


def is_bullpen_source(path: Path) -> bool:
    return (path / "bullpen.py").is_file() and (path / "server").is_dir()


def detect_supported_host() -> bool:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        return machine in {"arm64", "aarch64"}
    if system == "Linux":
        return Path("/dev/kvm").exists()
    return False


def require_command(command: str) -> None:
    if shutil.which(command) is None:
        raise DeployError(f"missing required command: {command}")


def host_port_in_use(port: int) -> bool:
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def host_port_owner(port: int) -> str:
    if shutil.which("lsof") is None:
        return ""
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) <= 1:
        return ""
    return "\n".join(lines[:6])


def ensure_host_ports_available(config: DeployConfig) -> None:
    occupied = [port for port in (config.bullpen_port, config.app_port) if host_port_in_use(port)]
    if not occupied:
        return
    details = []
    for port in occupied:
        owner = host_port_owner(port)
        if owner:
            details.append(f"Port {port} is already listening:\n{owner}")
        else:
            details.append(f"Port {port} is already listening.")
    raise DeployError(
        "Cannot start Microsandbox because required host port(s) are occupied.\n"
        + "\n\n".join(details)
    )


def wait_for_host_ports_available(config: DeployConfig, timeout_seconds: int = 10) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not any(host_port_in_use(port) for port in (config.bullpen_port, config.app_port)):
            return
        time.sleep(0.5)
    ensure_host_ports_available(config)


def install_bullpen_project_from_github(target_path: Path, repo_url: str) -> None:
    require_command("git")
    if (target_path / ".git").is_dir():
        print(f"Using existing Bullpen project checkout at {target_path}")
        return
    if target_path.exists():
        if target_path.is_dir() and not any(target_path.iterdir()):
            target_path.rmdir()
        else:
            raise DeployError(f"Bullpen project path already exists and is not a git checkout: {target_path}")
    print(f"Cloning Bullpen from {repo_url} into {target_path}")
    subprocess.run(["git", "clone", "--depth", "1", repo_url, str(target_path)], check=True)


def config_from_args(argv: list[str] | None = None) -> DeployConfig:
    root = resolve_script_root()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.replace and args.no_replace:
        raise DeployError("--replace and --no-replace cannot be used together")

    bullpen_port = parse_port("Bullpen web port", args.bullpen_port)
    app_port = parse_port("App port", args.app_port)
    if bullpen_port == app_port:
        raise DeployError("Bullpen web port and app port must be different")

    github_repo_url = os.environ.get("BULLPEN_GITHUB_REPO_URL", BULLPEN_GITHUB_REPO_URL_DEFAULT)
    local_project_path_default = root.parent / f"{root.name}-project"

    action = args.command or "deploy"
    target = getattr(args, "target", None)

    if args.install_bullpen_project:
        install_bullpen_project_from_github(local_project_path_default, github_repo_url)
        workspace = local_project_path_default.resolve()
    elif args.workspace:
        workspace = abs_path(args.workspace)
    else:
        cwd = Path.cwd().resolve()
        if action == "deploy" and cwd == root and is_bullpen_source(root):
            raise DeployError(
                "Refusing to mount the Bullpen source checkout as the project by default. "
                "Pass --workspace PATH, or use --install-bullpen-project."
            )
        workspace = cwd

    if action == "deploy":
        admin_password = args.admin_password or prompt_password()
    else:
        admin_password = args.admin_password or ""
    replace: bool | None
    if args.replace:
        replace = True
    elif args.no_replace:
        replace = False
    else:
        replace = None

    config = DeployConfig(
        sandbox_name=args.sandbox_name,
        workspace=workspace,
        bullpen_port=bullpen_port,
        app_port=app_port,
        admin_user=args.admin_user,
        admin_password=admin_password,
        base=args.base,
        sandbox_home=abs_path(args.sandbox_home),
        replace=replace,
        open_browser=args.open_browser,
        install_bullpen_project=args.install_bullpen_project,
        root=root,
        bullpen_source=root,
        github_repo_url=github_repo_url,
        local_project_path_default=local_project_path_default,
        action=action,
        target=target,
    )
    validate_config(config)
    return config


def validate_config(config: DeployConfig) -> None:
    if sys.version_info < (3, 10):
        raise DeployError("Python 3.10+ is required")
    if not detect_supported_host():
        raise DeployError("Microsandbox requires Apple Silicon macOS or Linux with KVM enabled")
    if not config.workspace.exists():
        raise DeployError(f"Workspace path does not exist: {config.workspace}")
    if not config.workspace.is_dir():
        raise DeployError(f"Workspace path is not a directory: {config.workspace}")
    if not is_bullpen_source(config.bullpen_source):
        raise DeployError(f"Bullpen source path does not contain bullpen.py: {config.bullpen_source}")
    if config.action != "deploy" and config.install_bullpen_project:
        raise DeployError("--install-bullpen-project is only supported for deploy")


def build_runtime_env(config: DeployConfig) -> None:
    config.runtime_env.update(
        {
            "HOME": "/home/bullpen",
            "USER": "bullpen",
            "LOGNAME": "bullpen",
            "BULLPEN_UID": str(os.getuid()),
            "BULLPEN_GID": str(os.getgid()),
            "BULLPEN_BOOTSTRAP_USER": config.admin_user,
            "BULLPEN_BOOTSTRAP_PASSWORD": config.admin_password,
            "BULLPEN_BOOTSTRAP_FORCE": "1",
            "BULLPEN_PORT": str(config.bullpen_port),
            "APP_PORT": str(config.app_port),
            "BULLPEN_HIDE_UNAVAILABLE_PROJECTS": "1",
            "BULLPEN_WORKSPACE": "/workspace",
            "BULLPEN_WORKSPACE_NAME": config.workspace.name,
            "BULLPEN_DEPLOY_LABEL": f"(Microsandbox:{config.sandbox_name})",
            "BULLPEN_PRODUCTION": os.environ.get("BULLPEN_PRODUCTION", "0"),
            "BULLPEN_VENV": "/opt/bullpen-venv",
            "BULLPEN_CODEX_SANDBOX": os.environ.get("BULLPEN_CODEX_SANDBOX", "none"),
            "BULLPEN_CODEX_PATH": "/home/bullpen/bin/codex",
        }
    )


def claude_tls_env_prefix() -> str:
    return "; ".join(
        [
            f"export SSL_CERT_FILE={shlex.quote(SYSTEM_CA_CERT_FILE)}",
            f"export SSL_CERT_DIR={shlex.quote(SYSTEM_CA_CERT_DIR)}",
            f"export NODE_EXTRA_CA_CERTS={shlex.quote(SYSTEM_CA_CERT_FILE)}",
            'export BUN_OPTIONS="${BUN_OPTIONS:+$BUN_OPTIONS }--use-system-ca"',
        ]
    )


async def run_sandbox_shell(sandbox: Any, command: str, *, check: bool = True) -> Any:
    exec_command = getattr(sandbox, "exec", None)
    if callable(exec_command):
        result = exec_command("bash", ["-lc", command])
    else:
        shell = getattr(sandbox, "shell", None)
        if not callable(shell):
            raise DeployError("Microsandbox sandbox object does not expose exec() or shell().")
        result = shell(command)
    if inspect.isawaitable(result):
        result = await result
    returncode = getattr(result, "returncode", None)
    if returncode is None:
        returncode = getattr(result, "exit_code", None)
    exit_status = getattr(result, "exit_status", None)
    if returncode is None and exit_status is not None:
        returncode = getattr(exit_status, "code", None)
    success = getattr(result, "success", None)
    failed = returncode not in (None, 0) or success is False
    if check and failed:
        stdout = getattr(result, "stdout_text", "") or getattr(result, "stdout", "")
        stderr = getattr(result, "stderr_text", "") or getattr(result, "stderr", "")
        details = "\n".join(part for part in (stdout, stderr) if part)
        raise DeployError(f"Sandbox command failed: {command}\n{details}")
    return result


def redact_text(text: str, config: DeployConfig | None = None) -> str:
    redacted = text
    if config is not None:
        for key in SECRET_ENV_NAMES:
            value = config.runtime_env.get(key)
            if value:
                redacted = redacted.replace(str(value), "[REDACTED]")
    return redacted


def sandbox_env_prefix(config: DeployConfig) -> str:
    exports = []
    for key, value in sorted(config.runtime_env.items()):
        exports.append(f"export {key}={shlex.quote(str(value))}")
    return "; ".join(exports)


async def run_configured_sandbox_shell(
    sandbox: Any,
    config: DeployConfig,
    command: str,
    *,
    check: bool = True,
    label: str | None = None,
) -> Any:
    try:
        return await run_sandbox_shell(sandbox, f"{sandbox_env_prefix(config)}; {command}", check=check)
    except DeployError as exc:
        message = redact_text(str(exc), config)
        if label and message.startswith("Sandbox command failed: "):
            _first, _sep, details = message.partition("\n")
            message = f"Sandbox command failed: {label}"
            if details:
                message = f"{message}\n{details}"
        raise DeployError(message) from exc


async def run_as_bullpen(sandbox: Any, config: DeployConfig, command: str, *, check: bool = True, label: str | None = None) -> Any:
    configured = f"{sandbox_env_prefix(config)}; {command}"
    wrapped = f"su -s /bin/bash bullpen -c {shlex.quote(configured)}"
    try:
        return await run_sandbox_shell(sandbox, wrapped, check=check)
    except DeployError as exc:
        message = redact_text(str(exc), config)
        if label and message.startswith("Sandbox command failed: "):
            _first, _sep, details = message.partition("\n")
            message = f"Sandbox command failed: {label}"
            if details:
                message = f"{message}\n{details}"
        raise DeployError(message) from exc


_URL_RE = re.compile(r"https?://\S+")


def _extract_urls(text: str) -> list[str]:
    return [match.group(0).rstrip(").,]") for match in _URL_RE.finditer(text or "")]


def _is_localhost_auth_callback(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
        and parsed.path == "/auth/callback"
        and bool(urllib.parse.parse_qs(parsed.query).get("code"))
    )


def _deliver_localhost_callback_to_sandbox(sandbox: Any, url: str) -> str:
    command = f"curl -fsS --max-time 10 {shlex.quote(url)} >/tmp/bullpen-provider-auth-callback.out"
    exec_command = getattr(sandbox, "exec", None)
    if callable(exec_command):
        result = exec_command("bash", ["-lc", command])
        if inspect.isawaitable(result):
            raise DeployError("Cannot bridge localhost callback because sandbox.exec() is asynchronous in this SDK path.")
    else:
        shell = getattr(sandbox, "shell", None)
        if not callable(shell):
            raise DeployError("Cannot bridge localhost callback because sandbox has no exec() or shell().")
        result = shell(command)
        if inspect.isawaitable(result):
            raise DeployError("Cannot bridge localhost callback because sandbox.shell() is asynchronous in this SDK path.")
    returncode = getattr(result, "returncode", None)
    if returncode is None:
        returncode = getattr(result, "exit_code", None)
    if returncode not in (None, 0):
        stderr = getattr(result, "stderr_text", "") or getattr(result, "stderr", "")
        raise DeployError(f"Sandbox localhost callback delivery failed: {stderr}".strip())
    return "Delivered localhost auth callback inside the sandbox."


async def attach_as_bullpen(
    runtime: MicrosandboxRuntime,
    sandbox: Any,
    config: DeployConfig,
    command: str,
    *,
    label: str | None = None,
    bridge_localhost_callback: bool = False,
    prefer_exec_stream: bool = False,
) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise DeployError("Interactive sandbox setup requires a TTY.")
    configured = f"{sandbox_env_prefix(config)}; {command}"
    status_path = f"/tmp/bullpen-attach-status-{uuid.uuid4().hex}"
    status_wrapped = (
        f"status_file={shlex.quote(status_path)}; "
        "rm -f \"$status_file\"; "
        f"bash -lc {shlex.quote(configured)}; "
        "status=$?; "
        "printf '%s\\n' \"$status\" > \"$status_file\"; "
        "exit \"$status\""
    )
    attach = getattr(sandbox, "attach", None)
    if not prefer_exec_stream and callable(attach) and runtime.AttachOptions is not None:
        options = runtime.AttachOptions(args=("-lc", status_wrapped), user="bullpen", env={})
        try:
            result = attach("bash", options)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            message = redact_text(str(exc), config)
            if label:
                message = f"Sandbox interactive command failed: {label}\n{message}"
            raise DeployError(message) from exc
        status_result = await run_sandbox_shell(
            sandbox,
            f"test -s {shlex.quote(status_path)} && cat {shlex.quote(status_path)}",
            check=False,
        )
        try:
            await run_sandbox_shell(sandbox, f"rm -f {shlex.quote(status_path)}", check=False)
        except DeployError:
            pass
        status_stdout = getattr(status_result, "stdout_text", "") or getattr(status_result, "stdout", "")
        status_text = status_stdout.strip()
        if not status_text:
            raise DeployError(
                f"Sandbox interactive command failed: {label or command}\n"
                "Interactive sandbox command exited without reporting a status."
            )
        try:
            exit_code = int(status_text.splitlines()[-1].strip())
        except ValueError as exc:
            raise DeployError(
                f"Sandbox interactive command failed: {label or command}\n"
                f"Unexpected interactive exit status output: {status_text!r}"
            ) from exc
        if exit_code != 0:
            raise DeployError(f"Sandbox interactive command failed: {label or command}")
        return

    exec_stream = getattr(sandbox, "exec_stream", None)
    if callable(exec_stream) and runtime.ExecOptions is not None and runtime.Stdin is not None:
        options = runtime.ExecOptions(
            args=("-lc", status_wrapped),
            user="bullpen",
            env={},
            tty=True,
            stdin=runtime.Stdin.pipe(),
        )
        handle = exec_stream("bash", options)
        if inspect.isawaitable(handle):
            handle = await handle
        stdin_sink = handle.take_stdin()
        stop_stdin = threading.Event()
        stdin_error: list[BaseException] = []
        callback_messages: queue.Queue[str] = queue.Queue()
        old_tty = termios.tcgetattr(sys.stdin.fileno())

        def pump_stdin() -> None:
            if stdin_sink is None:
                return
            fd = sys.stdin.fileno()
            while not stop_stdin.is_set():
                try:
                    ready, _w, _x = select.select([fd], [], [], 0.1)
                except OSError:
                    return
                if not ready:
                    continue
                try:
                    data = os.read(fd, 1024)
                except OSError as exc:
                    stdin_error.append(exc)
                    return
                if not data:
                    try:
                        stdin_sink.close()
                    except Exception:
                        pass
                    return
                if bridge_localhost_callback:
                    text = data.decode("utf-8", errors="ignore")
                    urls = [url for url in _extract_urls(text) if _is_localhost_auth_callback(url)]
                    if urls:
                        for url in urls:
                            try:
                                callback_messages.put(_deliver_localhost_callback_to_sandbox(sandbox, url))
                            except BaseException as exc:
                                stdin_error.append(exc)
                                return
                        continue
                try:
                    stdin_sink.write(data)
                except Exception as exc:
                    stdin_error.append(exc)
                    return

        seen_urls: set[str] = set()
        stdout_text_parts: list[str] = []
        stderr_text_parts: list[str] = []
        tty.setcbreak(sys.stdin.fileno())
        stdin_thread = threading.Thread(target=pump_stdin, daemon=True)
        stdin_thread.start()
        exit_code = 0
        try:
            while True:
                event = handle.recv()
                if inspect.isawaitable(event):
                    event = await event
                if event is None:
                    break
                while not callback_messages.empty():
                    print(callback_messages.get(), flush=True)
                if runtime.StdoutEvent is not None and isinstance(event, runtime.StdoutEvent):
                    text = event.data.decode("utf-8", errors="replace")
                    stdout_text_parts.append(text)
                    sys.stdout.write(text)
                    sys.stdout.flush()
                    for url in _extract_urls(text):
                        if url not in seen_urls:
                            seen_urls.add(url)
                            if config.open_browser:
                                open_browser(url)
                elif runtime.StderrEvent is not None and isinstance(event, runtime.StderrEvent):
                    text = event.data.decode("utf-8", errors="replace")
                    stderr_text_parts.append(text)
                    sys.stderr.write(text)
                    sys.stderr.flush()
                    for url in _extract_urls(text):
                        if url not in seen_urls:
                            seen_urls.add(url)
                            if config.open_browser:
                                open_browser(url)
                elif runtime.ExitedEvent is not None and isinstance(event, runtime.ExitedEvent):
                    exit_code = event.code
            while not callback_messages.empty():
                print(callback_messages.get(), flush=True)
            if stdin_error:
                raise stdin_error[0]
        except Exception as exc:
            message = redact_text(str(exc), config)
            if label:
                message = f"Sandbox interactive command failed: {label}\n{message}"
            raise DeployError(message) from exc
        finally:
            stop_stdin.set()
            try:
                if stdin_sink is not None:
                    stdin_sink.close()
            except Exception:
                pass
            stdin_thread.join(timeout=0.5)
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
        status_result = await run_sandbox_shell(
            sandbox,
            f"test -s {shlex.quote(status_path)} && cat {shlex.quote(status_path)}",
            check=False,
        )
        try:
            await run_sandbox_shell(sandbox, f"rm -f {shlex.quote(status_path)}", check=False)
        except DeployError:
            pass
        status_stdout = getattr(status_result, "stdout_text", "") or getattr(status_result, "stdout", "")
        status_text = status_stdout.strip()
        if status_text:
            try:
                exit_code = int(status_text.splitlines()[-1].strip())
            except ValueError as exc:
                raise DeployError(
                    f"Sandbox interactive command failed: {label or command}\n"
                    f"Unexpected interactive exit status output: {status_text!r}"
                ) from exc
        elif exit_code == 0:
            raise DeployError(
                f"Sandbox interactive command failed: {label or command}\n"
                "Interactive sandbox command exited without reporting a status."
            )
        if exit_code != 0:
            details = redact_text("".join(stdout_text_parts + stderr_text_parts), config)
            message = f"Sandbox interactive command failed: {label or command}"
            if details.strip():
                message = f"{message}\n{details}"
            raise DeployError(message)
        return

    raise DeployError("Microsandbox sandbox object does not expose interactive attach() or exec_stream().")


async def get_running_sandbox(runtime: MicrosandboxRuntime, config: DeployConfig) -> Any:
    sandbox = await runtime.get(config.sandbox_name)
    if sandbox is None:
        raise DeployError(
            f"Microsandbox '{config.sandbox_name}' is not running. Deploy Bullpen first:\n"
            "  python3 sandboxed-bullpen.py --replace"
        )
    return sandbox


async def ensure_bullpen_healthy(config: DeployConfig) -> None:
    try:
        wait_for_health(config.bullpen_port, timeout_seconds=5)
    except DeployError as exc:
        raise DeployError(
            f"Microsandbox '{config.sandbox_name}' is running, but Bullpen inside it is unhealthy.\n"
            f"{exc}"
        ) from exc


async def ensure_provider_command_ready(runtime: MicrosandboxRuntime, config: DeployConfig) -> Any:
    sandbox = await get_running_sandbox(runtime, config)
    try:
        await ensure_bullpen_healthy(config)
    except DeployError as exc:
        message = str(exc)
        if "Bullpen inside it is unhealthy" not in message:
            message = (
                f"Microsandbox '{config.sandbox_name}' is running, but Bullpen inside it is unhealthy.\n"
                f"{message}"
            )
        print(f"warn: {message}\nContinuing because provider auth/test commands do not require Bullpen HTTP.", file=sys.stderr)
    return sandbox


def prompt_yes_no(prompt: str, *, default: bool = True) -> bool:
    if not sys.stdin.isatty():
        raise DeployError("Install-time setup requires an interactive terminal.")
    suffix = "[Y/n]" if default else "[y/N]"
    reply = input(f"{prompt} {suffix}: ").strip().lower()
    if not reply:
        return default
    return reply in {"y", "yes"}


def prompt_text(prompt: str, default: str | None = None) -> str:
    if not sys.stdin.isatty():
        raise DeployError("Interactive setup requires a terminal.")
    suffix = f" [{default}]" if default else ""
    reply = input(f"{prompt}{suffix}: ").strip()
    if reply:
        return reply
    if default is not None:
        return default
    raise DeployError(f"{prompt} is required.")


def resolve_git_identity() -> tuple[str, str]:
    name = (
        os.environ.get("GIT_AUTHOR_NAME")
        or os.environ.get("GIT_COMMITTER_NAME")
        or os.environ.get("GIT_USER_NAME")
    )
    email = (
        os.environ.get("GIT_AUTHOR_EMAIL")
        or os.environ.get("GIT_COMMITTER_EMAIL")
        or os.environ.get("GIT_USER_EMAIL")
    )
    name = prompt_text("Git user.name for sandbox", name or None)
    email = prompt_text("Git user.email for sandbox", email or None)
    return name, email


def log_step(message: str) -> None:
    print(f"==> {message}", flush=True)


async def prepare_runtime_dirs(sandbox: Any, config: DeployConfig) -> None:
    command = r'''set -e
uid="${BULLPEN_UID:-1000}"
gid="${BULLPEN_GID:-1000}"
if ! getent group bullpen >/dev/null 2>&1; then
  if getent group "$gid" >/dev/null 2>&1; then
    group_name="$(getent group "$gid" | cut -d: -f1)"
  else
    groupadd --gid "$gid" bullpen
    group_name="bullpen"
  fi
else
  group_name="bullpen"
fi
if ! id bullpen >/dev/null 2>&1; then
  useradd --uid "$uid" --gid "$group_name" --home-dir /home/bullpen --shell /bin/bash bullpen
fi
actual_uid="$(id -u bullpen)"
if [ "$actual_uid" != "$uid" ]; then
  echo "Existing bullpen user has uid $actual_uid, expected $uid." >&2
  exit 1
fi
mkdir -p /home/bullpen/logs /home/bullpen/bin /home/bullpen/.codex /var/lib/bullpen
chown bullpen:"$group_name" /home/bullpen/logs /home/bullpen/bin /home/bullpen/.codex
chown -R bullpen:"$group_name" /var/lib/bullpen
chmod 700 /var/lib/bullpen 2>/dev/null || true
# Lift FD ceiling for bullpen via pam_limits. Default soft 1024 / hard 4096
# is too tight when many claude/codex/gemini subprocesses each churn FDs
# through TLS handshakes, MCP wires, and per-run tmp dirs; pressure surfaces
# as misclassified TLS or DNS errors that look like API retry storms.
mkdir -p /etc/security/limits.d
cat > /etc/security/limits.d/bullpen-fd.conf <<'LIMITS_EOF'
bullpen soft nofile 65536
bullpen hard nofile 65536
LIMITS_EOF
chmod 644 /etc/security/limits.d/bullpen-fd.conf
su -s /bin/bash bullpen -c 'test -w /home/bullpen && test -w /home/bullpen/logs && test -w /home/bullpen/bin && test -w /home/bullpen/.codex'
hard_nofile="$(su -s /bin/bash bullpen -c 'ulimit -Hn')"
if [ "$hard_nofile" -lt 65536 ]; then
  echo "warn: bullpen RLIMIT_NOFILE hard limit is $hard_nofile, expected 65536; pam_limits may not be enforcing limits.d" >&2
fi
'''
    await run_configured_sandbox_shell(sandbox, config, command, label="prepare Microsandbox runtime user")
    await run_sandbox_shell(sandbox, "test -x /opt/bullpen-venv/bin/python")


async def verify_mount_access(sandbox: Any, config: DeployConfig) -> None:
    repair_command = r'''set -e
uid="${BULLPEN_UID:-1000}"
gid="${BULLPEN_GID:-1000}"
mkdir -p /workspace/.bullpen
chown "$uid:$gid" /workspace/.bullpen
if [ -d /workspace/.bullpen ]; then
  chown -R "$uid:$gid" /workspace/.bullpen
fi
'''
    await run_configured_sandbox_shell(sandbox, config, repair_command, label="repair Bullpen workspace state ownership")
    command = r'''set -e
test -w /workspace
test -w /workspace/.bullpen
test -w /home/bullpen
'''
    await run_as_bullpen(sandbox, config, command, label="verify Microsandbox mount access")


async def install_codex_wrapper(sandbox: Any, config: DeployConfig) -> None:
    command = r'''set -e
mkdir -p /home/bullpen/bin /home/bullpen/.codex /var/lib/bullpen
chmod 700 /var/lib/bullpen 2>/dev/null || true
real_codex="$(command -v codex)"
if [ -z "$real_codex" ] || [ "$real_codex" = "/home/bullpen/bin/codex" ]; then
  echo "Unable to locate real Codex CLI" >&2
  exit 1
fi
cat > /home/bullpen/bin/codex <<EOF
#!/usr/bin/env bash
set -u

REAL_CODEX="$real_codex"
PERSISTENT_CODEX_HOME="\${BULLPEN_PERSISTENT_CODEX_HOME:-/home/bullpen/.codex}"
RUNTIME_CODEX_HOME="\${BULLPEN_CODEX_RUNTIME_HOME:-/var/lib/bullpen/codex-home}"
LOCK_DIR="\${BULLPEN_CODEX_LOCK_DIR:-/var/lib/bullpen/codex.lock}"

while ! mkdir "\$LOCK_DIR" 2>/dev/null; do
  if [ -f "\$LOCK_DIR/pid" ]; then
    old_pid="\$(cat "\$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "\$old_pid" ] && ! kill -0 "\$old_pid" 2>/dev/null; then
      rm -rf "\$LOCK_DIR"
      continue
    fi
  fi
  sleep 0.2
done
echo "\$\$" > "\$LOCK_DIR/pid"
cleanup() {
  rm -rf "\$LOCK_DIR"
}
trap cleanup EXIT INT TERM

mkdir -p "\$PERSISTENT_CODEX_HOME"
rm -rf "\$RUNTIME_CODEX_HOME"
mkdir -p "\$RUNTIME_CODEX_HOME"
if [ -d "\$PERSISTENT_CODEX_HOME" ]; then
  cp -a "\$PERSISTENT_CODEX_HOME"/. "\$RUNTIME_CODEX_HOME"/ 2>/dev/null || true
fi

export CODEX_HOME="\$RUNTIME_CODEX_HOME"
"\$REAL_CODEX" "\$@"
status="\$?"

mkdir -p "\$PERSISTENT_CODEX_HOME"
cp -a "\$RUNTIME_CODEX_HOME"/. "\$PERSISTENT_CODEX_HOME"/ 2>/dev/null || true

exit "\$status"
EOF
chmod 755 /home/bullpen/bin/codex
chown -R bullpen:"$(id -gn bullpen)" /var/lib/bullpen
test -x /home/bullpen/bin/codex
su -s /bin/bash bullpen -c 'test -x /home/bullpen/bin/codex && test -w /home/bullpen/.codex'
'''
    await run_configured_sandbox_shell(sandbox, config, command, label="install Codex wrapper")


async def bootstrap_bullpen_credentials(sandbox: Any, config: DeployConfig) -> None:
    command = (
        "set -e; "
        "cd /app; "
        "/opt/bullpen-venv/bin/python bullpen.py --bootstrap-credentials"
    )
    await run_as_bullpen(sandbox, config, command, label="bootstrap Bullpen credentials")


async def start_bullpen(sandbox: Any, config: DeployConfig) -> None:
    command = (
        "set -e; "
        "mkdir -p /home/bullpen/logs; "
        ": > /home/bullpen/logs/bullpen.log; "
        "test -x /opt/bullpen-venv/bin/python; "
        "cd /app; "
        "echo '[sandboxed-bullpen] starting Bullpen with /opt/bullpen-venv/bin/python' >> /home/bullpen/logs/bullpen.log; "
        "nohup /opt/bullpen-venv/bin/python bullpen.py "
        "--workspace /workspace "
        "--host 0.0.0.0 "
        '--port "$BULLPEN_PORT" '
        "--no-browser "
        ">/home/bullpen/logs/bullpen.log 2>&1 &"
    )
    await run_as_bullpen(sandbox, config, command, label="start Bullpen")


def wait_for_health(port: int, timeout_seconds: int = HEALTH_TIMEOUT_SECONDS) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise DeployError(f"Bullpen health check failed for {url}: {last_error}")


async def verify_admin_credentials(sandbox: Any, config: DeployConfig) -> None:
    command = r'''set -e; cd /app && /opt/bullpen-venv/bin/python - <<'PY'
import os
import sys
from server import auth
from server.workspace_manager import GLOBAL_DIR

username = os.environ.get("BULLPEN_BOOTSTRAP_USER", "")
password = os.environ.get("BULLPEN_BOOTSTRAP_PASSWORD", "")
auth.load_credentials(GLOBAL_DIR)
ok = bool(username) and auth.check_password(password, auth.get_password_hash(username))
if not ok:
    print(f"Credential verification failed for user {username!r}.", file=sys.stderr)
    sys.exit(1)
print(f"Credential verification passed for user {username!r}.")
PY'''
    await run_as_bullpen(sandbox, config, command, label="verify Bullpen credentials")


async def disable_guest_ipv6_for_claude(sandbox: Any) -> None:
    command = r'''set -e
if command -v sysctl >/dev/null 2>&1; then
  for key in net.ipv6.conf.all.disable_ipv6 net.ipv6.conf.default.disable_ipv6 net.ipv6.conf.eth0.disable_ipv6; do
    sysctl -w "$key=1" >/dev/null
  done
else
  for name in all default eth0; do
    path="/proc/sys/net/ipv6/conf/${name}/disable_ipv6"
    [ -e "$path" ] || continue
    printf '1' > "$path"
  done
fi
for name in all default eth0; do
  path="/proc/sys/net/ipv6/conf/${name}/disable_ipv6"
  [ -e "$path" ] || continue
  value="$(cat "$path")"
  if [ "$value" != 1 ]; then
    echo "Failed to disable guest IPv6 for Claude: $path is $value" >&2
    exit 1
  fi
done
echo "Disabled guest IPv6 for Claude auth due Microsandbox IPv6 TLS EOFs." >&2
'''
    await run_sandbox_shell(sandbox, command)
    print("Claude auth network mitigation applied: guest IPv6 disabled for this sandbox.", flush=True)


async def verify_claude_auth(sandbox: Any, config: DeployConfig) -> None:
    await disable_guest_ipv6_for_claude(sandbox)
    command = (
        "set -e\n"
        f"{claude_tls_env_prefix()}\n"
        "cd /workspace\n"
        "out=\"$(\n"
        "  timeout 60s bash -lc 'printf \"Reply OK only.\" | claude --print --output-format stream-json --verbose --no-session-persistence --setting-sources user --model claude-sonnet-4-6' 2>&1\n"
        ")\" || {\n"
        "  printf '%s\\n' \"$out\" | tail -40 >&2\n"
        "  echo \"Claude auth preflight failed inside Microsandbox. Re-run sandbox setup and complete Claude login there.\" >&2\n"
        "  exit 1\n"
        "}\n"
    )
    await run_as_bullpen(sandbox, config, command, label="verify Claude auth")


async def verify_codex_auth(sandbox: Any, config: DeployConfig) -> None:
    command = r'''set -e
cd /workspace
for _attempt in 1 2; do
  echo "Codex auth preflight attempt ${_attempt}/2" >&2
  timeout 45s bash -lc 'printf "Reply OK only." | HOME=/home/bullpen BULLPEN_CODEX_SANDBOX=none "$BULLPEN_CODEX_PATH" exec --dangerously-bypass-approvals-and-sandbox --json --skip-git-repo-check -'
done
'''
    await run_as_bullpen(sandbox, config, command, label="verify Codex auth")


async def verify_git_auth(sandbox: Any, config: DeployConfig) -> None:
    command = r'''set -e
git config --global --get user.name >/dev/null
git config --global --get user.email >/dev/null
gh auth status --hostname github.com >/dev/null
cd /workspace
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git remote get-url origin >/dev/null 2>&1; then
    remote_url="$(git remote get-url origin)"
    case "$remote_url" in
      *github.com*)
        git ls-remote origin HEAD >/dev/null
        ;;
      *)
        echo "warn: origin is not a GitHub remote; skipping remote auth verification" >&2
        ;;
    esac
  else
    echo "warn: git remote 'origin' not found; skipping remote auth verification" >&2
  fi
else
  echo "warn: /workspace is not a git repository; skipping remote auth verification" >&2
fi
'''
    await run_as_bullpen(sandbox, config, command, label="verify Git auth")


async def auth_claude(runtime: MicrosandboxRuntime, sandbox: Any, config: DeployConfig) -> None:
    print("Claude setup runs inside the sandbox. If localhost callback delivery fails, complete the terminal fallback.", flush=True)
    await disable_guest_ipv6_for_claude(sandbox)
    await attach_as_bullpen(
        runtime,
        sandbox,
        config,
        f"{claude_tls_env_prefix()}; claude auth login",
        label="authenticate Claude",
    )


async def auth_codex(runtime: MicrosandboxRuntime, sandbox: Any, config: DeployConfig) -> None:
    print(
        "Codex setup runs inside the sandbox using browser auth. If the browser lands on a localhost callback URL, paste that full URL here.",
        flush=True,
    )
    await attach_as_bullpen(
        runtime,
        sandbox,
        config,
        "codex login",
        label="authenticate Codex",
        bridge_localhost_callback=True,
        prefer_exec_stream=True,
    )


async def auth_git(runtime: MicrosandboxRuntime, sandbox: Any, config: DeployConfig) -> None:
    name, email = resolve_git_identity()
    setup_command = (
        f"git config --global user.name {shlex.quote(name)}; "
        f"git config --global user.email {shlex.quote(email)}; "
        "gh auth login --hostname github.com --git-protocol https --web; "
        "gh auth setup-git --hostname github.com"
    )
    print("Git setup runs inside the sandbox using GitHub CLI over HTTPS.", flush=True)
    await attach_as_bullpen(runtime, sandbox, config, setup_command, label="authenticate GitHub CLI")


@dataclass(frozen=True)
class SetupItem:
    key: str
    label: str
    auth_func: Any
    verify_func: Any


def setup_items() -> list[SetupItem]:
    return [
        SetupItem("claude", "Claude", auth_claude, verify_claude_auth),
        SetupItem("codex", "Codex", auth_codex, verify_codex_auth),
        SetupItem("git", "Git", auth_git, verify_git_auth),
    ]


def get_setup_item(key: str) -> SetupItem:
    for item in setup_items():
        if item.key == key:
            return item
    raise DeployError(f"Unknown setup target: {key}")


async def run_install_tui(runtime: MicrosandboxRuntime, sandbox: Any, config: DeployConfig) -> CredentialSummary:
    summary = CredentialSummary()
    if not sys.stdin.isatty():
        raise DeployError("Microsandbox install setup requires an interactive terminal.")
    for item in setup_items():
        should_setup = prompt_yes_no(f"Set up {item.label} in this sandbox?", default=True)
        if not should_setup:
            summary.skipped_items.append(item.key)
            continue
        summary.selected_items.append(item.key)
        log_step(f"Setting up {item.label}")
        await item.auth_func(runtime, sandbox, config)
        log_step(f"Verifying {item.label}")
        await item.verify_func(sandbox, config)
    return summary


async def detach_sandbox(sandbox: Any) -> None:
    detach = getattr(sandbox, "detach", None)
    if not callable(detach):
        raise DeployError("Installed Microsandbox SDK does not expose sandbox.detach().")
    result = detach()
    if inspect.isawaitable(result):
        await result


async def verify_detached_sandbox(runtime: MicrosandboxRuntime, config: DeployConfig) -> None:
    status = await runtime.status(config.sandbox_name)
    if status is not None and "running" not in status.lower():
        raise DeployError(f"Microsandbox '{config.sandbox_name}' is not running after detach (status: {status}).")
    wait_for_health(config.bullpen_port)


async def print_bullpen_log(sandbox: Any) -> None:
    try:
        result = await run_sandbox_shell(sandbox, "cat /home/bullpen/logs/bullpen.log", check=False)
    except Exception:
        return
    text = getattr(result, "stdout_text", "") or getattr(result, "stdout", "")
    if text:
        print(text, file=sys.stderr)


def open_browser(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    elif os.name == "nt":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", url], check=False)


async def run_auth_command(config: DeployConfig) -> None:
    if not config.target:
        raise DeployError("auth requires a target")
    runtime = MicrosandboxRuntime()
    await runtime.ensure_installed()
    sandbox = await ensure_provider_command_ready(runtime, config)
    build_runtime_env(config)
    if config.target == "codex":
        await install_codex_wrapper(sandbox, config)
    item = get_setup_item(config.target)
    await item.auth_func(runtime, sandbox, config)


async def run_test_provider_command(config: DeployConfig) -> None:
    if not config.target:
        raise DeployError("test-provider requires a target")
    runtime = MicrosandboxRuntime()
    await runtime.ensure_installed()
    sandbox = await ensure_provider_command_ready(runtime, config)
    build_runtime_env(config)
    if config.target == "codex":
        await install_codex_wrapper(sandbox, config)
    item = get_setup_item(config.target)
    await item.verify_func(sandbox, config)


async def choose_replace(runtime: MicrosandboxRuntime, config: DeployConfig) -> bool:
    exists = await runtime.exists(config.sandbox_name)
    if not exists:
        return True
    if config.replace is True:
        return True
    if config.replace is False:
        raise DeployError(f"Sandbox '{config.sandbox_name}' already exists.")
    if not sys.stdin.isatty():
        raise DeployError(f"Sandbox '{config.sandbox_name}' already exists. Pass --replace or --no-replace.")
    reply = input(f"Sandbox '{config.sandbox_name}' already exists. Replace it? [Y/n]: ").strip()
    if reply and reply.lower() not in {"y", "yes"}:
        print("Deployment unchanged.")
        return False
    return True


async def replace_existing_sandbox(runtime: MicrosandboxRuntime, config: DeployConfig) -> None:
    if not await runtime.exists(config.sandbox_name):
        return
    log_step(f"Replacing existing Microsandbox {config.sandbox_name}")
    await runtime.stop(config.sandbox_name)
    try:
        await runtime.remove(config.sandbox_name)
    except Exception:
        time.sleep(1)
        await runtime.remove(config.sandbox_name)
    wait_for_host_ports_available(config)


async def deploy(config: DeployConfig) -> CredentialSummary | None:
    runtime = MicrosandboxRuntime()
    await runtime.ensure_installed()
    should_deploy = await choose_replace(runtime, config)
    if not should_deploy:
        return None
    await replace_existing_sandbox(runtime, config)
    ensure_host_ports_available(config)

    build_runtime_env(config)
    config.replace = True

    log_step("Creating Microsandbox")
    sandbox = await runtime.create(config)
    try:
        log_step("Preparing Microsandbox runtime")
        await prepare_runtime_dirs(sandbox, config)
        log_step("Verifying Microsandbox mount access")
        await verify_mount_access(sandbox, config)
        log_step("Installing Codex wrapper")
        await install_codex_wrapper(sandbox, config)
        log_step("Bootstrapping Bullpen credentials")
        await bootstrap_bullpen_credentials(sandbox, config)
        log_step("Starting Bullpen")
        await start_bullpen(sandbox, config)
        log_step("Waiting for Bullpen health")
        wait_for_health(config.bullpen_port)
        log_step("Verifying Bullpen credentials")
        await verify_admin_credentials(sandbox, config)
        log_step("Running install setup")
        summary = await run_install_tui(runtime, sandbox, config)
        log_step("Detaching Microsandbox")
        await detach_sandbox(sandbox)
        log_step("Verifying detached Bullpen health")
        await verify_detached_sandbox(runtime, config)
    except Exception:
        await print_bullpen_log(sandbox)
        raise
    return summary


def print_success(config: DeployConfig, summary: CredentialSummary) -> None:
    ui_url = f"http://localhost:{config.bullpen_port}"
    print()
    print("Bullpen is up.")
    print(f"UI:   {ui_url}")
    print(f"App:  http://localhost:{config.app_port}")
    print(f"User: {config.admin_user}")
    print(f"Sandbox: {config.sandbox_name}")
    print(f"Sandbox home: {config.sandbox_home}")
    if summary.selected_items:
        print(f"Configured during install: {', '.join(summary.selected_items)}")
    if summary.skipped_items:
        print(f"Skipped during install: {', '.join(summary.skipped_items)}")
    if config.open_browser:
        open_browser(ui_url)


async def async_main(argv: list[str] | None = None) -> int:
    try:
        config = config_from_args(argv)
        if config.action == "deploy":
            summary = await deploy(config)
            if summary is not None:
                print_success(config, summary)
        elif config.action == "auth":
            await run_auth_command(config)
        elif config.action == "test-provider":
            await run_test_provider_command(config)
        else:
            raise DeployError(f"Unknown action: {config.action}")
        return 0
    except DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed: {' '.join(exc.cmd)}", file=sys.stderr)
        return exc.returncode or 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    sys.exit(main())
