# Deploying Bullpen on a DigitalOcean Droplet

This runbook covers a single Ubuntu 24.04 Droplet with:
- Bullpen as a `systemd` service
- nginx reverse proxy (WebSocket-safe)
- TLS via Let's Encrypt
- baseline host hardening (`ufw`, `fail2ban`)

## 1. Prerequisites

- Ubuntu 24.04 Droplet
- DNS A/AAAA record for your domain pointed to the Droplet
- Non-root sudo user
- Bullpen credentials bootstrap secret ready (`BULLPEN_BOOTSTRAP_PASSWORD`)

## 2. One-command bootstrap (optional)

Run this on the Droplet as root (or via `sudo`):

```bash
curl -fsSL https://raw.githubusercontent.com/billroy/bullpen/main/deploy-do-droplet.sh -o /tmp/deploy-do-droplet.sh
chmod +x /tmp/deploy-do-droplet.sh
sudo BULLPEN_DOMAIN=your.domain.com \
  BULLPEN_ADMIN_EMAIL=ops@your.domain.com \
  BULLPEN_ADMIN_PASSWORD='change-me' \
  /tmp/deploy-do-droplet.sh
```

What it does:
- Installs packages (`python3-venv`, `nginx`, `ufw`, `fail2ban`, `certbot`)
- Creates a least-privilege `bullpen` service user
- Clones/updates Bullpen under `/opt/bullpen`
- Creates a virtualenv and installs Python dependencies
- Bootstraps login credentials non-interactively
- Installs `systemd` + nginx configs and enables services
- Opens firewall ports `22`, `80`, `443`
- Requests/installs a TLS certificate when domain/email vars are provided

## 3. Manual install path

### Install packages

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv git nginx ufw fail2ban certbot python3-certbot-nginx
```

### Create service user and directories

```bash
sudo useradd --system --create-home --home-dir /home/bullpen --shell /usr/sbin/nologin bullpen || true
sudo mkdir -p /opt/bullpen /var/lib/bullpen/workspace
sudo chown -R bullpen:bullpen /opt/bullpen /var/lib/bullpen /home/bullpen
```

### Install Bullpen

```bash
sudo -u bullpen git clone https://github.com/billroy/bullpen.git /opt/bullpen || true
sudo -u bullpen bash -lc 'cd /opt/bullpen && git pull --ff-only'
sudo -u bullpen bash -lc 'cd /opt/bullpen && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt'
```

### Bootstrap auth (required for non-local bind)

```bash
sudo -u bullpen env BULLPEN_BOOTSTRAP_USER=admin BULLPEN_BOOTSTRAP_PASSWORD='change-me' \
  /opt/bullpen/.venv/bin/python /opt/bullpen/bullpen.py --bootstrap-credentials
```

### Install service unit

```bash
sudo cp /opt/bullpen/deploy/digitalocean/bullpen.service /etc/systemd/system/bullpen.service
sudo systemctl daemon-reload
sudo systemctl enable --now bullpen
sudo systemctl status bullpen --no-pager
```

Optional runtime env overrides can go in `/etc/default/bullpen`.

### Install nginx reverse proxy

```bash
sudo cp /opt/bullpen/deploy/digitalocean/nginx-bullpen.conf /etc/nginx/sites-available/bullpen
sudo sed -i 's/server_name example.com;/server_name your.domain.com;/' /etc/nginx/sites-available/bullpen
sudo ln -sfn /etc/nginx/sites-available/bullpen /etc/nginx/sites-enabled/bullpen
sudo nginx -t
sudo systemctl reload nginx
```

### Enable TLS

```bash
sudo certbot --nginx -d your.domain.com
```

### Firewall baseline

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo systemctl enable --now fail2ban
```

## 4. Verification

```bash
curl -sS http://127.0.0.1:8080/health
curl -I https://your.domain.com/
```

Expected health response:

```json
{"ok": true}
```

## 5. Upgrade procedure

```bash
sudo -u bullpen bash -lc 'cd /opt/bullpen && git pull --ff-only && .venv/bin/pip install -r requirements.txt'
sudo systemctl restart bullpen
sudo systemctl status bullpen --no-pager
```

## 6. Reverse proxy requirements (important)

Bullpen login/session and Socket.IO rely on forwarded headers and WebSocket upgrades.
Your proxy config must pass:
- `Host`
- `X-Forwarded-Host`
- `X-Forwarded-Proto`
- `X-Forwarded-For`
- `Upgrade` and `Connection: upgrade`

Without these, remote auth/session behavior and live updates can break.

## 7. Notes on agent CLIs

Deploying the web app does not automatically install Claude/Codex/Gemini CLIs.
Install/authenticate any CLI you want workers to run on the Droplet, and ensure the `bullpen` service user can execute them.
