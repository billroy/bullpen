# Docker Deployment

Use the interactive deploy script from the repo root:

```bash
./deploy-docker.sh
```

The script handles deployment end-to-end:
- prompts for container name, workspace path, ports, and Bullpen admin credentials
- builds the Docker image when needed
- starts/replaces the container with the correct runtime settings
- auto-loads provider credentials by mounting local auth directories and forwarding detected API/token environment variables
- falls back to secure credential prompts only when no credentials are detected

After deployment, the script prints URLs and operational commands (`docker logs`, `docker exec`, remove/redeploy).

The container runs Bullpen as a non-root `bullpen` user. This is required for
agent CLIs such as Claude Code, which refuse unattended permission-bypass flags
when executed as root.

Detected provider credentials are mounted into that user's home directory. For
Claude Code this includes both:

```text
~/.claude      -> /home/bullpen/.claude
~/.claude.json -> /home/bullpen/.claude.json
```

Claude may need both paths because some versions keep account state in
`~/.claude.json` while backups live under `~/.claude/backups/`.

## Notes

- Bullpen runs on the configured Bullpen port (default `8080`).
- Your app can use the configured app port (default `3000`) from the same container workspace.
- Bullpen auth/session data is persisted by mounting `~/.bullpen` into the container.
