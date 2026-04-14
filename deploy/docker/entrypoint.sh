#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${BULLPEN_WORKSPACE:-/workspace}"
HOST="${BULLPEN_HOST:-0.0.0.0}"
PORT="${BULLPEN_PORT:-8080}"
APP_PORT="${APP_PORT:-3000}"

mkdir -p "$WORKSPACE"

if [[ ! -f "$HOME/.claude.json" && -d "$HOME/.claude/backups" ]]; then
  CLAUDE_BACKUP="$(find "$HOME/.claude/backups" -maxdepth 1 -type f -name '.claude.json.backup.*' | sort -r | head -n 1 || true)"
  if [[ -n "$CLAUDE_BACKUP" ]]; then
    echo "Restoring Claude config from backup: ${CLAUDE_BACKUP}"
    cp "$CLAUDE_BACKUP" "$HOME/.claude.json"
  fi
fi

if [[ -n "${BULLPEN_BOOTSTRAP_PASSWORD:-}" ]]; then
  echo "Bootstrapping Bullpen credentials (if none exist yet)"
  python3 bullpen.py --bootstrap-credentials
else
  echo "BULLPEN_BOOTSTRAP_PASSWORD not set; skipping credential bootstrap"
fi

echo "Starting Bullpen on ${HOST}:${PORT} (app port convention: ${APP_PORT})"
exec python3 bullpen.py \
  --workspace "$WORKSPACE" \
  --host "$HOST" \
  --port "$PORT" \
  --no-browser \
  "$@"
