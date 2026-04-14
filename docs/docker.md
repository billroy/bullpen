# Docker Deployment (Dual Ports)

This guide runs Bullpen in Docker while exposing:
- one port for Bullpen UI/API
- one port for the app being developed inside the same workspace container

## 1. Build image

```bash
docker build -t bullpen:local .
```

## 2. Run with two host ports

```bash
docker run -d \
  --name bullpen \
  -e BULLPEN_BOOTSTRAP_PASSWORD='change-me' \
  -e BULLPEN_BOOTSTRAP_USER='admin' \
  -e BULLPEN_PORT=8080 \
  -e APP_PORT=3000 \
  -p 8080:8080 \
  -p 3000:3000 \
  -v ~/my-project:/workspace \
  bullpen:local
```

What this does:
- Bootstraps Bullpen credentials once (if none exist yet).
- Starts Bullpen on `0.0.0.0:$BULLPEN_PORT`.
- Leaves `APP_PORT` as a convention for your app process.

Your app must still bind to `0.0.0.0:$APP_PORT` from inside the container.

## 3. Optional docker compose

Use `docker-compose.yml` for a repeatable setup:

```bash
BULLPEN_BOOTSTRAP_PASSWORD='change-me' docker compose up -d --build
```

The compose file includes:
- default single-container mode (`bullpen`)
- optional advanced profile (`app`) for a separate app runtime container:

```bash
BULLPEN_BOOTSTRAP_PASSWORD='change-me' docker compose --profile app up -d --build
```

## 4. Provider CLI authentication

Bullpen does not manage provider secrets itself. You have two common options:

1. Pass token env vars at runtime (preferred when available).
2. Mount provider config directories read-only.

Example read-only mount:

```bash
-v ~/.claude:/root/.claude:ro
```

### Risks of read-only `.claude` mount

Read-only prevents direct file modification, but does not prevent secret use.

- Token replay/exfiltration risk: any process in the container that can read mounted files can use those credentials for API calls.
- Prompt-injection blast radius: agent-executed code can intentionally trigger paid calls or privileged actions using mounted auth.
- Account-scope leakage: if host auth is tied to a personal or broad-scope account, compromise impacts more than this one project.
- Metadata leakage: config files can expose account identifiers, org/project context, model preferences, and usage endpoints.
- Cross-project coupling: one shared host credential mount means all containerized projects run with the same identity unless isolated.

Recommended mitigations:
- Prefer short-lived or scoped env tokens over full profile mounts when possible.
- Use a dedicated low-privilege provider account for containerized automation.
- Mount only exact subpaths needed, not whole home directories.
- Treat workspace code as potentially hostile; avoid running untrusted repos with mounted credentials.

## 5. Notes

- No nginx is required inside the container for this model.
- For multiple app services, expose a range (for example `-p 3000-3010:3000-3010`) or add explicit mappings.
- Persistent Bullpen auth/session files are stored in the container user home (`~/.bullpen`). Mount a volume there if you need auth/session persistence across container rebuilds.
