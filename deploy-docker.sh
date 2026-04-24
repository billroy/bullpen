#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="bullpen:local"
CONTAINER_NAME_DEFAULT="bullpen"
BULLPEN_PORT_DEFAULT="8080"
APP_PORT_DEFAULT="3000"
ADMIN_USER_DEFAULT="admin"
DOCKER_HOME_DEFAULT="$HOME/.bullpen/docker-home"

log() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$1" >&2; }
die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

prompt_default() {
  local prompt="$1"
  local default="$2"
  local value
  read -rp "$prompt [$default]: " value
  printf '%s' "${value:-$default}"
}

prompt_yes_no() {
  local prompt="$1"
  local default="${2:-N}"
  local reply
  if [[ "$default" == "Y" ]]; then
    read -rp "$prompt [Y/n]: " reply
    [[ -z "$reply" || "$reply" =~ ^[Yy]$ ]]
  else
    read -rp "$prompt [y/N]: " reply
    [[ "$reply" =~ ^[Yy]$ ]]
  fi
}

prompt_secret() {
  local prompt="$1"
  local value
  IFS= read -rsp "$prompt: " value
  printf '\n' >&2
  printf '%s' "$value"
}

require_port() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || die "$name must be numeric"
  (( value >= 1 && value <= 65535 )) || die "$name must be between 1 and 65535"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

abs_path() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p"
  else
    (cd "$p" && pwd)
  fi
}

collect_bootstrap_password() {
  local pw1 pw2
  while true; do
    pw1="$(prompt_secret "Admin password")"
    [[ -n "$pw1" ]] || { warn "Password cannot be blank."; continue; }
    pw2="$(prompt_secret "Confirm admin password")"
    [[ "$pw1" == "$pw2" ]] && break
    warn "Passwords did not match; try again."
  done
  printf '%s' "$pw1"
}

add_env_if_set() {
  local var_name="$1"
  if [[ -n "${!var_name:-}" ]]; then
    RUNTIME_ENV_ARGS+=("-e" "${var_name}=${!var_name}")
    DETECTED_CREDENTIALS+=("env:${var_name}")
  fi
}

add_git_env_if_set() {
  local var_name="$1"
  if [[ -n "${!var_name:-}" ]]; then
    RUNTIME_ENV_ARGS+=("-e" "${var_name}=${!var_name}")
    DETECTED_GIT_AUTH+=("env:${var_name}")
  fi
}

add_mount_if_exists() {
  local host_path="$1"
  local container_path="$2"
  if [[ -d "$host_path" ]]; then
    RUNTIME_VOLUME_ARGS+=("-v" "${host_path}:${container_path}:ro")
    DETECTED_CREDENTIALS+=("mount:${host_path}")
  fi
}

add_git_mount_if_exists() {
  local host_path="$1"
  local container_path="$2"
  if [[ -d "$host_path" ]]; then
    RUNTIME_VOLUME_ARGS+=("-v" "${host_path}:${container_path}:ro")
    DETECTED_GIT_AUTH+=("mount:${host_path}")
  fi
}

add_git_file_mount_if_exists() {
  local host_path="$1"
  local container_path="$2"
  if [[ -f "$host_path" ]]; then
    RUNTIME_VOLUME_ARGS+=("-v" "${host_path}:${container_path}:ro")
    DETECTED_GIT_AUTH+=("mount:${host_path}")
  fi
}

add_file_mount_if_exists() {
  local host_path="$1"
  local container_path="$2"
  if [[ -f "$host_path" ]]; then
    RUNTIME_VOLUME_ARGS+=("-v" "${host_path}:${container_path}:ro")
    DETECTED_CREDENTIALS+=("mount:${host_path}")
  fi
}

prompt_optional_credential() {
  local env_name="$1"
  local label="$2"
  local value
  value="$(prompt_secret "${label} (optional, press Enter to skip)")"
  if [[ -n "$value" ]]; then
    RUNTIME_ENV_ARGS+=("-e" "${env_name}=${value}")
    DETECTED_CREDENTIALS+=("env:${env_name}")
  fi
}

