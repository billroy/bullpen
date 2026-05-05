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
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
    runtime_env: dict[str, str] = field(default_factory=dict)
    codex_auth_synced: bool = False


@dataclass
class CredentialSummary:
    provider_sources: list[str] = field(default_factory=list)
    git_sources: list[str] = field(default_factory=list)


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

    if args.install_bullpen_project:
        install_bullpen_project_from_github(local_project_path_default, github_repo_url)
        workspace = local_project_path_default.resolve()
    elif args.workspace:
        workspace = abs_path(args.workspace)
    else:
        cwd = Path.cwd().resolve()
        if cwd == root and is_bullpen_source(root):
            raise DeployError(
                "Refusing to mount the Bullpen source checkout as the project by default. "
                "Pass --workspace PATH, or use --install-bullpen-project."
            )
        workspace = cwd

    admin_password = args.admin_password or prompt_password()
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


def chmod_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(stat.S_IRWXU)
    except OSError:
        pass


def copy_file_if_exists(source: Path, target: Path, *, sync: bool = False) -> bool:
    if not source.is_file():
        return False
    if target.exists() and not sync:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def copy_dir_if_exists(source: Path, target: Path, *, sync: bool = False) -> bool:
    if not source.is_dir():
        return False
    if target.exists() and not sync:
        return True
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return True


def yaml_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def host_github_gh(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "XDG_CONFIG_HOME"):
        env.pop(key, None)
    return subprocess.run(["gh", *args], env=env, capture_output=True, text=True, check=False)


