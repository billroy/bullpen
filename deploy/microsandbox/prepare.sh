#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "warn: deploy/microsandbox/prepare.sh is deprecated; use python3 deploy-msb.py --prepare-base" >&2
exec python3 "${REPO_ROOT}/deploy-msb.py" --prepare-base "$@"
