# Transition Plan: Gemini CLI to Antigravity CLI

## Purpose

Bullpen should replace its Gemini CLI provider with Google Antigravity CLI only
if Antigravity can support Bullpen's MCP-backed worker contract. This is a hard
cutover, not a compatibility migration:

- The Bullpen UI stops offering `gemini`.
- Deploy scripts stop installing and authenticating `gemini`.
- New workers and live-agent chats use `antigravity`.
- The old Gemini adapter is removed from the active provider registry.
- Stale `agent: gemini` state is rejected cleanly. It is not translated to
  Antigravity and not kept alive through compatibility code.

MCP support is the decision point. If Antigravity cannot load Bullpen's MCP tools
in a reliable, scoped, non-interactive run, this task changes from "replace
Gemini with Antigravity" to "remove Gemini and do not add an Antigravity
provider yet."

## Verified Facts

### External Platform Facts

Public reporting on Google's I/O 2026 Antigravity announcement says Gemini CLI
and Gemini Code Assist IDE extensions stop serving requests for free, Google AI
Pro, and Google AI Ultra individual users on June 18, 2026. The same reporting
says business users are not required to migrate immediately. Bullpen targets
local individual installs, so the individual migration is the relevant path.

Antigravity is positioned as Google's agent-first coding platform. Antigravity
2.0 includes a desktop app, a CLI, and an SDK. It should not be assumed to be a
flag-compatible Gemini CLI replacement.

### Local `agy` 1.0.8 Facts

The local machine has `/opt/homebrew/bin/agy`; `agy --version` reports `1.0.8`.
Observed help output confirms:

- Binary name: `agy`.
- Non-interactive prompt mode: `--print`, `-p`, and alias `--prompt`.
- Model flag: `--model`.
- Print timeout flag: `--print-timeout`, default `5m0s`.
- Permission bypass flag: `--dangerously-skip-permissions`.
- Sandbox flag: `--sandbox`.
- Extra workspace directory flag: `--add-dir`, repeatable.
- Subcommands include `models`, `plugin`, `install`, `update`, and `changelog`.
- `agy plugin` supports `import [source]` from `gemini` or `claude`.
- `agy --help` does not advertise `--output-format`, `--mcp-config`, or
  `--allowed-mcp-server-names`.
- Running `agy plugin --help` under the normal sandbox tried to create
  `~/.gemini/config`; using a temporary `HOME` created
  `~/.gemini/config` and `~/.gemini/antigravity-cli/...`.

The local probe partially confirmed MCP configuration behavior, but did not
complete an authenticated `agy --print` MCP tool call. Authentication behavior,
model names, machine-readable output, Bullpen MCP invocation, and container auth
remain Phase 0 gates.

## Bullpen Current State

Gemini is currently a first-class AI provider alongside `claude`, `codex`, and
`opencode`.

The current implementation is [server/agents/gemini_adapter.py](../server/agents/gemini_adapter.py).
It implements the shared `AgentAdapter` interface and is registered in
[server/agents/__init__.py](../server/agents/__init__.py) under `"gemini"`.
Workers and live agents both resolve adapters through `get_adapter(name)`.

The Gemini adapter currently:

- Finds the `gemini` binary via `BULLPEN_GEMINI_PATH`, `PATH`, and common local
  install paths.
- Builds `gemini --model <model> --output-format stream-json
  --allowed-mcp-server-names bullpen --approval-mode yolo --prompt <prompt>`.
- Injects Bullpen MCP by writing a temporary `settings.json` and setting
  `GEMINI_CLI_SYSTEM_SETTINGS_PATH`.
- Loads headless auth values from `~/.gemini/.env`.
- Parses Gemini JSONL stream/result output for focus views, final output, and
  usage accounting.

Bullpen-side references that must change if Antigravity passes Phase 0:

- Adapter registry: [server/agents/__init__.py](../server/agents/__init__.py).
- Validation: `VALID_AGENTS` and `VALID_WORKER_COLOR_KEYS` in
  [server/validation.py](../server/validation.py).