build_image() {
  docker build \
    --build-arg "BULLPEN_UID=$(id -u)" \
    --build-arg "BULLPEN_GID=$(id -g)" \
    -t "$IMAGE_NAME" .
}

seed_file_if_missing() {
  local source_path="$1"
  local target_path="$2"
  if [[ -f "$source_path" && ! -e "$target_path" ]]; then
    mkdir -p "$(dirname "$target_path")"
    cp -p "$source_path" "$target_path"
  fi
}

sync_file_if_exists() {
  local source_path="$1"
  local target_path="$2"
  if [[ -f "$source_path" ]]; then
    mkdir -p "$(dirname "$target_path")"
    cp -p "$source_path" "$target_path"
  fi
}

seed_dir_if_missing() {
  local source_path="$1"
  local target_path="$2"
  if [[ -d "$source_path" && ! -e "$target_path" ]]; then
    mkdir -p "$(dirname "$target_path")"
    cp -pR "$source_path" "$target_path"
  fi
}

sync_dir_if_exists() {
  local source_path="$1"
  local target_path="$2"
  if [[ -d "$source_path" ]]; then
    mkdir -p "$target_path"
    cp -pR "$source_path/." "$target_path"
  fi
}

claude_logged_in() {
  # Check for a non-empty credentials file in the persistent home on the host.
  # This avoids a docker exec and correctly reflects OAuth login state rather
  # than just whether the claude binary runs (which config list tests).
  [[ -s "$DOCKER_HOME/.claude/.credentials.json" ]]
}

verify_admin_credentials() {
  local output=""
  local attempt

  for attempt in {1..15}; do
    if output="$(docker exec \
      -e "BULLPEN_VERIFY_USER=${ADMIN_USER}" \
      -e "BULLPEN_VERIFY_PASSWORD=${ADMIN_PASSWORD}" \
      "$CONTAINER_NAME" \
      bash -lc 'python3 - <<'"'"'PY'"'"'
import os
import sys
from server import auth
from server.workspace_manager import GLOBAL_DIR

username = os.environ.get("BULLPEN_VERIFY_USER", "")
password = os.environ.get("BULLPEN_VERIFY_PASSWORD", "")
auth.load_credentials(GLOBAL_DIR)
ok = bool(username) and auth.check_password(password, auth.get_password_hash(username))
if not ok:
    print(f"Credential verification failed for user {username!r} in {auth.env_path(GLOBAL_DIR)}", file=sys.stderr)
    sys.exit(1)
print(f"Credential verification passed for user {username!r}.")
PY'
      2>&1
    )"; then
      printf '%s\n' "$output"
      return 0
    fi
    sleep 1
  done

  printf '%s\n' "$output" >&2
  return 1
}

require_command docker

docker info >/dev/null 2>&1 || die "Docker daemon is not running or not reachable."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_PROJECT_PATH_DEFAULT="$(dirname "$SCRIPT_DIR")/$(basename "$SCRIPT_DIR")-project"

printf '\n\033[1mBullpen Docker Deployer\033[0m\n\n'

CONTAINER_NAME="$(prompt_default "Container name" "$CONTAINER_NAME_DEFAULT")"
if [[ "$(abs_path "$PWD")" == "$SCRIPT_DIR" ]]; then
  warn "Running deploy-docker.sh from the Bullpen repo root."
  warn "Enter the project Bullpen should work on so Docker does not mount Bullpen itself by default."
  warn "You can also create or reuse a local project directory at ${LOCAL_PROJECT_PATH_DEFAULT}."
  if prompt_yes_no "Create or use local project directory ${LOCAL_PROJECT_PATH_DEFAULT}?" "Y"; then
    mkdir -p "$LOCAL_PROJECT_PATH_DEFAULT"
    WORKSPACE_INPUT="$LOCAL_PROJECT_PATH_DEFAULT"
  else
    while true; do
      read -rp "Project path to mount into /workspace (required): " WORKSPACE_INPUT
      if [[ -n "$WORKSPACE_INPUT" ]]; then
        break
      fi
      warn "Project path is required. Type . if you intentionally want to mount the Bullpen repo itself."
    done
  fi
