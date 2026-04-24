# Docker Deployment

Use the interactive deploy script from the repo root:

```bash
./deploy-docker.sh
```

The script handles deployment end-to-end:
- prompts for container name, project path or local project directory, ports,
  and Bullpen admin credentials
- builds the Docker image when needed
- starts/replaces the container with the correct runtime settings
- updates Bullpen login credentials to match the admin username/password entered for this deploy
- verifies inside the container that the entered admin password matches the stored Bullpen credentials
- auto-loads provider credentials by mounting local auth directories and forwarding detected API/token environment variables
- falls back to secure credential prompts only when no credentials are detected

When you run `./deploy-docker.sh` from the Bullpen repo root, it now requires
an explicit choice instead of defaulting to the Bullpen source tree. You can
either enter an existing project path or let the script create/reuse a local
directory next to the Bullpen checkout, such as `../bullpen-project`. That
directory is mounted at `/workspace`, auto-registered as a Bullpen project, and
becomes the current project on startup. Type `.` only if you intentionally want
the container to mount Bullpen itself.

After deployment, the script prints URLs and operational commands (`docker logs`, `docker exec`, remove/redeploy).

The container runs Bullpen as a non-root `bullpen` user. This is required for
agent CLIs such as Claude Code, which refuse unattended permission-bypass flags
when executed as root.

The deploy script builds that user with the host UID/GID. This lets the
container read host credential files that are commonly mode `600`, including
Claude and GitHub auth files.

Detected provider credentials are mounted into that user's home directory. For
Claude Code this includes both:

```text
~/.claude      -> /home/bullpen/.claude
~/.claude.json -> /home/bullpen/.claude.json
```

Claude may need both paths because some versions keep account state in
`~/.claude.json` while backups live under `~/.claude/backups/`.

If `~/.claude.json` is missing but a backup exists under `~/.claude/backups`,
the entrypoint restores the newest backup into the container user's writable
home directory before Bullpen starts.

Claude Code's normal desktop login may rely on host-native credential storage
that is not available inside Docker. The reliable Docker path is to run the
host Claude CLI with the persistent Docker home:

```text
./deploy-docker.sh -> HOME=~/.bullpen/docker-home claude auth login
```

The browser opens normally on the host, while Claude writes the resulting auth
state into the same directory Docker mounts at `/home/bullpen`. Future container
replacements keep the Claude auth state because `~/.bullpen/docker-home`
persists.

If `CLAUDE_CODE_OAUTH_TOKEN` is already set in the host environment, the deploy
script still forwards it into the container.

For Codex, the deploy script copies the host Codex home into the persistent
Docker home and refreshes the login file on each deploy:

```text
~/.codex/auth.json -> /home/bullpen/.codex/auth.json
```

Without that file, Codex can still launch but OpenAI API calls fail with a 401
because no bearer or basic authentication header is available. If
`OPENAI_API_KEY` is set in the host environment, the deploy script also forwards
it into the container.

## Git and Pull Request Auth

The Docker image includes `git`, `openssh-client`, and the GitHub CLI (`gh`).
The deploy script auto-forwards common GitHub and Git identity environment
variables when they are set:

```text
GH_TOKEN
GITHUB_TOKEN
GIT_AUTHOR_NAME
GIT_AUTHOR_EMAIL
GIT_COMMITTER_NAME
GIT_COMMITTER_EMAIL
```

It also syncs host GitHub CLI auth into the persistent Docker home and copies
Git config when present:

```text
~/.config/gh -> /home/bullpen/.config/gh
~/.gitconfig -> /home/bullpen/.gitconfig.host
```

The entrypoint creates a writable `/home/bullpen/.gitconfig` that includes the
host config, marks the mounted workspace as a safe Git directory, applies Git
identity environment variables when provided, and runs `gh auth setup-git` when
`GH_TOKEN`, `GITHUB_TOKEN`, or copied GitHub CLI auth is available. It also
installs host-scoped GitHub credential-helper entries directly in git config as
a fallback, so HTTPS web git operations still authenticate even if `gh auth
setup-git` does not update the config in that container instance.

For SSH remotes, the deploy script can optionally mount `~/.ssh` read-only into
`/home/bullpen/.ssh`. Prefer a dedicated deploy key or a scoped GitHub token
over mounting a broad personal SSH directory.

## Notes

- Bullpen runs on the configured Bullpen port (default `8080`).
- Your app can use the configured app port (default `3000`) from the same container workspace.
- Bullpen auth/session data is persisted by mounting `~/.bullpen` into the container.
- Docker deploys default to `BULLPEN_PRODUCTION=0` because the script serves
  Bullpen at local HTTP URLs. Set `BULLPEN_PRODUCTION=1` only when an HTTPS
  reverse proxy terminates TLS in front of the container.