- Provider colors: [server/init.py](../server/init.py) and
  [static/utils.js](../static/utils.js).
- Provider labels: [server/manager.py](../server/manager.py) and
  [static/components/WorkerConfigModal.js](../static/components/WorkerConfigModal.js).
- Frontend provider/model options: [static/utils.js](../static/utils.js),
  [static/components/LiveAgentChatTab.js](../static/components/LiveAgentChatTab.js),
  and [static/components/WorkerConfigModal.js](../static/components/WorkerConfigModal.js).
- Top-toolbar color controls:
  [static/components/TopToolbar.js](../static/components/TopToolbar.js).
- Model aliases: [server/model_aliases.py](../server/model_aliases.py).
- Usage parsing: [server/usage.py](../server/usage.py).
- Worker error classification and capacity short-circuit:
  [server/workers.py](../server/workers.py).
- Live-agent error classification:
  [server/events.py](../server/events.py).
- Runtime hardening: [server/prompt_hardening.py](../server/prompt_hardening.py).
- Deployment: [Dockerfile](../Dockerfile), [deploy-sprite.sh](../deploy-sprite.sh),
  [deploy-docker.sh](../deploy-docker.sh),
  [docker-compose.yml](../docker-compose.yml), and
  [deploy-sandbox.py](../deploy-sandbox.py).
- Tests covering agents, workers, usage, validation, model aliases, model catalog
  validation, frontend provider/model lists, live-agent tabs, events, manager,
  deploy scripts, and Dockerfile content.

Existing worker and live-chat paths already avoid process crashes for unknown
providers: workers block the task with `Unknown agent: <name>`, and live chat
emits `Unknown provider: <name>`. The cutover should improve those stale-Gemini
messages, but it should not add Gemini-to-Antigravity conversion.

## Target Behavior

### Provider Identity

`antigravity` becomes the canonical provider key only if Phase 0 proves MCP
support.

`gemini` is removed as a supported provider. It should not appear in provider
dropdowns, default config, deploy docs, provider install flows, active adapter
registration, or new tests as a supported option.

### Stale Gemini State

Because this is a hard cutover with no users to migrate, Bullpen should reject
stale Gemini state cleanly rather than translating it.

Worker behavior:

- If a persisted worker still has `agent: gemini`, worker start should block the
  assigned task with a clear non-retryable message:
  `Gemini CLI support has been removed. Reconfigure this worker to Antigravity
  or another supported provider.`
- The worker should return to idle and should not spawn `gemini` or `agy`.
- The task should not be left stuck in `in_progress`.
- No provider/model rewrite should be attempted.

Live-agent behavior:

- The provider list should contain `antigravity`, not `gemini`.
- If a stale browser tab or remembered selection sends `provider: gemini`, the
  server should emit a clear `chat:error`:
  `Gemini CLI support has been removed. Choose Antigravity or another supported
  provider.`
- The server should not normalize, remember, or silently rewrite the stale
  selection.

Model alias behavior:

- Remove Gemini-specific aliasing for active provider use.
- Add Antigravity aliases only for confirmed Antigravity model names and
  shorthand. Do not map Gemini model slugs to Antigravity models as a
  compatibility feature.

### MCP and Ticket Safety

Bullpen ticket writes are live application state. Antigravity is viable only if
it can call Bullpen's server-backed MCP tools in worker and live-agent runs.
Agents must not be asked to edit `.bullpen/tasks` files directly.

The current Gemini path uses a temporary settings file and
`GEMINI_CLI_SYSTEM_SETTINGS_PATH`. `agy` 1.0.8 help does not expose an equivalent
per-run MCP config flag. Phase 0 must prove a reliable alternative before any
adapter/product work proceeds.

Acceptable MCP outcomes:

- A documented or observed per-run config/env override that scopes Bullpen MCP
  to the current run.
- A temporary `HOME` or config-dir strategy that loads only the Bullpen MCP
  server for the current subprocess and does not mutate the user's real config.
- A plugin-based mechanism that can be generated/installed per Bullpen runtime,
  is non-interactive after setup, and exposes the required Bullpen ticket tools.

