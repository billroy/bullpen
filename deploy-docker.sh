#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="bullpen:local"
CONTAINER_NAME_DEFAULT="bullpen"
BULLPEN_PORT_DEFAULT="8080"
APP_PORT_DEFAULT="3000"
ADMIN_USER_DEFAULT="admin"
DOCKER_HOME_DEFAULT="$HOME/.bullpen/docker-home"
BULLPEN_GITHUB_REPO_URL="${BULLPEN_GITHUB_REPO_URL:-https://github.com/billroy/bullpen.git}"
BULLPEN_DOCKER_BUILD_CONTEXT="${BULLPEN_DOCKER_BUILD_CONTEXT:-$BULLPEN_GITHUB_REPO_URL}"
INSTALL_BULLPEN_PROJECT=0

log() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$1" >&2; }
die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: ./deploy-docker.sh [options]

Options:
  --install-bullpen-project
      Clone Bullpen from GitHub into the local project directory and mount it
      as /workspace. This replaces the old interactive Bullpen-project prompt.
  -h, --help
      Show this help.

Environment:
  BULLPEN_GITHUB_REPO_URL
      GitHub repository URL used for project installation.
      Default: https://github.com/billroy/bullpen.git
  BULLPEN_DOCKER_BUILD_CONTEXT
      Docker build context used for the Bullpen image.
      Default: same as BULLPEN_GITHUB_REPO_URL
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --install-bullpen-project)
        INSTALL_BULLPEN_PROJECT=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
    shift
  done
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local value
  read_prompt "$prompt [$default]: " value || die "Unable to read input."
  printf '%s' "${value:-$default}"
}

prompt_yes_no() {
  local prompt="$1"
  local default="${2:-N}"
  local reply
  if [[ "$default" == "Y" ]]; then
    read_prompt "$prompt [Y/n]: " reply || die "Unable to read input."
    [[ -z "$reply" || "$reply" =~ ^[Yy]$ ]]
  else
    read_prompt "$prompt [y/N]: " reply || die "Unable to read input."
    [[ "$reply" =~ ^[Yy]$ ]]
  fi
}

prompt_secret() {
  local prompt="$1"
  local value
  read_prompt "$prompt: " value 1 || die "Unable to read input."
  printf '%s' "$value"
}

