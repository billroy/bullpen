# Microsandbox deployment specification

## Objective

Provide a secure Microsandbox deployment path for Bullpen where Claude, Codex, Gemini, GitHub CLI, and project commands run inside a microVM, with only the intended host paths mounted.

Microsandbox should become the preferred secure local deployment path. `deploy-docker.sh` remains the behavior model for prompts, defaults, credential seeding, workspace mounting, health checks, and success output. The implementation must not install heavyweight CLIs during every deploy.

## Architecture

Use a two-phase flow:

1. **Prepare phase:** one-time local setup that creates a reusable Bullpen Microsandbox base with all tooling installed.
2. **Run phase:** fast per-project startup that mounts the project and persistent auth home, syncs credentials, bootstraps Bullpen login, starts Bullpen, and exits.

The prepare phase may take time and use network/package managers. The run phase should be nearly instant after the base is prepared.

No registry is required. The prepared base must live on the local machine.

## Commands

Provide two scripts:

```bash
./deploy/microsandbox/prepare.sh
python3 sandboxed-bullpen.py [options]
```

`prepare.sh` is the one-time setup. It installs or builds the local Microsandbox base.

`sandboxed-bullpen.py` is the normal user entrypoint. It refuses to perform heavyweight apt/npm installs. If the prepared base is missing, it tells the user to run `./deploy/microsandbox/prepare.sh`.

## Prepare phase

`deploy/microsandbox/prepare.sh` creates a local reusable Bullpen Microsandbox base containing:

- Python 3 and pip
- Bullpen Python dependencies
- Node.js and npm
- Git
- curl
- bash
- ripgrep
- GitHub CLI
- Claude Code CLI
- Codex CLI
- Gemini CLI

The prepare phase should support users who have not cloned the Bullpen repo yet. A user should be able to run a single downloaded shell script, or an equivalent command documented in the README, and have it fetch whatever Bullpen files are needed.

Preferred behavior:

- Use the Bullpen GitHub repo as the default source.
- Avoid any external container registry.
- Start from `node:22-bookworm` as the preferred source image. It is Debian-based, multi-arch, and includes Node.js 22 plus npm, which avoids the biggest failure-prone part of the bare `debian` bootstrap.
- Add Python 3, pip/venv, git, curl, bash, ripgrep, GitHub CLI, Bullpen Python dependencies, and the agent CLIs during prepare.
- Do not require Docker to be installed. The prepare script should use Microsandbox's image/rootfs/snapshot capabilities directly. If the chosen Microsandbox primitive cannot consume `node:22-bookworm` without Docker, pick the nearest Microsandbox-native equivalent rather than adding Docker as a host dependency.
- If `node:22-bookworm` does not work cleanly with Microsandbox on Apple Silicon, fall back to `python:3.12-bookworm` and add only the missing Node/npm/GitHub CLI pieces during prepare.
- Do not use bare `debian` for the prepared Bullpen base except as a diagnostic fallback.
- Store the prepared result locally under a stable name, for example `bullpen-microsandbox-local` if Microsandbox supports local OCI images, or a named local Microsandbox snapshot/volume if that is the better supported primitive.
- Verify all installed CLIs before declaring success:

```bash
python3 --version
git --version
gh --version
claude --version
codex --version
gemini --version
```

The prepare phase must keep tool installation separate from user auth/config state. Do not install npm global packages into `/home/bullpen`; use image filesystem paths or a dedicated tooling path baked into the prepared base.

## Run phase

`sandboxed-bullpen.py` is command-line driven. Prompting is only for secrets.

```bash
python3 sandboxed-bullpen.py [options]
```

Options:

```text
--sandbox-name NAME          Sandbox name. Default: bullpen
--workspace PATH             Project directory mounted as /workspace. Default: current directory
--bullpen-port PORT          Host and guest Bullpen port. Default: 8080
--app-port PORT              Host and guest client app port. Default: 3000
--admin-user USER            Bullpen admin user. Default: admin
--admin-password PASSWORD    Bullpen admin password. If omitted, prompt securely.
--base NAME                  Prepared Microsandbox base. Default: bullpen-microsandbox-local
--sandbox-home PATH          Persistent sandbox home. Default: ~/.bullpen/microsandbox-home
--replace                    Replace an existing sandbox without prompting.
--no-replace                 Abort if the sandbox already exists.
--open                       Open the Bullpen UI in a host browser after startup. Default.
--no-open                    Do not open a browser; only print URLs.
--install-bullpen-project    Clone Bullpen into a local project directory and mount that as /workspace.
-h, --help                   Show usage.
```

If `--admin-password` is omitted, prompt once and confirm it. No other option should require an interactive prompt because every non-secret value has a default or flag.

## Defaults

- Sandbox name: `bullpen`
- Workspace: current directory
- Bullpen port: `8080`
- Client app port: `3000`
- Admin user: `admin`
- Prepared base: `bullpen-microsandbox-local`
- Sandbox home: `~/.bullpen/microsandbox-home`
- Browser opening: enabled
- Replacement behavior: prompt if a sandbox with the same name exists, unless `--replace` or `--no-replace` is provided

When launched from the Bullpen source checkout and `--workspace` is not supplied, keep the Docker deployer's safety behavior: do not silently mount the Bullpen repo as the user project. Require `--workspace` or `--install-bullpen-project` in that case.

## Validation

Validate before creating or replacing the sandbox:

- Python is 3.10+
- The `microsandbox` Python package is importable; otherwise print `python3 -m pip install microsandbox`
- Microsandbox runtime is installed; install it through the SDK when missing
- Host is supported by Microsandbox: Apple Silicon macOS or Linux with KVM
- Prepared Microsandbox base exists locally
- Workspace path exists and is a directory
- Bullpen source path exists and contains `bullpen.py`, unless Bullpen source is baked into the prepared base
- Ports are numeric and in `1..65535`
- Bullpen port and app port are different
- `--replace` and `--no-replace` are not both set
- Git is installed on the host when `--install-bullpen-project` is used

Fail fast with one clear error message per problem. Do not run apt or npm from `sandboxed-bullpen.py`.

## Microsandbox implementation

Use the native Microsandbox Python SDK.

The sandbox create call should have this shape:

```python
sandbox = await Sandbox.create(
    sandbox_name,
    snapshot=prepared_base_snapshot_path,
    replace=replace,
    ports={
        bullpen_port: bullpen_port,
        app_port: app_port,
    },
    volumes={
        "/workspace": Volume.bind(workspace_path),
        "/home/bullpen": Volume.bind(sandbox_home),
    },
    network=Network.allow_all(),
    env=runtime_env,
)
```

If Bullpen source is not baked into the prepared base, also mount the local Bullpen checkout read-only:

```python
"/app": Volume.bind(bullpen_source_path, readonly=True)
```

Use `ports={host_port: guest_port}`. Host exposure is localhost-only. Do not publish Bullpen to all host interfaces.

Use `Network.allow_all()` for the first implementation because the sandbox must call AI APIs, GitHub, and package managers during the prepare phase. The microVM is the security boundary.

The script starts Bullpen as a detached process inside the sandbox and then exits after successful health and credential checks. The sandbox must continue running after `sandboxed-bullpen.py` terminates.

## Filesystem layout

Run phase mounts:

```text
<host project path>              -> /workspace      writable
~/.bullpen/microsandbox-home     -> /home/bullpen   writable
<Bullpen source checkout>        -> /app            read-only, only if not baked into base
```

`/workspace` must be a live writable bind mount, not a copy. File browser edits, worker changes, git worktrees, generated files, and task outputs must mutate the real host project directory.