Unacceptable outcomes:

- No MCP support in `agy --print`.
- MCP support only in the desktop app, not CLI.
- A global-user-config-only approach that would mutate unrelated user
  Antigravity state.
- A setup requiring manual per-worker configuration.
- Any fallback where the agent writes `.bullpen/tasks` files directly.

If Phase 0 lands in an unacceptable outcome, stop. The correct follow-up plan is
to yank Gemini from Bullpen and leave Antigravity unimplemented until Google
ships a usable CLI MCP surface.

## Phase 0 Spike Result

Status as of June 15, 2026: **GO for local Antigravity adapter build.**

The spike proved that authenticated Antigravity CLI print mode can call
plugin-configured MCP tools through `mcp_config.json`. It first passed with a
synthetic Bullpen-shaped MCP server, then the user ran the real Bullpen MCP
inbox test outside the Codex command sandbox and confirmed success:
`agy --print` called `list_tickets(status="inbox")` and printed the actual
Bullpen inbox.

Observed:

- `strings agy` contains real MCP implementation strings, not just incidental
  text. Evidence includes `mcp_config.json`, `mcpServers`, `command`, `args`,
  `env`, `cwd`, `serverUrl`, `enabledTools`, `disabledTools`,
  `tools/list`, `tools/call`, `resources/list`, `resources/read`,
  `GetMcpServerStates`, `RefreshMcpServers`, and MCP server status values.
- A local plugin containing `plugin.json` plus `mcp_config.json` validated
  successfully with `agy plugin validate`.
- The same local plugin installed successfully with `agy plugin install`.
- Validation reported `mcpServers: 1 processed`, proving the plugin loader
  recognizes MCP server declarations.
- The plugin install copied the plugin under
  `~/.gemini/config/plugins/<plugin-name>/` and recorded `mcpServers` in
  `import_manifest.json`.
- `agy --print` starts a local language server before entering print mode. In
  the normal command sandbox this failed with
  `listen tcp 127.0.0.1:0: bind: operation not permitted`; outside the sandbox
  it successfully bound random localhost HTTP/gRPC ports.
- Outside the sandbox, unauthenticated `agy --print` initialized print mode and
  then stopped at OAuth. This proves the local-server startup path is viable but
  does not prove model or MCP execution.
- A temporary `HOME` strategy works for plugin validation/install and avoids
  writing the real user config during those steps.
- After authenticating Antigravity in the user's main terminal, `agy models`
  succeeded and listed available models, proving CLI auth was usable.
- Auth is applied through the real profile/keyring path; a throwaway `HOME` did
  not inherit authentication.
- Installing a synthetic Bullpen-shaped plugin into the authenticated real
  profile, then running `agy --print`, successfully called the configured MCP
  tool and printed the returned inbox ticket ids/titles.
- The synthetic test plugin was uninstalled from the real Antigravity profile
  after the run.
- A self-contained user-run script,
  [tmp/python-mcp-test.py](../tmp/python-mcp-test.py), created a temporary
  Antigravity plugin pointing at the real Bullpen MCP stdio server, installed
  it, ran `agy --print`, and uninstalled it.
- The user confirmed that the script worked and that `agy` printed the actual
  Bullpen inbox.
- The user then ran a controlled write smoke against the real Bullpen MCP
  server. `agy` created a disposable ticket through `create_ticket`, updated it
  through `update_ticket`, and the ticket appeared in the Bullpen UI as
  `agy-mcp-write-smoke-20260615-111929-ce9e71-ZasH`.
- The server-backed Bullpen ticket CLI subsequently listed that ticket in
  `done` status, confirming the write path went through the running Bullpen
  server rather than direct task-file edits.
- The user then restarted Bullpen onto the cutover code and ran the real worker
  smoke. A temporary Antigravity worker completed disposable ticket
  `agy-worker-smoke-20260615-113424-16nS`, and the server-backed Bullpen ticket
  CLI listed that ticket in `done` status.