read_prompt() {
  local prompt="$1"
  local var_name="$2"
  local silent="${3:-0}"
  local status

  if [[ -r /dev/tty && -w /dev/tty ]]; then
    printf '%s' "$prompt" > /dev/tty
    if [[ "$silent" -eq 1 ]]; then
      IFS= read -rs "$var_name" < /dev/tty
      status=$?
      printf '\n' > /dev/tty
      return "$status"
    fi
    IFS= read -r "$var_name" < /dev/tty
    return $?
  fi

  printf '%s' "$prompt" >&2
  if [[ "$silent" -eq 1 ]]; then
    IFS= read -rs "$var_name"
    status=$?
    printf '\n' >&2
    return "$status"
  fi
  IFS= read -r "$var_name"
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

resolve_script_dir() {
  local source_path="${BASH_SOURCE[0]:-}"
  if [[ -n "$source_path" && -f "$source_path" ]]; then
    cd "$(dirname "$source_path")" && pwd
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
    -t "$IMAGE_NAME" \
    "$BULLPEN_DOCKER_BUILD_CONTEXT"
}

install_bullpen_project_from_github() {
  local target_path="$1"

  require_command git

  if [[ -d "$target_path/.git" ]]; then
    log "Using existing Bullpen project checkout at ${target_path}"
    return 0
  fi

  if [[ -e "$target_path" ]]; then
    if [[ -d "$target_path" && -z "$(find "$target_path" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
      rmdir "$target_path"
    else
      die "Bullpen project path already exists and is not a git checkout: $target_path"
    fi
  fi

  log "Cloning Bullpen from ${BULLPEN_GITHUB_REPO_URL} into ${target_path}"
  git clone --depth 1 "$BULLPEN_GITHUB_REPO_URL" "$target_path"
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

github_gh() {
  env -u GH_CONFIG_DIR -u XDG_CONFIG_HOME HOME="$DOCKER_HOME" gh "$@"
}

host_github_gh() {
  env -u GH_TOKEN -u GITHUB_TOKEN -u GH_CONFIG_DIR -u XDG_CONFIG_HOME gh "$@"
}

yaml_single_quote() {
  local value="$1"
  value="${value//\'/\'\'}"
  printf "'%s'" "$value"
}

github_cli_logged_in() {
  command -v gh >/dev/null 2>&1 || return 1
  github_gh auth status --hostname github.com >/dev/null 2>&1
}

github_hosts_has_oauth_token() {
  [[ -s "$DOCKER_HOME/.config/gh/hosts.yml" ]] || return 1
  grep -Eq '^[[:space:]]*oauth_token:' "$DOCKER_HOME/.config/gh/hosts.yml"
}

copy_host_github_cli_auth_to_docker_home() {
  local token=""
  local user=""

  command -v gh >/dev/null 2>&1 || return 1
  token="$(host_github_gh auth token --hostname github.com 2>/dev/null)" || return 1
  [[ -n "$token" ]] || return 1
  user="$(GH_TOKEN="$token" env -u GITHUB_TOKEN -u GH_CONFIG_DIR -u XDG_CONFIG_HOME gh api --hostname github.com user --jq .login 2>/dev/null || true)"

  mkdir -p "$DOCKER_HOME/.config/gh"
  {
    printf 'github.com:\n'
    printf '    git_protocol: https\n'
    printf '    oauth_token: %s\n' "$(yaml_single_quote "$token")"
    if [[ -n "$user" ]]; then
      printf '    user: %s\n' "$(yaml_single_quote "$user")"
    fi
  } > "$DOCKER_HOME/.config/gh/hosts.yml"
  chmod 600 "$DOCKER_HOME/.config/gh/hosts.yml" 2>/dev/null || true

  github_cli_logged_in
}

github_token_env_valid() {
  local token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
  [[ -n "$token" ]] || return 1
  command -v gh >/dev/null 2>&1 || return 1
  GH_TOKEN="$token" github_gh auth status --hostname github.com >/dev/null 2>&1
}

ensure_github_cli_auth() {
  if [[ -n "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]]; then
    if github_token_env_valid; then
      log "GitHub token environment variable is valid for Docker git operations"
    else
      warn "GH_TOKEN/GITHUB_TOKEN is set, but GitHub CLI could not validate it."
      warn "Git pushes and PR creation may fail until that token is fixed."
    fi
    return 0
  fi

  if github_hosts_has_oauth_token && github_cli_logged_in; then
    log "GitHub CLI login found in Docker home"
    return 0
  fi

  if copy_host_github_cli_auth_to_docker_home; then
    log "Copied host GitHub CLI token into Docker home"
    return 0
  fi

  if [[ -s "$DOCKER_HOME/.config/gh/hosts.yml" ]]; then
    warn "GitHub CLI auth exists in Docker home but is not valid, and the host token could not be copied automatically."
  else
    warn "No valid GitHub CLI auth was found in Docker home ${DOCKER_HOME}, and the host token could not be copied automatically."
  fi

  if ! command -v gh >/dev/null 2>&1; then
    warn "Install GitHub CLI on the host or set GH_TOKEN/GITHUB_TOKEN before using Docker git push or auto-PR."
    return 0
  fi

  warn "Docker git push and auto-PR may fail until the host GitHub CLI login is refreshed."
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

parse_args "$@"

require_command docker

docker info >/dev/null 2>&1 || die "Docker daemon is not running or not reachable."
SCRIPT_DIR="$(resolve_script_dir)"
if [[ -n "$SCRIPT_DIR" ]]; then
  LOCAL_PROJECT_PATH_DEFAULT="$(dirname "$SCRIPT_DIR")/$(basename "$SCRIPT_DIR")-project"
else
  LOCAL_PROJECT_PATH_DEFAULT="$PWD/bullpen-project"
fi

printf '\n\033[1mBullpen Docker Deployer\033[0m\n\n'

CONTAINER_NAME="$(prompt_default "Container name" "$CONTAINER_NAME_DEFAULT")"
if [[ "$INSTALL_BULLPEN_PROJECT" -eq 1 ]]; then
  install_bullpen_project_from_github "$LOCAL_PROJECT_PATH_DEFAULT"
  WORKSPACE_INPUT="$LOCAL_PROJECT_PATH_DEFAULT"
elif [[ -n "$SCRIPT_DIR" && "$(abs_path "$PWD")" == "$SCRIPT_DIR" ]]; then
  while true; do
    read_prompt "Project path to mount into /workspace (required): " WORKSPACE_INPUT || die "Unable to read input."
    if [[ -n "$WORKSPACE_INPUT" ]]; then
      break
    fi
    warn "Project path is required. Type . if you intentionally want to mount the Bullpen repo itself."
  done
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
ensure_github_cli_auth
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
  warn "Complete Claude Code login outside this deploy before using Claude Live Agent workers."
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