`/home/bullpen` persists across sandbox replacement. Create it if needed and restrict it to the current user. Store CLI auth state, Bullpen global config, and logs there.

Do not install toolchains into `/home/bullpen`. Tooling belongs in the prepared base. Auth/config belongs in `/home/bullpen`.

Codex OAuth auth follows the proven Docker topology: seed/sync host auth into the runtime-owned persistent home, then mount only that home. Do not add a nested `~/.codex` bind mount over `/home/bullpen/.codex`; overlapping mounts make Microsandbox differ from Docker and can hide stale state or change refresh persistence behavior.

## Credentials

Mirror `deploy-docker.sh`.

Seed or sync these provider credentials into the persistent sandbox home when present:

- `~/.claude`
- `~/.claude.json`
- `~/.config/codex`
- `~/.codex`
- `~/.codex/auth.json`
- `~/.config/gemini`
- `~/.config/google-gemini`

Seed host `~/.codex` into `/home/bullpen/.codex` if missing and sync host `~/.codex/auth.json` into `/home/bullpen/.codex/auth.json` on every deploy. This mirrors `deploy-docker.sh`: after deploy starts, Codex inside Microsandbox owns the runtime-home token store and can persist refresh-token rotation there.

When `~/.codex/auth.json` was synced, deploy must verify the sandbox can use it before declaring success:

```bash
test -w /home/bullpen/.codex/auth.json
HOME=/home/bullpen codex login status
```

Forward these environment variables when present:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`
- `CLAUDE_CODE_OAUTH_TOKEN`

Handle `ANTHROPIC_API_KEY` like `deploy-docker.sh`: if Claude OAuth credentials exist in the persistent home, do not forward `ANTHROPIC_API_KEY`, because it can silently switch Claude Code from subscription OAuth auth to API-key billing.

For GitHub and git operations, support:

- `GH_TOKEN`
- `GITHUB_TOKEN`
- `GIT_AUTHOR_NAME`
- `GIT_AUTHOR_EMAIL`
- `GIT_COMMITTER_NAME`
- `GIT_COMMITTER_EMAIL`
- `~/.gitconfig`
- `~/.config/gh`

If the host `gh` CLI can provide a valid GitHub token, copy it into the sandbox home as GitHub CLI auth. If no usable GitHub auth is found, warn and continue; Bullpen can run without GitHub push/PR support.

If no provider credentials are found, prompt for optional provider credentials. At least one provider credential is required before starting Bullpen.

## Bullpen runtime

Start Bullpen inside the sandbox:

```bash
cd /app
python3 bullpen.py \
  --workspace /workspace \
  --host 0.0.0.0 \
  --port "$BULLPEN_PORT" \
  --no-browser