- The user then ran the live-agent chat smoke successfully. `chat:send` with
  provider `antigravity` returned live chat output and completed with
  `chat:done` while using the Bullpen MCP read path.

Not yet proven:

- A fully isolated temporary `HOME` can also satisfy Antigravity
  authentication; the observed auth path appears tied to the real
  profile/keyring.
- A Docker or Microsandbox worker can authenticate non-interactively.
- A machine-readable output/usage mode exists.

Important caveat:

- The real-HOME baseline run was intentionally attempted to check existing
  credentials. Antigravity was not authenticated, and the run did mutate
  `~/.gemini/config` by creating `.migrated`, `mcp_config.json`, and a project
  entry. That makes global-user-config mutation a live risk, not a theoretical
  one. The build must prefer an isolated config/HOME path; if that cannot be
  authenticated and loaded reliably, Antigravity is not ready for Bullpen.

Current readiness decision:

- **Local runtime ready.** The minimum viable local contract is proven for
  authenticated `agy --print`, Bullpen MCP read/write access, the Bullpen
  worker lifecycle, and live-agent chat.
- **Keep production/deploy blocked behind auth and isolation follow-up.** The
  working path uses the real authenticated Antigravity profile and installs a
  temporary plugin into real `~/.gemini/config/plugins`.
- **Treat usage accounting as unavailable until proven otherwise.** `agy`
  help does not expose a structured output mode, and the successful tests used
  plain text.

## Implementation Plan

### Current Build Slice

The first local adapter slice is implemented.

- [server/agents/antigravity_adapter.py](../server/agents/antigravity_adapter.py)
  adds a local authenticated `agy --print` provider.
- The adapter treats `agy` output as plain text and returns empty usage.
- Each run generates a unique temporary Antigravity plugin containing
  `plugin.json` and `mcp_config.json`.
- The plugin exposes Bullpen's MCP stdio server with the required ticket tools:
  `list_tickets`, `list_tasks`, `list_tickets_by_title`, `create_ticket`, and
  `update_ticket`.
- The adapter installs the plugin before invoking `agy` and uninstalls it
  during cleanup.
- `antigravity` is registered as the active Google provider.
- `gemini` is removed from active provider registration, validation, UI
  provider lists, default colors, default labels, and deploy-facing model
  catalog assumptions.
- Stale Gemini workers and stale Gemini live-chat requests fail clearly without
  spawning either `gemini` or `agy`.

Do not update Docker, Microsandbox, or deploy scripts in this slice. Those
remain blocked until Antigravity has a documented or observed non-interactive
auth path suitable for headless environments.

Recommended next step: capture common Antigravity failure outputs and decide
whether to add provider-specific error classification. Use controlled local
probes for missing binary, unauthenticated profile, invalid model, timeout, and
plugin install/uninstall failures. Keep deploy work blocked until a headless
auth/config isolation path is proven.

### Phase 0: MCP Spike and Go/No-Go

This phase is a stop-and-wait decision point. Do not implement the Antigravity
adapter, UI wiring, deploy changes, or tests beyond probe fixtures until Phase 0
has an authenticated MCP result and explicit approval to proceed.

Phase 0 must answer four questions in this order.

1. **Can `agy --print` use MCP tools at all?**

   - Create a throwaway MCP server with one harmless tool, for example
     `bullpen_probe_echo`.
   - Configure it through an Antigravity plugin containing `mcp_config.json`;
     plugin validation/install already processes `mcpServers`.
   - Prefer a temporary `HOME` or other isolated config directory. Use the real
     user config only as a last-resort diagnostic, because the baseline probe
     already proved that `agy` mutates `~/.gemini/config`.
   - Run `agy --print "Call the bullpen_probe_echo tool with value ok"` from a
     temporary workspace.
   - Capture stdout, stderr, exit code, generated config files, and logs.

   Result: passed. An authenticated `agy --print` run called
   `list_tickets(status="inbox")` and printed returned ids/titles first with a
   synthetic Bullpen-shaped MCP server and then, via user-run script, against
   the real Bullpen MCP server.

