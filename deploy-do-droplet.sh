#!/usr/bin/env bash
# Bootstrap Bullpen on a DigitalOcean Ubuntu 24.04 Droplet.
# Run as root (or with sudo):
#   sudo BULLPEN_DOMAIN=your.domain.com BULLPEN_ADMIN_EMAIL=ops@your.domain.com \
#     BULLPEN_ADMIN_PASSWORD='change-me' ./deploy-do-droplet.sh

set -euo pipefail

REPO_URL="${BULLPEN_REPO:-https://github.com/billroy/bullpen.git}"
REPO_REF="${BULLPEN_REF:-main}"
SERVICE_USER="${BULLPEN_USER:-bullpen}"
SERVICE_GROUP="${BULLPEN_GROUP:-$SERVICE_USER}"
INSTALL_DIR="${BULLPEN_HOME:-/opt/bullpen}"
WORKSPACE_DIR="${BULLPEN_WORKSPACE:-/var/lib/bullpen/workspace}"
APP_PORT="${BULLPEN_PORT:-8080}"
DOMAIN="${BULLPEN_DOMAIN:-}"
ADMIN_USER="${BULLPEN_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${BULLPEN_ADMIN_PASSWORD:-}"
ADMIN_EMAIL="${BULLPEN_ADMIN_EMAIL:-}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$1" >&2; }
die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root (use sudo)."
[[ -n "$ADMIN_PASSWORD" ]] || die "set BULLPEN_ADMIN_PASSWORD."

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    warn "script tested on Ubuntu; detected ID=${ID:-unknown}."
  fi
fi

log "Installing system packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-venv git nginx ufw fail2ban certbot python3-certbot-nginx curl

log "Creating service account and directories"
if ! getent group "$SERVICE_GROUP" >/dev/null; then
  groupadd --system "$SERVICE_GROUP"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_GROUP" --create-home --home-dir "/home/$SERVICE_USER" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
mkdir -p "$INSTALL_DIR" "$WORKSPACE_DIR" "/home/$SERVICE_USER/.bullpen"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR" "$WORKSPACE_DIR" "/home/$SERVICE_USER"

log "Cloning or updating Bullpen"
if [[ -d "$INSTALL_DIR/.git" ]]; then
  sudo -u "$SERVICE_USER" bash -lc "cd '$INSTALL_DIR' && git fetch --all --tags && git checkout '$REPO_REF' && git pull --ff-only"
else
  rm -rf "$INSTALL_DIR"
  sudo -u "$SERVICE_USER" git clone --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
fi

log "Installing Python dependencies into venv"
sudo -u "$SERVICE_USER" bash -lc "cd '$INSTALL_DIR' && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt"

log "Bootstrapping Bullpen credentials"
sudo -u "$SERVICE_USER" env \
  BULLPEN_BOOTSTRAP_USER="$ADMIN_USER" \
  BULLPEN_BOOTSTRAP_PASSWORD="$ADMIN_PASSWORD" \
  "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/bullpen.py" --bootstrap-credentials

log "Installing systemd unit"
cat > /etc/systemd/system/bullpen.service <<SERVICE
[Unit]
Description=Bullpen service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
Environment=BULLPEN_PRODUCTION=1
Environment=BULLPEN_BOOTSTRAP_USER=$ADMIN_USER
EnvironmentFile=-/etc/default/bullpen
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/bullpen.py --workspace $WORKSPACE_DIR --host 127.0.0.1 --port $APP_PORT --no-browser
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$INSTALL_DIR $WORKSPACE_DIR /home/$SERVICE_USER/.bullpen

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now bullpen

log "Configuring nginx reverse proxy"
cat > /etc/nginx/sites-available/bullpen <<NGINX
server {
    listen 80;
    server_name ${DOMAIN:-_};

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/bullpen /etc/nginx/sites-enabled/bullpen
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

log "Applying firewall baseline"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now fail2ban

if [[ -n "$DOMAIN" && -n "$ADMIN_EMAIL" ]]; then
  log "Requesting Let's Encrypt certificate"
  certbot --nginx --non-interactive --agree-tos --redirect -m "$ADMIN_EMAIL" -d "$DOMAIN"
else
  warn "Skipping certbot (set BULLPEN_DOMAIN and BULLPEN_ADMIN_EMAIL to enable)."
fi

log "Health check"
curl -fsS "http://127.0.0.1:$APP_PORT/health" >/dev/null || die "local health check failed"

cat <<DONE

Bullpen deployment complete.

Service status:
  systemctl status bullpen --no-pager

Health endpoint:
  curl http://127.0.0.1:$APP_PORT/health

If TLS was configured:
  https://$DOMAIN/

DONE