```

Write stdout/stderr to:

```text
/home/bullpen/logs/bullpen.log
```

Bind Bullpen to `0.0.0.0` inside the microVM so Microsandbox port publishing can reach the guest service. Host exposure remains localhost-only through Microsandbox port publishing.

Set these environment variables inside the sandbox:

- `BULLPEN_BOOTSTRAP_USER`
- `BULLPEN_BOOTSTRAP_PASSWORD`
- `BULLPEN_BOOTSTRAP_FORCE=1`
- `BULLPEN_PORT`
- `APP_PORT`
- `BULLPEN_HIDE_UNAVAILABLE_PROJECTS=1`
- `BULLPEN_WORKSPACE=/workspace`
- `BULLPEN_WORKSPACE_NAME=<basename of workspace path>`
- `BULLPEN_PRODUCTION=0`, unless the host environment overrides it

The run phase bootstraps Bullpen login credentials, starts Bullpen, checks `/health`, verifies credentials, prints success output, and exits.

The script does not start the user's client app. It only exposes the client app port so Bullpen workers, shells, or user commands inside the sandbox can run an app on that port.

## Port exposure

Expose:

```text
host localhost:$BULLPEN_PORT -> guest 0.0.0.0:$BULLPEN_PORT
host localhost:$APP_PORT     -> guest 0.0.0.0:$APP_PORT
```

Do not add LAN/public binding in the first implementation.

## Lifecycle

If the named sandbox already exists:

- With `--replace`: replace it.
- With `--no-replace`: exit nonzero without changing it.
- With neither flag: ask `Sandbox 'bullpen' already exists. Replace it? [Y/n]`.

If the user answers no, exit successfully without changing the existing sandbox.

Replacement means:

- Stop and remove the existing sandbox runtime
- Keep `~/.bullpen/microsandbox-home`
- Keep the host workspace untouched
- Create a fresh sandbox with the requested mounts, ports, prepared base, env, and command

Do not attach to an existing sandbox for normal deploy. Deployment should produce a known runtime.

## Health and verification

After starting Bullpen, wait for:

```text
http://127.0.0.1:<BULLPEN_PORT>/health
```

Treat HTTP 200 as success. Retry for up to 20 seconds, matching `deploy-docker.sh`.

After health passes, verify admin credentials inside the sandbox by running a short Python check against Bullpen's auth module and confirming the entered username/password matches the stored hash.

If health or credential verification fails:

- Print `/home/bullpen/logs/bullpen.log`
- Print the failed command or HTTP status
- Exit nonzero

## Success output

After health and credential verification pass, print:

```text
Bullpen is up.
UI:   http://localhost:8080
App:  http://localhost:3000
User: admin
Sandbox: bullpen
Sandbox home: ~/.bullpen/microsandbox-home
Credential sources attached: N
Git auth sources attached: N
```

Then open `http://localhost:$BULLPEN_PORT` in the host browser unless `--no-open` was supplied. Browser opening is best-effort; printing the URL is required.

## Optional project install

Support:

```bash
python3 sandboxed-bullpen.py --install-bullpen-project
```

When enabled, clone `BULLPEN_GITHUB_REPO_URL` into the default local project path and use that as `--workspace`.

If the target path is already a git checkout, use it. If it exists and is not empty or not a git checkout, fail with a clear error.

Default:

```text
BULLPEN_GITHUB_REPO_URL=https://github.com/billroy/bullpen.git
```

## Acceptance criteria

- `deploy/microsandbox/prepare.sh` creates a local prepared Bullpen Microsandbox base without requiring an external registry
- After prepare succeeds, `python3 sandboxed-bullpen.py --admin-password test-password --no-open` starts Bullpen on `http://localhost:8080` without running apt or npm
- `--sandbox-name`, `--workspace`, `--bullpen-port`, `--app-port`, `--admin-user`, `--admin-password`, `--base`, `--replace`, `--no-replace`, and `--no-open` work without prompts
- Omitting `--admin-password` prompts securely and confirms the password
- The mounted project appears in Bullpen as `/workspace`
- Creating or editing files through Bullpen changes the host project directory
- Bullpen and client app ports are both exposed on host localhost
- Bullpen starts with authentication enabled using the requested admin credentials
- Claude, Codex, Gemini, and GitHub credentials are available inside the sandbox when present on the host
- The script refuses invalid ports and refuses to use the same port for Bullpen and the app
- `--no-replace` exits nonzero without modifying an existing sandbox
- Answering no to the replacement prompt exits successfully without modifying an existing sandbox
- After success, `sandboxed-bullpen.py` exits while the Microsandbox runtime and Bullpen process keep running
- Failure to start Bullpen prints useful logs and exits nonzero
- The implementation uses the Microsandbox Python SDK directly and does not require `msb server start --dev`

## References

- Docker deployment model: `deploy-docker.sh`
- Microsandbox repo: https://github.com/superradcompany/microsandbox
- Microsandbox getting started: https://docs.microsandbox.dev/guides/getting-started/
- Microsandbox Python SDK: https://docs.microsandbox.dev/references/python-sdk/
