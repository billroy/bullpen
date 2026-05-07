#!/usr/bin/env bash
set -euo pipefail

BASE_NAME="${BULLPEN_MICROSANDBOX_BASE:-bullpen-microsandbox-local}"
SOURCE_IMAGE="${BULLPEN_MICROSANDBOX_SOURCE_IMAGE:-node:22-bookworm}"
REPO_URL="${BULLPEN_GITHUB_REPO_URL:-https://github.com/billroy/bullpen.git}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ ! -f "${REPO_ROOT}/bullpen.py" ]]; then
  SOURCE_DIR="${BULLPEN_MICROSANDBOX_SOURCE_DIR:-$HOME/.bullpen/microsandbox-source/bullpen}"
  if [[ -d "${SOURCE_DIR}/.git" ]]; then
    echo "==> Updating Bullpen source at ${SOURCE_DIR}"
    git -C "${SOURCE_DIR}" fetch --depth 1 origin
    git -C "${SOURCE_DIR}" reset --hard FETCH_HEAD
  else
    echo "==> Fetching Bullpen source from ${REPO_URL} into ${SOURCE_DIR}"
    mkdir -p "$(dirname "${SOURCE_DIR}")"
    git clone --depth 1 "${REPO_URL}" "${SOURCE_DIR}"
  fi
  REPO_ROOT="${SOURCE_DIR}"
fi

python3 - "$BASE_NAME" "$SOURCE_IMAGE" "$REPO_ROOT" <<'PY'
import asyncio
import inspect
import sys
from pathlib import Path

base_name = sys.argv[1]
source_image = sys.argv[2]
repo_root = Path(sys.argv[3]).resolve()
prepare_name = f"{base_name}-prepare"


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def run(sandbox, command, *, label):
    print(f"==> {label}")
    result = await maybe_await(sandbox.exec("bash", ["-lc", command]))
    success = getattr(result, "success", None)
    code = getattr(result, "exit_code", None)
    if code is None:
        code = getattr(result, "returncode", None)
    failed = success is False or code not in (None, 0)
    stdout = getattr(result, "stdout_text", "") or getattr(result, "stdout", "")
    stderr = getattr(result, "stderr_text", "") or getattr(result, "stderr", "")
    if failed:
        if stdout:
            print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        raise SystemExit(f"error: {label} failed")
    if stdout.strip():
        print(stdout)
    if stderr.strip():
        print(stderr, file=sys.stderr)


async def main():
    try:
        import microsandbox
    except ImportError as exc:
        raise SystemExit("error: install Microsandbox with: python3 -m pip install microsandbox") from exc

    if hasattr(microsandbox, "is_installed"):
        installed = await maybe_await(microsandbox.is_installed())
        if not installed:
            print("==> Installing Microsandbox runtime")
            await maybe_await(microsandbox.install())

    try:
        existing = await maybe_await(microsandbox.Sandbox.get(prepare_name))
        try:
            await maybe_await(existing.stop())
        except Exception:
            pass
        try:
            await maybe_await(existing.remove())
        except Exception:
            await maybe_await(microsandbox.Sandbox.remove(prepare_name))
    except Exception:
        pass

    print(f"==> Creating prepare sandbox {prepare_name} from {source_image}")
    sandbox = await maybe_await(
        microsandbox.Sandbox.create(
            prepare_name,
            image=microsandbox.Image.oci(source_image),
            replace=True,
            volumes={"/app": microsandbox.Volume.bind(str(repo_root), readonly=True)},
            network=microsandbox.Network.allow_all(),
        )
    )

    try:
        await run(
            sandbox,
            """
            set -euo pipefail
            export DEBIAN_FRONTEND=noninteractive
            apt-get update
            apt-get install -y --no-install-recommends \
              bash ca-certificates curl gh git iproute2 python3 python3-pip python3-venv ripgrep strace
            rm -rf /var/lib/apt/lists/*
            """,
            label="install OS packages",
        )
        await run(
            sandbox,
            """
            set -euo pipefail
            python3 -m venv /opt/bullpen-venv
            /opt/bullpen-venv/bin/python -m pip install --upgrade pip
            /opt/bullpen-venv/bin/python -m pip install --no-cache-dir -r /app/requirements.txt
            /opt/bullpen-venv/bin/python - <<'PY2'
import flask
import flask_socketio
import pyfiglet
PY2
            """,
            label="install Bullpen Python dependencies",
        )
        await run(
            sandbox,
            """
            set -euo pipefail
            export npm_config_audit=false
            export npm_config_fund=false
            export npm_config_progress=false
            npm install -g --no-audit --no-fund --no-progress --omit=dev @anthropic-ai/claude-code
            npm install -g --no-audit --no-fund --no-progress --omit=dev @openai/codex
            npm install -g --no-audit --no-fund --no-progress --omit=dev @google/gemini-cli
            """,
            label="install agent CLIs",
        )
        await run(
            sandbox,
            """
            set -euo pipefail
            python3 --version
            /opt/bullpen-venv/bin/python -c 'import flask, flask_socketio, pyfiglet'
            git --version
            gh --version
            node --version
            npm --version
            claude --version
            codex --version
            gemini --version
            """,
            label="verify prepared base",
        )
        print(f"==> Stopping prepare sandbox")
        if hasattr(sandbox, "stop_and_wait"):
            await maybe_await(sandbox.stop_and_wait())
        else:
            await maybe_await(sandbox.stop())
            await maybe_await(sandbox.wait())
        print(f"==> Creating local snapshot {base_name}")
        await maybe_await(
            microsandbox.Snapshot.create(
                prepare_name,
                name=base_name,
                force=True,
                labels={"app": "bullpen", "kind": "microsandbox-base"},
            )
        )
        print(f"Prepared Microsandbox base: {base_name}")
    finally:
        try:
            await maybe_await(microsandbox.Sandbox.remove(prepare_name))
        except Exception:
            pass


asyncio.run(main())
PY
