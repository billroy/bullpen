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

## Notes

- Bullpen runs on the configured Bullpen port (default `8080`).
- Your app can use the configured app port (default `3000`) from the same container workspace.
- Bullpen auth/session data is persisted by mounting `~/.bullpen` into the container.
