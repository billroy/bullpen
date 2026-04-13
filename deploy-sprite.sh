#!/usr/bin/env bash
#
# Deploy Bullpen to a Fly.io Sprite.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/billroy/bullpen/main/deploy-sprite.sh | bash
#
# Or clone the repo and run locally:
#   bash deploy-sprite.sh
#
set -euo pipefail

REPO="https://github.com/billroy/bullpen.git"

# ── helpers ──────────────────────────────────────────────────────────

die()  { printf '\033[31mError:\033[0m %s\n' "$1" >&2; exit 1; }
step() { printf '\033[1;34m▸\033[0m %s ... ' "$1"; }
ok()   { printf '\033[32mdone\033[0m\n'; }

# ── preflight ────────────────────────────────────────────────────────

command -v sprite >/dev/null 2>&1 || {
    echo "The Sprite CLI is not installed."
    echo "Install it with:  curl https://sprites.dev/install.sh | bash"
    echo "Then run:          sprite login"
    exit 1
}

# ── prompts ──────────────────────────────────────────────────────────

printf '\n\033[1mBullpen Sprite Deployer\033[0m\n\n'

read -rp "Sprite name [bullpen]: " SPRITE_NAME
SPRITE_NAME="${SPRITE_NAME:-bullpen}"

read -rp "Admin username [admin]: " ADMIN_USER
ADMIN_USER="${ADMIN_USER:-admin}"

while true; do
    read -rsp "Password for '${ADMIN_USER}': " ADMIN_PW; echo
    [ -n "$ADMIN_PW" ] || { echo "Password cannot be blank."; continue; }
    read -rsp "Confirm password: " ADMIN_PW2; echo
    [ "$ADMIN_PW" = "$ADMIN_PW2" ] && break
    echo "Passwords did not match. Try again."
done

echo

# ── create sprite ────────────────────────────────────────────────────

step "Creating Sprite '${SPRITE_NAME}'"
if sprite list 2>/dev/null | grep -q "^${SPRITE_NAME} "; then
    printf '\033[33malready exists\033[0m\n'
else
    sprite create "$SPRITE_NAME" --skip-console >/dev/null
    ok
fi

S="-s $SPRITE_NAME"

# ── clone + install ──────────────────────────────────────────────────

step "Cloning repo and installing dependencies"
CLONE_OUT=$(sprite exec $S -- bash -c "
    if [ -d ~/bullpen/.git ]; then
        cd ~/bullpen && git pull --ff-only
    else
        git clone ${REPO} ~/bullpen
    fi
    cd ~/bullpen && pip install -q -r requirements.txt
" 2>&1) || {
    printf '\033[31mfailed\033[0m\n'
    echo "$CLONE_OUT"
    die "Clone or install failed."
}
ok

# ── install Node.js ─────────────────────────────────────────────

step "Ensuring Node.js is available"
NODE_OUT=$(sprite exec $S -- bash -c "
    command -v node >/dev/null 2>&1 && echo ok || {
        curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - &&
        sudo apt-get install -y nodejs
    }
" 2>&1) || {
    printf '\033[31mfailed\033[0m\n'
    echo "$NODE_OUT"
    die "Node.js installation failed."
}
ok

# ── install AI agent CLIs ───────────────────────────────────────

step "Installing AI agent CLIs (claude, codex, gemini)"
CLI_OUT=$(sprite exec $S -- npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli 2>&1) || {
    printf '\033[31mfailed\033[0m\n'
    echo "$CLI_OUT"
    die "CLI installation failed."
}
ok

# ── bootstrap credentials ───────────────────────────────────────────

step "Setting up admin credentials"
# sprite exec --env has known issues with variable expansion on Sprites,
# so we write env vars into an inline script instead.
ESCAPED_PW=$(printf '%s' "$ADMIN_PW" | sed "s/'/'\\\\''/g")
ESCAPED_USER=$(printf '%s' "$ADMIN_USER" | sed "s/'/'\\\\''/g")
CRED_OUT=$(sprite exec $S -- bash -c "
    export BULLPEN_BOOTSTRAP_PASSWORD='${ESCAPED_PW}'
    export BULLPEN_BOOTSTRAP_USER='${ESCAPED_USER}'
    cd ~/bullpen && python bullpen.py --bootstrap-credentials
" 2>&1) || {
    printf '\033[31mfailed\033[0m\n'
    echo "$CRED_OUT"
    die "Credential bootstrap failed."
}
echo "$CRED_OUT" | grep -qi "error" && {
    printf '\033[31mfailed\033[0m\n'
    echo "$CRED_OUT"
    die "Credential bootstrap reported an error."
}
ok

# ── production env ───────────────────────────────────────────────────

step "Configuring production environment"
sprite exec $S -- bash -c "
    grep -q BULLPEN_PRODUCTION ~/.bashrc 2>/dev/null || \
        echo 'export BULLPEN_PRODUCTION=1' >> ~/.bashrc
    # Disable Codex bubblewrap sandbox — Sprites are already isolated VMs
    mkdir -p ~/.config/codex
    cat > ~/.config/codex/config.yaml <<'YAML'