2. **Can Bullpen scope MCP per run?**

   - Repeat the authenticated probe with a temporary `HOME` or equivalent
     isolated config.
   - Verify the real user's Antigravity/Gemini config is not changed.
   - Verify only the intended Bullpen MCP server is visible to the run.
   - Verify a second run without the temporary config cannot see the probe tool.

   Result: partially passed for local development. A temporary plugin can be
   installed and uninstalled around a run, but the working authenticated path
   uses the real Antigravity profile/keyring and therefore mutates
   `~/.gemini/config/plugins` during the run. This is acceptable for the first
   local adapter implementation only if the adapter installs a uniquely named
   Bullpen runtime plugin, cleans it up reliably, and refuses to proceed if
   cleanup/install fails. It remains insufficient for production deployment.

3. **Can `agy --print` call the real Bullpen MCP server?**

   - Run against the existing [server/mcp_tools.py](../server/mcp_tools.py)
     stdio server.
   - Verify read tools work: `list_tickets`, `list_tasks`,
     `list_tickets_by_title`.
   - Verify write tools work through the running Bullpen Flask/Socket.IO server:
     `create_ticket` and `update_ticket`.
   - Verify browser clients receive normal task events; do not inspect success
     only by reading `.bullpen/tasks`.

   Result: passed for local development. The real Bullpen
   `list_tickets(status="inbox")` path worked via user-run script. The write
   path also passed: the user-run smoke created and updated a disposable ticket
   through `create_ticket` and `update_ticket`, the ticket appeared in the UI,
   and the server-backed CLI later listed it as `done`. Direct `.bullpen/tasks`
   writes remain forbidden.

4. **Can the remaining CLI contract support Bullpen acceptably?**

   - Confirm auth behavior for local, headless, Docker, and Microsandbox runs.
     Do not assume `ANTIGRAVITY_API_KEY` exists until observed or documented.
   - Capture available model names from `agy models` after auth.
   - Confirm whether machine-readable output exists. `agy` 1.0.8 help does not
     list `--output-format`; plain text is acceptable if MCP works, but usage
     accounting must then be empty.
   - Capture auth failure, model-not-found, quota/capacity, timeout, and
     permission-denied outputs for user-facing error classification.
   - Confirm whether `--sandbox` still permits the required MCP workflow.

   Result: sufficient for local runtime use. The known invocation shape is
   `agy --print <prompt> --print-timeout <duration>` with a temporary
   Antigravity plugin installed into the authenticated real profile. Worker and
   live-chat execution both passed. Remaining limitations are no proven
   structured output, no isolated auth path, no container auth path, and limited
   provider-specific failure samples.

Phase 0 final deliverable:

- A short written spike report appended to this document or checked in under
  `tests/fixtures/antigravity/README.md`.
- Redacted command outputs and any generated minimal config/plugin files needed
  for tests.
- Decision: `GO: build local Antigravity adapter`, with deploy/container
  support and production-grade config isolation tracked as follow-up gates.

### Phase 1: Adapter Replacement

Status: implemented for local authenticated runs.

Create [server/agents/antigravity_adapter.py](../server/agents/antigravity_adapter.py)
and remove active Gemini registration.

The adapter should:

- Use provider name `"antigravity"`. Implemented.
- Find `agy` via `BULLPEN_ANTIGRAVITY_PATH`, `PATH`, `~/.local/bin/agy`,
  `/usr/local/bin/agy`, and `/opt/homebrew/bin/agy`; include Windows paths only
  after verifying the installer layout. Implemented for current known local
  paths.
- Build argv from observed flags:
  `agy --print-timeout <timeout> --model <model> --print <prompt>`.
  Implemented.
- Prepare per-run MCP config exactly as proven in Phase 0. Implemented through
  a generated temporary plugin.
- Use `--sandbox` for untrusted/chat paths only if Phase 0 proves MCP still
  works under sandbox restrictions. Deferred; not yet proven.
- Add `--dangerously-skip-permissions` only for trusted worker runs where
  Bullpen intentionally permits autonomous edits. Deferred; not enabled in the
  first slice.