else
  WORKSPACE_INPUT="$(prompt_default "Project path to mount into /workspace" "$PWD")"
fi
[[ -e "$WORKSPACE_INPUT" ]] || die "Workspace path does not exist: $WORKSPACE_INPUT"
[[ -d "$WORKSPACE_INPUT" ]] || die "Workspace path is not a directory: $WORKSPACE_INPUT"
WORKSPACE_PATH="$(abs_path "$WORKSPACE_INPUT")"
WORKSPACE_NAME="$(basename "$WORKSPACE_PATH")"

BULLPEN_PORT="$(prompt_default "Bullpen web port" "$BULLPEN_PORT_DEFAULT")"
APP_PORT="$(prompt_default "App port (for your project inside container)" "$APP_PORT_DEFAULT")"
require_port "Bullpen web port" "$BULLPEN_PORT"
require_port "App port" "$APP_PORT"
[[ "$BULLPEN_PORT" != "$APP_PORT" ]] || die "Bullpen web port and app port must be different"

ADMIN_USER="$(prompt_default "Admin username" "$ADMIN_USER_DEFAULT")"
ADMIN_PASSWORD="$(collect_bootstrap_password)"

RUNTIME_ENV_ARGS=()
RUNTIME_VOLUME_ARGS=()
DETECTED_CREDENTIALS=()
DETECTED_GIT_AUTH=()

# Persist the container user's home across container recreation. Claude Code
# login writes auth state to this home and cannot use host keychain-backed login
# metadata mounted read-only.
DOCKER_HOME="${BULLPEN_DOCKER_HOME:-$DOCKER_HOME_DEFAULT}"
mkdir -p "$DOCKER_HOME"
chmod 700 "$DOCKER_HOME" 2>/dev/null || true
seed_file_if_missing "$HOME/.claude.json" "$DOCKER_HOME/.claude.json"
seed_dir_if_missing "$HOME/.claude" "$DOCKER_HOME/.claude"

# Always sync the OAuth credentials file from the host so re-logins on the
# host propagate into the container home without a full re-deploy. Only runs
# when the source exists; leaves the file alone if the host has none.
if [[ -f "$HOME/.claude/.credentials.json" ]]; then
  mkdir -p "$DOCKER_HOME/.claude"
  cp -p "$HOME/.claude/.credentials.json" "$DOCKER_HOME/.claude/.credentials.json"
  chmod 600 "$DOCKER_HOME/.claude/.credentials.json" 2>/dev/null || true
fi
seed_dir_if_missing "$HOME/.codex" "$DOCKER_HOME/.codex"
sync_file_if_exists "$HOME/.codex/auth.json" "$DOCKER_HOME/.codex/auth.json"
seed_dir_if_missing "$HOME/.config/codex" "$DOCKER_HOME/.config/codex"
seed_dir_if_missing "$HOME/.config/gemini" "$DOCKER_HOME/.config/gemini"
seed_dir_if_missing "$HOME/.config/google-gemini" "$DOCKER_HOME/.config/google-gemini"
RUNTIME_VOLUME_ARGS+=("-v" "${DOCKER_HOME}:/home/bullpen")

# Auto-detect provider credentials seeded into the persistent container home.
[[ -d "$DOCKER_HOME/.claude" ]] && DETECTED_CREDENTIALS+=("home:${DOCKER_HOME}/.claude")
[[ -f "$DOCKER_HOME/.claude.json" ]] && DETECTED_CREDENTIALS+=("home:${DOCKER_HOME}/.claude.json")
[[ -f "$DOCKER_HOME/.codex/auth.json" ]] && DETECTED_CREDENTIALS+=("home:${DOCKER_HOME}/.codex/auth.json")
[[ -d "$DOCKER_HOME/.config/codex" ]] && DETECTED_CREDENTIALS+=("home:${DOCKER_HOME}/.config/codex")
[[ -d "$DOCKER_HOME/.config/gemini" ]] && DETECTED_CREDENTIALS+=("home:${DOCKER_HOME}/.config/gemini")
[[ -d "$DOCKER_HOME/.config/google-gemini" ]] && DETECTED_CREDENTIALS+=("home:${DOCKER_HOME}/.config/google-gemini")