sandbox_mode: danger-full-access
YAML
" 2>&1 || {
    printf '\033[31mfailed\033[0m\n'
    die "Could not configure production environment."
}
ok

# ── create service ───────────────────────────────────────────────────

step "Creating background service"
# --args is comma-separated: "-c" must be a separate arg from the command string
SERVICE_OUT=$(sprite exec $S -- bash -c "
    sprite-env services delete bullpen 2>/dev/null; \
    sprite-env services create bullpen \
        --cmd /usr/bin/bash \
        --args '-c,source ~/.bashrc && cd ~/bullpen && python bullpen.py --host 0.0.0.0 --port 8080 --no-browser' \
        --http-port 8080 \
        2>&1
" 2>&1) || {
    printf '\033[31mfailed\033[0m\n'
    echo "$SERVICE_OUT"
    die "Could not create the bullpen service."
}
ok

# ── make public ──────────────────────────────────────────────────────

step "Making Sprite URL public"
sprite url $S update --auth public 2>&1 || {
    printf '\033[31mfailed\033[0m\n'
    die "Could not make Sprite URL public."
}
ok

# ── agent login (optional) ──────────────────────────────────────

echo ""
echo "── Agent login (optional) ──────────────────────────"
echo "Each agent CLI needs a one-time login."
echo "You can skip any you don't use."
echo ""

read -rp "Log in to Claude Code? [y/N]: " DO_CLAUDE
if [[ "$DO_CLAUDE" == [yY] ]]; then
    echo ""
    echo "Claude Code requires a token for headless login."
    echo "On your LOCAL machine, run:  claude setup-token"
    echo "Then paste the token here."
    echo ""
    read -rsp "Claude Code OAuth token (input hidden): " CLAUDE_TOKEN; echo
    if [ -n "$CLAUDE_TOKEN" ]; then
        ESCAPED_TOKEN=$(printf '%s' "$CLAUDE_TOKEN" | sed "s/'/'\\\\''/g")
        sprite exec $S -- bash -c "
            grep -q CLAUDE_CODE_OAUTH_TOKEN ~/.bashrc 2>/dev/null && \
                sed -i '/CLAUDE_CODE_OAUTH_TOKEN/d' ~/.bashrc
            echo 'export CLAUDE_CODE_OAUTH_TOKEN='\''${ESCAPED_TOKEN}'\''' >> ~/.bashrc
        " 2>&1 && printf '\033[32mClaude Code token saved.\033[0m\n' \
              || printf '\033[31mFailed to save Claude Code token.\033[0m\n'
    else
        echo "Skipped (no token entered)."
    fi
    echo ""
fi

read -rp "Log in to Codex? [y/N]: " DO_CODEX
if [[ "$DO_CODEX" == [yY] ]]; then
    sprite exec $S -- codex auth login --device-auth
    echo ""
fi

read -rp "Log in to Gemini CLI? [y/N]: " DO_GEMINI
if [[ "$DO_GEMINI" == [yY] ]]; then
    sprite exec $S -- gemini auth login
    echo ""
fi

# ── resolve URL ──────────────────────────────────────────────────────

SPRITE_URL=$(sprite info $S 2>/dev/null | awk '/https:\/\//{for(i=1;i<=NF;i++) if($i ~ /^https:\/\//) {print $i; exit}}')
[ -n "$SPRITE_URL" ] || SPRITE_URL="(could not determine — run 'sprite info $S')"

# ── health check ─────────────────────────────────────────────────────

step "Waiting for service to become reachable"
HEALTHY=false
for i in 1 2 3 4 5 6; do
    sleep 5
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$SPRITE_URL" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" != "000" ] && [ "$HTTP_CODE" != "502" ] && [ "$HTTP_CODE" != "503" ]; then
        HEALTHY=true
        break
    fi
done
if $HEALTHY; then
    printf '\033[32mreachable (HTTP %s)\033[0m\n' "$HTTP_CODE"
else
    printf '\033[33mnot yet reachable (HTTP %s)\033[0m\n' "$HTTP_CODE"
    echo ""
    echo "The service may still be starting. Check with:"
    echo "  sprite exec $S -- sprite-env services logs bullpen"
fi

# ── done ─────────────────────────────────────────────────────────────

echo ""
echo "────────────────────────────────────────────────────"
printf '\033[1;32m  Bullpen URL:\033[0m  %s\n' "$SPRITE_URL"
echo "────────────────────────────────────────────────────"
echo ""
printf 'Log in with username "%s" and the password you just set.\n\n' "$ADMIN_USER"
printf 'To update later:\n'
printf '  sprite exec %s -- bash -c "cd ~/bullpen && git pull"\n' "$S"
printf '  sprite exec %s -- sprite-env services restart bullpen\n\n' "$S"
printf 'To log in to an agent later:\n'
printf '  claude setup-token  # then set CLAUDE_CODE_OAUTH_TOKEN on Sprite\n'
printf '  sprite exec %s -- codex auth login --device-auth\n' "$S"
printf '  sprite exec %s -- gemini auth login\n\n' "$S"