- Treat stdout as plain text unless a real structured stream is confirmed.
  Implemented.
- Preserve stderr and nonzero exits as failure details. Implemented.
- Return empty usage unless Phase 0 proves a token schema. Implemented.

Registry behavior:

- Register `"antigravity"` as the active provider. Implemented.
- Do not register `"gemini"` to any active adapter. Implemented.
- Add a small stale-provider rejection path for `gemini` at worker and live-chat
  entry points. This path reports removal; it does not convert the run.
  Implemented.

### Phase 2: Product Wiring

Status: implemented for the local product surface.

Update user-facing provider metadata:

- Replace `gemini` with `antigravity` in `VALID_AGENTS` and
  `VALID_WORKER_COLOR_KEYS`. Implemented.
- Replace provider colors in backend defaults and frontend defaults.
  Implemented.
- Replace labels with `Antigravity`. Implemented.
- Replace frontend model options with Phase 0-confirmed Antigravity models.
  Implemented from observed `agy models` output.
- Replace live-agent provider tests so they assert Antigravity is present and
  Gemini is absent.
- Keep custom model entry behavior so users can type a newly released
  Antigravity model before Bullpen's static list is updated.

Update model aliases:

- Add only Antigravity-native aliases confirmed in Phase 0. No Antigravity
  aliases are currently needed; the UI uses exact observed model labels.
- Remove active Gemini alias behavior once Gemini is not a supported provider.
  Implemented.

Update provider errors:

- Worker quota/auth/model-not-found classification should use real Antigravity
  stderr/stdout strings captured in Phase 0. Deferred until more real failure
  samples are captured.
- `_observe_provider_failure()` should be provider-aware and must not hard-code
  "Gemini model capacity exhausted."
- Live-agent model errors should say `Antigravity CLI did not accept model ...`.
- Stale Gemini worker/live-chat paths should have focused tests for graceful
  rejection. Implemented.

Update usage:

- Add `extract_antigravity_usage_event()` only if Phase 0 confirms structured
  token output. Not added; no structured token schema is known.
- If `agy` only emits plain text, explicitly return `{}` and keep stats empty.
  Implemented.

### Phase 3: Deploy and Runtime Setup

Status: blocked.

Replace install/auth flows:

- [Dockerfile](../Dockerfile): stop installing `@google/gemini-cli`; install
  `agy` using the verified Antigravity install mechanism.
- [deploy-sprite.sh](../deploy-sprite.sh): replace Gemini install and
  `gemini auth login` with the verified Antigravity setup/auth flow.
- [deploy-docker.sh](../deploy-docker.sh) and
  [docker-compose.yml](../docker-compose.yml): replace Gemini config mounts/env
  forwarding with verified Antigravity config/auth paths.
- [deploy-sandbox.py](../deploy-sandbox.py): forward only verified Antigravity
  auth environment variables.

Do not document or rely on `ANTIGRAVITY_API_KEY` until Phase 0 confirms it. If
OAuth/keyring is the only supported auth path, Docker and Microsandbox setup need
explicit limitations or a documented manual credential bootstrap.

### Phase 4: Remove Gemini Product Surface

Status: implemented for the active product surface. Gemini is no longer
registered, the old Gemini adapter file has been removed, and the remaining
Gemini references are limited to stale-state rejection, historical transition
context, deployment follow-up notes, and Antigravity model display names that
currently contain the word "Gemini".

Remove or retire:

- `server/agents/gemini_adapter.py`. Implemented.
- Gemini model options from `static/utils.js`.
- Gemini provider labels/colors from frontend and backend defaults.
- Gemini-specific deploy instructions.
- Gemini-specific capacity/quota/model messages, except the stale-provider
  removal message. Implemented for active worker/live-chat error paths.
- Gemini usage helpers and tests that assume Gemini remains an active provider.
  Implemented.

Keep only:

- A tiny stale-provider rejection check for worker start and live chat.
- Tests proving stale `agent: gemini` and `provider: gemini` fail clearly and
  do not spawn any provider subprocess.

