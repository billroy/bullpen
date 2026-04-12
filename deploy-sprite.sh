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

while true; do
    read -rsp "Admin password: " ADMIN_PW; echo
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
sprite exec $S -- bash -c "
    if [ -d ~/bullpen/.git ]; then
        cd ~/bullpen && git pull --ff-only
    else
        git clone ${REPO} ~/bullpen
    fi
    cd ~/bullpen && pip install -q -r requirements.txt
" >/dev/null 2>&1
ok

# ── bootstrap credentials ───────────────────────────────────────────

step "Setting up admin credentials"
sprite exec $S \
    --env "BULLPEN_BOOTSTRAP_PASSWORD=${ADMIN_PW}" \
    --env "BULLPEN_BOOTSTRAP_USER=admin" \
    -- bash -c "cd ~/bullpen && python bullpen.py --bootstrap-credentials" \
    >/dev/null 2>&1
ok

# ── production env ───────────────────────────────────────────────────

step "Configuring production environment"
sprite exec $S -- bash -c "
    grep -q BULLPEN_PRODUCTION ~/.bashrc 2>/dev/null || \
        echo 'export BULLPEN_PRODUCTION=1' >> ~/.bashrc
" >/dev/null 2>&1
ok

# ── create service ───────────────────────────────────────────────────

step "Creating background service"
sprite exec $S -- bash -c "
    sprite-env services create bullpen \
        --cmd bash \
        --args '-c source ~/.bashrc && cd ~/bullpen && python bullpen.py --host 0.0.0.0 --port 8080 --no-browser' \
        2>/dev/null || \
    sprite-env services restart bullpen 2>/dev/null || true
" >/dev/null 2>&1
ok

# ── make public ──────────────────────────────────────────────────────

step "Making Sprite URL public"
sprite url $S update --auth public >/dev/null 2>&1
ok

# ── done ─────────────────────────────────────────────────────────────

printf '\n\033[1;32mBullpen is live at:\033[0m https://%s.sprites.app\n\n' "$SPRITE_NAME"
printf 'Log in with username "admin" and the password you just set.\n'
printf 'To update later:  sprite exec %s -- bash -c "cd ~/bullpen && git pull"\n' "$S"
printf '                  sprite exec %s -- sprite-env services restart bullpen\n\n' "$S"