def sandbox_home_gh(*args: str, sandbox_home: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(sandbox_home)
    env.pop("GH_CONFIG_DIR", None)
    env.pop("XDG_CONFIG_HOME", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["gh", *args], env=env, capture_output=True, text=True, check=False)


def github_hosts_has_oauth_token(sandbox_home: Path) -> bool:
    hosts = sandbox_home / ".config" / "gh" / "hosts.yml"
    if not hosts.is_file():
        return False
    return "oauth_token:" in hosts.read_text(encoding="utf-8", errors="ignore")


def github_cli_logged_in(sandbox_home: Path) -> bool:
    if shutil.which("gh") is None:
        return False
    result = sandbox_home_gh("auth", "status", "--hostname", "github.com", sandbox_home=sandbox_home)
    return result.returncode == 0


def github_token_env_valid(sandbox_home: Path) -> bool:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token or shutil.which("gh") is None:
        return False
    result = sandbox_home_gh(
        "auth",
        "status",
        "--hostname",
        "github.com",
        sandbox_home=sandbox_home,
        extra_env={"GH_TOKEN": token},
    )
    return result.returncode == 0


def copy_host_github_cli_auth_to_sandbox_home(sandbox_home: Path) -> bool:
    if shutil.which("gh") is None:
        return False
    token_result = host_github_gh("auth", "token", "--hostname", "github.com")
    token = token_result.stdout.strip()
    if token_result.returncode != 0 or not token:
        return False
    user_result = subprocess.run(
        ["gh", "api", "--hostname", "github.com", "user", "--jq", ".login"],
        env={**os.environ, "GH_TOKEN": token},
        capture_output=True,
        text=True,
        check=False,
    )
    user = user_result.stdout.strip() if user_result.returncode == 0 else ""
    gh_dir = sandbox_home / ".config" / "gh"
    gh_dir.mkdir(parents=True, exist_ok=True)
    hosts = gh_dir / "hosts.yml"
    lines = [
        "github.com:",
        "    git_protocol: https",
        f"    oauth_token: {yaml_single_quote(token)}",
    ]
    if user:
        lines.append(f"    user: {yaml_single_quote(user)}")
    hosts.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        hosts.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return github_cli_logged_in(sandbox_home)


def seed_credentials(config: DeployConfig) -> CredentialSummary:
    home = Path.home()
    sandbox_home = config.sandbox_home
    chmod_private_dir(sandbox_home)
    (sandbox_home / "logs").mkdir(parents=True, exist_ok=True)

    summary = CredentialSummary()
    copy_file_if_exists(home / ".claude.json", sandbox_home / ".claude.json")
    copy_dir_if_exists(home / ".claude", sandbox_home / ".claude")
    copy_file_if_exists(home / ".claude" / ".credentials.json", sandbox_home / ".claude" / ".credentials.json", sync=True)
    copy_dir_if_exists(home / ".config" / "codex", sandbox_home / ".config" / "codex")
    copy_dir_if_exists(home / ".codex", sandbox_home / ".codex")
    config.codex_auth_synced = copy_file_if_exists(home / ".codex" / "auth.json", sandbox_home / ".codex" / "auth.json", sync=True)
    copy_dir_if_exists(home / ".config" / "gemini", sandbox_home / ".config" / "gemini")
    copy_dir_if_exists(home / ".config" / "google-gemini", sandbox_home / ".config" / "google-gemini")

    provider_home_paths = [
        sandbox_home / ".claude",
        sandbox_home / ".claude.json",
        sandbox_home / ".claude" / ".credentials.json",
        sandbox_home / ".codex",
        sandbox_home / ".codex" / "auth.json",
        sandbox_home / ".config" / "codex",
        sandbox_home / ".config" / "gemini",
        sandbox_home / ".config" / "google-gemini",
    ]
    for path in provider_home_paths:
        if path.exists():
            summary.provider_sources.append(f"home:{path}")

    claude_oauth_present = (sandbox_home / ".claude" / ".credentials.json").is_file()
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        if os.environ.get(name):
            config.runtime_env[name] = os.environ[name]
            summary.provider_sources.append(f"env:{name}")
    if os.environ.get("ANTHROPIC_API_KEY"):
        if claude_oauth_present:
            print(
                f"warn: ANTHROPIC_API_KEY is set but OAuth credentials exist in {sandbox_home}/.claude/.credentials.json; skipping it.",
                file=sys.stderr,
            )
        else:
            config.runtime_env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
            summary.provider_sources.append("env:ANTHROPIC_API_KEY")

    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        if os.environ.get(name):
            config.runtime_env[name] = os.environ[name]
            summary.git_sources.append(f"env:{name}")

    copy_file_if_exists(home / ".gitconfig", sandbox_home / ".gitconfig.host")
    copy_dir_if_exists(home / ".config" / "gh", sandbox_home / ".config" / "gh", sync=True)
    if (sandbox_home / ".gitconfig.host").is_file():
        summary.git_sources.append(f"home:{sandbox_home}/.gitconfig.host")
    if (sandbox_home / ".config" / "gh").is_dir():
        summary.git_sources.append(f"home:{sandbox_home}/.config/gh")

    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        if not github_token_env_valid(sandbox_home):
            print("warn: GH_TOKEN/GITHUB_TOKEN is set, but GitHub CLI could not validate it.", file=sys.stderr)
    elif github_hosts_has_oauth_token(sandbox_home) and github_cli_logged_in(sandbox_home):
        pass
    elif copy_host_github_cli_auth_to_sandbox_home(sandbox_home):
        print("Copied host GitHub CLI token into Microsandbox home")
        summary.git_sources.append(f"home:{sandbox_home}/.config/gh")
    elif shutil.which("gh") is None:
        print("warn: Install GitHub CLI on the host or set GH_TOKEN/GITHUB_TOKEN before git push or auto-PR.", file=sys.stderr)
    else:
        print("warn: No valid GitHub CLI auth found; git push and auto-PR may fail.", file=sys.stderr)

    if not summary.provider_sources:
        prompt_optional_provider_credentials(config, summary)
    if not summary.provider_sources:
        raise DeployError("No provider credentials were supplied.")

    return summary


def prompt_optional_provider_credentials(config: DeployConfig, summary: CredentialSummary) -> None:
    if not sys.stdin.isatty():
        return
    print("No provider credentials were auto-detected. Enter any credentials you have; at least one is required.")
    for name, label in (
        ("CLAUDE_CODE_OAUTH_TOKEN", "Claude Code OAuth token"),
        ("ANTHROPIC_API_KEY", "Anthropic API key"),
        ("OPENAI_API_KEY", "OpenAI API key"),
        ("GEMINI_API_KEY", "Gemini API key"),
        ("GOOGLE_API_KEY", "Google API key"),
    ):
        value = getpass.getpass(f"{label} (optional, press Enter to skip): ")
        if value:
            config.runtime_env[name] = value
            summary.provider_sources.append(f"env:{name}")


def build_runtime_env(config: DeployConfig) -> None:
    config.runtime_env.update(
        {
            "HOME": "/home/bullpen",
            "BULLPEN_BOOTSTRAP_USER": config.admin_user,
            "BULLPEN_BOOTSTRAP_PASSWORD": config.admin_password,
            "BULLPEN_BOOTSTRAP_FORCE": "1",
            "BULLPEN_PORT": str(config.bullpen_port),
            "APP_PORT": str(config.app_port),
            "BULLPEN_HIDE_UNAVAILABLE_PROJECTS": "1",
            "BULLPEN_WORKSPACE": "/workspace",
            "BULLPEN_WORKSPACE_NAME": config.workspace.name,
            "BULLPEN_PRODUCTION": os.environ.get("BULLPEN_PRODUCTION", "0"),
            "BULLPEN_VENV": "/opt/bullpen-venv",
            "BULLPEN_CODEX_SANDBOX": os.environ.get("BULLPEN_CODEX_SANDBOX", "none"),
            "BULLPEN_CODEX_PATH": "/home/bullpen/bin/codex",
        }
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


def log_step(message: str) -> None:
    print(f"==> {message}", flush=True)


async def prepare_runtime_dirs(sandbox: Any) -> None:
    await run_sandbox_shell(sandbox, "mkdir -p /home/bullpen/logs")
    await run_sandbox_shell(sandbox, ": > /home/bullpen/logs/bullpen.log")
    await run_sandbox_shell(sandbox, "test -x /opt/bullpen-venv/bin/python")


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
test -x /home/bullpen/bin/codex
'''
    await run_configured_sandbox_shell(sandbox, config, command, label="install Codex wrapper")


async def bootstrap_bullpen_credentials(sandbox: Any, config: DeployConfig) -> None:
    command = (
        "set -e; "
        "cd /app; "
        "/opt/bullpen-venv/bin/python bullpen.py --bootstrap-credentials"
    )
    await run_configured_sandbox_shell(sandbox, config, command, label="bootstrap Bullpen credentials")


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
    await run_configured_sandbox_shell(sandbox, config, command, label="start Bullpen")


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
    await run_configured_sandbox_shell(sandbox, config, command, label="verify Bullpen credentials")


async def verify_codex_auth(sandbox: Any, config: DeployConfig) -> None:
    if not config.codex_auth_synced:
        return
    command = (
        "set -e; "
        "test -f /home/bullpen/.codex/auth.json; "
        "test -w /home/bullpen/.codex/auth.json; "
        "for _attempt in 1 2; do "
        "echo \"Codex auth preflight attempt ${_attempt}/2\" >&2; "
        "timeout 45s bash -lc 'printf \"Reply OK only.\" | "
        "HOME=/home/bullpen BULLPEN_CODEX_SANDBOX=none "
        "\"$BULLPEN_CODEX_PATH\" exec --dangerously-bypass-approvals-and-sandbox --json --skip-git-repo-check -'; "
        "done"
    )
    await run_configured_sandbox_shell(sandbox, config, command, label="verify Codex auth")


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


async def deploy(config: DeployConfig) -> CredentialSummary | None:
    runtime = MicrosandboxRuntime()
    await runtime.ensure_installed()
    should_deploy = await choose_replace(runtime, config)
    if not should_deploy:
        return None

    build_runtime_env(config)
    summary = seed_credentials(config)
    config.replace = True

    log_step("Creating Microsandbox")
    sandbox = await runtime.create(config)
    try:
        log_step("Preparing Microsandbox runtime")
        await prepare_runtime_dirs(sandbox)
        log_step("Installing Codex wrapper")
        await install_codex_wrapper(sandbox, config)
        log_step("Bootstrapping Bullpen credentials")
        await bootstrap_bullpen_credentials(sandbox, config)
        log_step("Starting Bullpen")
        await start_bullpen(sandbox, config)
        log_step("Waiting for Bullpen health")
        wait_for_health(config.bullpen_port)
        if config.codex_auth_synced:
            log_step("Verifying Codex auth")
        await verify_codex_auth(sandbox, config)
        log_step("Verifying Bullpen credentials")
        await verify_admin_credentials(sandbox, config)
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
    print(f"Credential sources attached: {len(summary.provider_sources)}")
    print(f"Git auth sources attached: {len(summary.git_sources)}")
    if config.open_browser:
        open_browser(ui_url)


async def async_main(argv: list[str] | None = None) -> int:
    try:
        config = config_from_args(argv)
        summary = await deploy(config)
        if summary is not None:
            print_success(config, summary)
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