### Phase 5: Verification

Status: automated verification and manual local runtime smokes passed for the
implemented adapter slice.

Automated checks:

- `python3 -m pytest tests/test_agents.py -q`
- `python3 -m pytest tests/test_workers.py tests/test_events_chat_hardening.py -q`
- `python3 -m pytest tests/test_usage.py tests/test_model_aliases.py -q`
- `python3 -m pytest tests/test_validation.py tests/test_frontend_worker_models.py tests/test_frontend_live_agent_tabs.py -q`
- `python3 -m pytest tests/test_deploy_sandbox.py tests/test_deploy_docker_script.py tests/test_manager.py -q`
- Full suite: `python3 -m pytest tests/ -x -q`

Latest result after removing the inactive Gemini adapter and Gemini usage
helpers: `1172 passed, 1 skipped`.

Manual checks on an authenticated `agy` install:

- New Antigravity worker can complete a ticket. Verified by worker smoke:
  `agy-worker-smoke-20260615-113424-16nS`.
- Antigravity can create and update tickets through Bullpen MCP.
  Verified by write smoke:
  `agy-mcp-write-smoke-20260615-111929-ce9e71-ZasH`.
- Live-agent chat with Antigravity returns text and can use Bullpen MCP.
  Verified by user-run live-chat smoke.
- Stale Gemini worker blocks cleanly without spawning a subprocess.
- Stale live-agent request with `provider: gemini` returns a clear error.
- Focus view shows useful streaming or buffered output.
- Auth failure, missing binary, model-not-found, quota/capacity, permission, and
  timeout errors are user-readable.

## Risks

1. **MCP configuration currently mutates the real Antigravity profile.** The
   local build can manage this with uniquely named temporary plugins and
   best-effort cleanup. Production-quality support still needs a scoped
   config/auth strategy.
2. **Provider-specific failure handling is still thin.** `list_tickets`,
   `create_ticket`, `update_ticket`, worker execution, and live chat passed
   against the real Bullpen server. The next local hardening work is to capture
   real Antigravity outputs for auth failure, invalid model, timeout, and plugin
   failure so Bullpen can show sharper error messages.
3. **Structured output may not exist.** Plain text is acceptable because MCP
   works; Bullpen will lose Gemini-style stream event parsing and token usage
   until Antigravity exposes a machine-readable mode.
4. **Auth may not fit containers.** Local keyring/OAuth flows may not work in
   Docker or Microsandbox without an API-key or service-account path.
5. **Model names are likely to churn.** Keep Antigravity model IDs centralized
   in the frontend model list and `model_aliases.py`.
6. **Permission semantics changed.** Gemini's `--approval-mode yolo` plus
   settings-file MCP allow-list does not map cleanly to `agy`. The adapter must
   use only flags and plugin config that were actually observed.

## Implementation Checklist

- [x] Complete Phase 0 MCP spike.
- [x] Stop and report Phase 0 decision.
- [x] Add `server/agents/antigravity_adapter.py` for local authenticated runs.
- [x] Register `antigravity`; remove active Gemini registration.
- [x] Remove the old Gemini adapter module and active Gemini usage parsing.
- [x] Add stale Gemini rejection for worker and live chat.
- [x] Avoid Antigravity alias compatibility until native aliases are proven
      useful.
- [x] Replace provider validation, colors, labels, dropdowns, and model lists.
- [x] Update worker and live-chat stale-provider error handling.
- [ ] Update runtime hardening for Antigravity trust modes.
- [x] Update usage handling based on real `agy` output.
- [ ] Defer Gemini deploy/install/auth replacement until Antigravity headless
      auth is proven.
- [x] Add tests for Antigravity paths.
- [x] Add tests for stale Gemini graceful rejection.
- [x] Run focused tests and full suite after final cleanup.
- [x] Manually verify MCP read and write tools through `agy --print`.
- [x] Manually verify worker lifecycle through an Antigravity worker smoke.
- [x] Manually verify live chat through an Antigravity chat smoke.
- [ ] Manually verify common failure modes.