# Auto-detect Git/GitHub auth. These are separate from agent-provider
# credentials because they enable push and pull request workflows.
add_git_env_if_set "GH_TOKEN"
add_git_env_if_set "GITHUB_TOKEN"
add_git_env_if_set "GIT_AUTHOR_NAME"
add_git_env_if_set "GIT_AUTHOR_EMAIL"
add_git_env_if_set "GIT_COMMITTER_NAME"
add_git_env_if_set "GIT_COMMITTER_EMAIL"
seed_file_if_missing "$HOME/.gitconfig" "$DOCKER_HOME/.gitconfig.host"
sync_dir_if_exists "$HOME/.config/gh" "$DOCKER_HOME/.config/gh"
[[ -f "$DOCKER_HOME/.gitconfig.host" ]] && DETECTED_GIT_AUTH+=("home:${DOCKER_HOME}/.gitconfig.host")
[[ -d "$DOCKER_HOME/.config/gh" ]] && DETECTED_GIT_AUTH+=("home:${DOCKER_HOME}/.config/gh")
if [[ -d "$HOME/.ssh" ]] && prompt_yes_no "Mount ~/.ssh read-only for git SSH remotes?" "N"; then
  add_git_mount_if_exists "$HOME/.ssh" "/home/bullpen/.ssh"
fi

# Auto-forward commonly used API/token env vars when present on host.
# ANTHROPIC_API_KEY takes priority over OAuth credentials inside the container,
# which would silently switch from subscription billing to pay-as-you-go API
# billing. Skip forwarding it when OAuth credentials are already present.
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  if [[ -s "$DOCKER_HOME/.claude/.credentials.json" ]]; then
    warn "ANTHROPIC_API_KEY is set on the host but OAuth credentials were found in ${DOCKER_HOME}/.claude/.credentials.json"
    warn "Skipping ANTHROPIC_API_KEY to preserve subscription OAuth auth. Unset it on the host or remove the credentials file to use API key billing."
  else
    add_env_if_set "ANTHROPIC_API_KEY"
  fi
fi
add_env_if_set "OPENAI_API_KEY"
add_env_if_set "GEMINI_API_KEY"
add_env_if_set "GOOGLE_API_KEY"

if [[ ${#DETECTED_CREDENTIALS[@]} -eq 0 ]]; then
  warn "No provider credentials were auto-detected on this machine."
  echo "Enter any credentials you have now; at least one is required so agent CLIs can run."
  prompt_optional_credential "CLAUDE_CODE_OAUTH_TOKEN" "Claude Code OAuth token"
  prompt_optional_credential "ANTHROPIC_API_KEY" "Anthropic API key"
  prompt_optional_credential "OPENAI_API_KEY" "OpenAI API key"
  prompt_optional_credential "GEMINI_API_KEY" "Gemini API key"
  prompt_optional_credential "GOOGLE_API_KEY" "Google API key"
  [[ ${#DETECTED_CREDENTIALS[@]} -gt 0 ]] || die "No provider credentials were supplied."
fi

if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  if prompt_yes_no "Rebuild Docker image ${IMAGE_NAME}?" "N"; then
    log "Building Docker image ${IMAGE_NAME}"
    build_image
  fi
else
  log "Building Docker image ${IMAGE_NAME}"
  build_image
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  prompt_yes_no "Container '${CONTAINER_NAME}' already exists. Replace it?" "Y" || die "Deployment aborted."
  log "Removing existing container ${CONTAINER_NAME}"
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

log "Starting container ${CONTAINER_NAME}"

DOCKER_RUN_ARGS=(
  -d
  --name "$CONTAINER_NAME"
  --restart unless-stopped
  -e "BULLPEN_BOOTSTRAP_USER=${ADMIN_USER}"
  -e "BULLPEN_BOOTSTRAP_PASSWORD=${ADMIN_PASSWORD}"
  -e "BULLPEN_BOOTSTRAP_FORCE=1"
  -e "BULLPEN_PORT=${BULLPEN_PORT}"
  -e "APP_PORT=${APP_PORT}"
  -e "BULLPEN_HIDE_UNAVAILABLE_PROJECTS=1"
  -e "BULLPEN_WORKSPACE=/workspace"
  -e "BULLPEN_WORKSPACE_NAME=${WORKSPACE_NAME}"
  -e "BULLPEN_PRODUCTION=${BULLPEN_PRODUCTION:-0}"
  -p "${BULLPEN_PORT}:${BULLPEN_PORT}"
  -p "${APP_PORT}:${APP_PORT}"
  -v "${WORKSPACE_PATH}:/workspace"
)

if [[ ${#RUNTIME_VOLUME_ARGS[@]} -gt 0 ]]; then
  DOCKER_RUN_ARGS+=("${RUNTIME_VOLUME_ARGS[@]}")
fi

if [[ ${#RUNTIME_ENV_ARGS[@]} -gt 0 ]]; then
  DOCKER_RUN_ARGS+=("${RUNTIME_ENV_ARGS[@]}")
fi

DOCKER_RUN_ARGS+=("$IMAGE_NAME")

docker run "${DOCKER_RUN_ARGS[@]}" >/dev/null

if ! verify_admin_credentials; then
  die "The container did not store the admin credentials entered in this deploy."
fi

if ! claude_logged_in; then
  warn "Claude CLI is not logged in for Docker home ${DOCKER_HOME}."
  if command -v claude >/dev/null 2>&1 && prompt_yes_no "Log in to Claude Code now using the host browser?" "Y"; then
    HOME="$DOCKER_HOME" claude auth login || true
    if claude_logged_in; then
      log "Claude CLI login saved in Docker home"
    else
      warn "Claude still does not report a valid login. Live Agent Claude workers may fail until login is completed."
    fi
  else
    warn "Install Claude Code on the host or complete login before using Claude Live Agent workers."
  fi
else
  log "Claude CLI login found in Docker home"
fi

log "Waiting for Bullpen to become reachable"
HEALTHY=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 2
  if command -v curl >/dev/null 2>&1; then
    HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${BULLPEN_PORT}/health" || true)"
    if [[ "$HTTP_CODE" == "200" ]]; then
      HEALTHY=1
      break
    fi
  else
    if docker logs "$CONTAINER_NAME" 2>&1 | grep -q "Starting Bullpen on"; then
      HEALTHY=1
      break
    fi
  fi
done

echo
if [[ "$HEALTHY" -eq 1 ]]; then
  printf '\033[32mBullpen is up.\033[0m\n'
else
  printf '\033[33mBullpen container started, but health check did not return 200 yet.\033[0m\n'
fi

printf 'UI:   http://localhost:%s\n' "$BULLPEN_PORT"
printf 'App:  http://localhost:%s\n' "$APP_PORT"
printf 'User: %s\n' "$ADMIN_USER"
printf 'Container: %s\n' "$CONTAINER_NAME"
printf 'Container home: %s\n' "$DOCKER_HOME"
printf 'Credential sources attached: %s\n' "${#DETECTED_CREDENTIALS[@]}"
printf 'Git auth sources attached: %s\n' "${#DETECTED_GIT_AUTH[@]}"
printf '\nUseful commands:\n'
printf '  docker logs -f %s\n' "$CONTAINER_NAME"
printf '  docker exec -it %s bash\n' "$CONTAINER_NAME"
printf '  docker rm -f %s\n' "$CONTAINER_NAME"
