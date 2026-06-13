# OpenCode support

## Objective

Add OpenCode as a first-class Bullpen AI provider everywhere Claude, Codex, and
Gemini are currently supported:

- AI workers and queued ticket execution
- Live Agent Chat
- worker/provider configuration UI
- provider colors and usage reporting
- installation, credential, Docker, and Microsandbox setup
- model selection and validation
- MCP ticket-tool access

The goal is provider parity, not a separate OpenCode-specific workflow. A user
who already understands Bullpen workers should be able to pick "OpenCode",
choose a model, assign a ticket, watch output stream, and get the same ticket
lifecycle behavior they get from the existing AI providers.

## Context reviewed

- Current Bullpen provider surface: `claude`, `codex`, and `gemini`
- Existing adapter contract in `server/agents/base.py`
- Current provider registry in `server/agents/__init__.py`
- Current model and color definitions in `static/utils.js`
- Current worker config and Live Agent provider selectors
- Current provider-color config validation in `server/validation.py`
- Existing deeper draft in `docs/opencode-proposal.md`
- OpenCode docs as of June 12, 2026:
  - install package is `opencode-ai`
  - non-interactive execution is `opencode run`
  - `opencode run --format json` emits raw JSON events
  - model strings use `provider/model`
  - `opencode models [provider] --refresh` refreshes the model cache
  - auth can be configured with `opencode auth login`, env vars, project
    `.env`, or `~/.local/share/opencode/auth.json`
  - local MCP servers are configured under the OpenCode config `mcp` key

## Assumptions

- Bullpen should treat OpenCode as another process-backed coding-agent CLI, not
  as a direct API integration.
- OpenCode should run per ticket/session like existing Bullpen adapters. A
  persistent `opencode serve` process may be an optimization later, but is not
  required for the first implementation.
- Bullpen should not attempt to own or broker every upstream model provider's
  credentials. It should preserve and pass through the user's existing OpenCode
  auth state and supported environment variables.
- OpenCode's JSON event schema should be treated as external and versioned by
  tests/fixtures, with graceful fallback for unknown events.

## Functional requirements

### 1. Provider availability and setup

- Bullpen must recognize `opencode` as an AI provider.
- Bullpen must detect the executable from:
  - `BULLPEN_OPENCODE_PATH`, if set and executable
  - `PATH`
  - common platform install locations where appropriate
- If unavailable, Bullpen must show a provider-specific setup message that
  mentions installing OpenCode and setting `BULLPEN_OPENCODE_PATH`.
- README/setup documentation must include OpenCode alongside Claude, Codex, and
  Gemini.
- Bullpen Manager credential/setup UI must include OpenCode where provider
  setup is listed today.
- Docker and Microsandbox images should install the OpenCode CLI.
- Microsandbox runtime env forwarding must include the OpenCode path and the
  auth/config environment variables Bullpen intends to support.

### 2. Authentication and credential handling

- Bullpen must support OpenCode auth without storing OpenCode secrets in
  Bullpen ticket files or workspace config.
- Bullpen must preserve these auth paths:
  - OpenCode's own auth file, `~/.local/share/opencode/auth.json`
  - OpenCode config path variables such as `OPENCODE_CONFIG`,
    `OPENCODE_CONFIG_DIR`, and `OPENCODE_CONFIG_CONTENT`
  - provider API keys already present in the Bullpen process environment or
    project `.env`
- The adapter must pass through commonly used provider env vars needed by
  OpenCode, including OpenAI, Anthropic, Google, OpenRouter, and local/provider
  gateway variables where the project already exposes them.
- Microsandbox and Docker docs must explain whether users should rely on env
  vars, mounted OpenCode auth state, or an interactive `opencode auth login`.
- Logs, focus output, and error messages must not echo secret values.

### 3. Worker configuration UI

- The worker provider selector must include "OpenCode".
- OpenCode workers must support the same configurable fields as other AI
  workers unless a field is explicitly unsupported.
- Provider colors must include an OpenCode default in both backend workspace
  defaults and frontend defaults.
- Use a distinct OpenCode default color in all color sources. Proposed default:
  `#63b3ed`, matching the existing draft and staying visually distinct from
  Claude `#da7756`, Codex `#5b6fd6`, and Gemini `#3c7bf4`.
- The provider color menu must include OpenCode.
- Existing saved worker configs with `agent: "opencode"` must round-trip
  without falling back to another provider.
- Model field validation must allow realistic `provider/model` strings.
  `server/validation.py` currently caps worker `model` at 50 characters, which
  is too short for triple-segment OpenCode IDs such as
  `openrouter/meta-llama/llama-3.1-405b-instruct`. Raise the cap to at least
  128 characters and cover it with validation tests.
- Add `opencode` to every server-side and frontend provider enumeration, not
  only the visible worker dropdown. This includes worker field validation,
  provider color validation, worker normalization/default handling, Live Agent
  provider lists, and setup/manager allowlists.

### 4. Model selection

- OpenCode model values must be passed through as `provider/model` strings.
- OpenCode will initially be the first catalog-backed model selector while
  Claude, Codex, and Gemini continue using existing static options. The UI must
  make that provider-specific difference feel intentional and contained, and
  Phase 5 should evaluate reusing the catalog picker pattern for the other
  providers.
- The selector must avoid both a hand-curated model list and a flat 300+ item
  dropdown. A hand-curated list creates unclear provenance, constant
  maintenance work, and hides the model space users specifically want to
  explore.
- The MVP model UI should be catalog-backed:
  - backend endpoint shells out to `opencode models`
  - results are parsed into `provider` and `model` parts from `provider/model`
  - frontend shows a compact provider/vendor selector first
  - frontend then shows a searchable model selector scoped to that provider
  - a "Custom" path always allows manual `provider/model` entry
- The worker config modal should keep the common path compact. If the catalog
  is too large for the existing form, use a model-picker modal opened from the
  model field rather than embedding a giant dropdown inline.
- Catalog results should be cached per workspace with a short TTL so opening the
  worker modal does not repeatedly launch OpenCode.
- Users must be able to explicitly refresh the catalog using
  `opencode models --refresh`.
- Users must be able to type arbitrary OpenCode model IDs, including local,
  OpenRouter, OpenCode Zen, and custom-provider models.
- Backend model normalization must not rewrite unknown OpenCode model IDs.
- Catalog errors from missing auth, unavailable providers, or model-cache
  refresh failures must be shown as setup hints, not hard failures when a custom
  model is typed.

### 5. AI worker execution

- Bullpen must implement an `OpenCodeAdapter` under `server/agents/`.
- The adapter must implement the existing `AgentAdapter` contract:
  - `name`
  - `available`
  - `unavailable_message`
  - `build_argv`
  - `prompt_via_stdin`
  - `prepare_env`
  - `finalize_env`, if needed
  - `format_stream_line`
  - `parse_output`
- Optional base methods such as `unavailable_message` and `finalize_env` should
  only be overridden when OpenCode needs provider-specific behavior.
- Phase 0 must confirm whether OpenCode accepts prompt text through stdin in
  Bullpen's shared runner. If it does, keep `prompt_via_stdin()` on the default
  `True` path; if not, pass the prompt as `opencode run` message args and
  return `False`.
- Worker execution must invoke OpenCode in non-interactive mode with JSON
  output enabled.
- Execution must happen in the ticket workspace/worktree directory, not in
  Bullpen's app directory.
- The full Bullpen task prompt, including workspace context and profile
  expertise, must reach OpenCode exactly once.
- Cancellation, retries, queue handling, completion dispositions, auto-commit,
  auto-PR, and worktree cleanup must behave the same as existing AI workers.
- Provider/model metadata must be recorded on the task usage/history records.

### 6. Permissions and trust model

- OpenCode must obey Bullpen's trust-mode setting, but implementation must not
  assume a uniform existing hardening path. Today `harden_agent_argv()` applies
  argv-level hardening only for Claude; Codex and Gemini use provider-specific
  execution flags instead.
- Choose and document one OpenCode runtime hardening design before adapter
  implementation:
  - add an explicit `opencode` branch to `harden_agent_argv()`, or
  - self-gate in `OpenCodeAdapter.build_argv()` using Bullpen trust/runtime
    configuration, similar in spirit to Codex's sandbox flag selection.
- Auto-approval flags such as `--dangerously-skip-permissions` must not be
  added unconditionally. In trusted mode they may be enabled if needed for
  headless operation. In untrusted mode, Bullpen must either omit/restrict them
  with provider-supported permission controls or fail with a clear message if
  OpenCode cannot run safely without them.
- The implementation plan must include tests for OpenCode trust-mode argv
  behavior, including the untrusted path.
- OpenCode config generated by Bullpen must avoid enabling unrelated tools or
  MCP servers.

### 7. MCP ticket tools

- OpenCode workers should receive Bullpen MCP access equivalent to existing AI
  providers.
- Reuse the existing Claude MCP config pattern where practical: generate a
  per-run config pointing at `server/mcp_tools.py`, pass it to OpenCode through
  OpenCode-supported config mechanisms, and avoid mutating user/project config.
- The generated OpenCode config must define a local MCP server named `bullpen`
  that runs `server/mcp_tools.py` with the active `.bullpen` directory, host,
  and port.
- The MCP server must be launched directly without a shell wrapper or any
  command that can print stray stdout before the JSON-RPC stdio protocol starts.
- Only the intended Bullpen MCP tools should be exposed initially:
  - list tickets/tasks
  - search/list tickets by title
  - create ticket
  - update ticket
- The MCP config must be per run or otherwise isolated so it does not overwrite
  user project config.
- MCP startup/config errors must be visible in worker logs.

### 8. Streaming and focus view

- OpenCode JSON output must stream into Worker Focus Mode in near real time.
- Assistant text, tool calls, tool results, and errors must map to readable
  focus-view lines.
- Result/final metadata events must not be duplicated as assistant text.
- Unknown JSON event shapes must be ignored or displayed safely without
  crashing the worker.
- Very large tool outputs must be truncated for focus display while preserving
  the raw process output for final parsing where practical.
- Non-JSON lines must be displayed or retained as diagnostic output.

### 9. Output parsing and ticket lifecycle

- `parse_output` must classify successful runs, model/provider/auth failures,
  permission failures, malformed JSON, and non-zero exits.
- Final assistant output must be written to the ticket history in the same
  style as existing AI providers.
- Failures must move through Bullpen's existing retry/error path and must
  include actionable error text.
- If OpenCode emits token usage, Bullpen must normalize it into canonical
  usage fields:
  - `input_tokens`
  - `cached_input_tokens`
  - `output_tokens`
  - `reasoning_output_tokens`
  - `total_tokens`
- If token usage is unavailable, Bullpen must still record provider/model and
  task timing without fabricating token counts.

### 10. Live Agent Chat

- The Live Agent provider list must include OpenCode.
- A chat tab using OpenCode must support:
  - provider/model selection
  - custom model entry
  - streaming response output
  - stop/cancel
  - conversation logging to tickets
- Session semantics need an implementation choice:
  - MVP can run each Live Agent turn as a fresh `opencode run` with assembled
    conversation context if that matches current Live Agent architecture.
  - A later enhancement can use `--continue`, `--session`, or `opencode serve`
    if that materially improves continuity or startup cost.
- The UI must not imply persistent OpenCode session reuse unless it is actually
  implemented.

### 11. Deployment and runtime environments

- Docker image build must install OpenCode using the current supported package
  name or install script.
- Docker compose/run docs must document optional mounts for OpenCode auth and
  config directories.
- Microsandbox base image setup must install OpenCode once in the base snapshot
  when possible.
- Microsandbox auth/first-light commands should include OpenCode:
  - verify binary availability
  - verify at least one configured model can complete a small JSON run
  - report missing auth distinctly from missing binary
- Cross-platform behavior must be checked for macOS, Linux, and Windows/WSL.

### 12. Observability and diagnostics

- Worker logs must include the provider name, model, selected executable path,
  and high-level phase, without printing secrets.
- Setup failures should be classified clearly:
  - binary missing
  - auth/provider missing
  - model not found or unavailable
  - permission denied
  - malformed/unsupported OpenCode output
  - process timeout/cancelled
- Existing stats views must include OpenCode as another provider bucket.
- Model catalog refresh diagnostics should show cache age and refresh errors
  if the catalog endpoint is implemented.

### 13. Backward compatibility

- Existing Claude, Codex, Gemini, shell, service, and marker behavior must not
  change.
- Existing saved workspace configs with provider colors must continue to load.
- Existing tickets and workers must not require migration.
- Unknown provider/model values should continue to fail gracefully rather than
  breaking workspace load.

### 14. Testing requirements

- Unit tests for `OpenCodeAdapter`:
  - executable discovery and unavailable message
  - argv construction
  - prompt routing
  - env/config generation
  - stream event formatting
  - output parsing for success, failure, malformed JSON, and non-zero exit
  - usage extraction
- Registry tests proving `get_adapter("opencode")` works.
- Trust hardening tests proving OpenCode trusted/untrusted argv behavior is
  implemented deliberately and does not accidentally inherit Claude-only
  assumptions.
- Backward-compat test: a saved worker config with `agent: "opencode"` loads
  without the server allowlist rejecting it.
- Model alias/normalization tests proving OpenCode model IDs pass through.
- Validation tests for longer `provider/model` strings.
- Frontend/static tests for:
  - worker config provider option
  - Live Agent provider option
  - model options/custom model behavior
  - provider color defaults/menu rows
- Worker lifecycle tests with a fake OpenCode executable.
- Manual smoke checklist:
  - install/auth check
  - create OpenCode worker
  - assign simple ticket
  - observe focus streaming
  - verify ticket completion/history/usage
  - run one Live Agent OpenCode chat
  - run in Docker or Microsandbox if included in the release scope

## Non-goals for the first cut

- Building a native OpenRouter/OpenAI-compatible API coding loop in Bullpen.
- Maintaining a bundled, always-current copy of every OpenCode model.
- Managing upstream provider billing, plan limits, or account setup beyond
  clear user-facing setup guidance.
- Replacing existing Claude, Codex, or Gemini adapters with OpenCode.
- Running a shared long-lived OpenCode server unless later benchmarks show it
  is necessary.

## Detailed implementation plan

Each phase below is sized to end in a reviewable commit. Do not roll phases
together unless a phase produces no code changes after investigation. At every
phase boundary:

- run the listed verification commands
- update this plan's open items and phase status
- commit the completed work
- pause for a plan checkpoint before starting the next phase

Phase status:

| Phase | Status | Checkpoint |
|-------|--------|------------|
| 0. Contract spike and fixtures | Complete | Contract captured in `docs/opencode-contract.md` |
| 1. Backend adapter and provider registration | Not started | Commit after adapter tests pass |
| 2. Model catalog backend API | Blocked on Phase 1 | Commit after catalog API tests pass |
| 3. Worker configuration UI | Blocked on Phase 2 | Commit after UI/manual picker check |
| 4. Worker lifecycle integration and smoke test | Blocked on Phase 3 | Commit after fake lifecycle and local smoke |
| 5. Live Agent Chat support | Blocked on Phase 4 | Commit after chat tests/manual check |
| 6. Setup, manager, Docker, and Microsandbox | Blocked on Phase 5 | Commit after setup/deploy checks |
| 7. Hardening, docs, and release readiness | Blocked on Phase 6 | Commit after release-readiness review |

### Phase 0 - Contract spike and fixtures

Goal: turn the unknown OpenCode CLI behavior into fixtures and documented
adapter decisions before product code depends on it.

Files likely touched:

- `docs/opencode.md`
- `tests/fixtures/opencode/`
- optionally `docs/opencode-contract.md` if fixture notes become too large for
  this file

Work:

- Record the installed OpenCode path and version from the dev environment.
- Probe prompt transport:
  - `opencode run --format json` with prompt as message args
  - `opencode run --format json` with prompt on stdin
  - confirm which mode produces exactly one user turn and no prompt echo issues
- Capture JSONL fixtures for:
  - successful text-only answer
  - tool call and tool result
  - final result/usage event
  - model-not-found failure
  - auth/provider failure, if reproducible without damaging local auth
  - permission failure, if reproducible
- Capture model catalog fixtures:
  - `opencode models`
  - `opencode models --refresh`
  - one provider-filtered catalog, if available
  - `opencode models --verbose`, to decide whether metadata is stable enough
    for later UI use
- Confirm OpenCode config injection for a local MCP server:
  - file path via `OPENCODE_CONFIG`
  - inline content via `OPENCODE_CONFIG_CONTENT`, if suitable
  - config-dir isolation via `OPENCODE_CONFIG_DIR`, if needed
- Decide the first implementation's trust-mode strategy:
  - preferred: add an explicit `opencode` branch to `harden_agent_argv()` if
    permission flags can be cleanly modified after `build_argv()`
  - fallback: make `OpenCodeAdapter.build_argv()` trust-aware only if the
    shared adapter contract is extended deliberately
- Decide the first Live Agent session strategy:
  - default to fresh `opencode run` turns using Bullpen's assembled chat prompt
  - defer `--continue`, `--session`, or `opencode serve` unless the spike shows
    they are necessary

Verification:

- Fixture files are present and small enough to review.
- The contract notes state:
  - prompt transport choice
  - JSON event types Bullpen will parse
  - model catalog output shape
  - MCP config injection mechanism
  - trust-mode flag behavior

Phase-end checkpoint:

- Completed with OpenCode `1.17.3` at `/Users/bill/.opencode/bin/opencode`.
- Contract notes and sanitized fixtures were added.
- Prompt transport, text/error JSON shapes, model catalog shape, MCP config
  injection approach, trust-mode strategy, and Live Agent session strategy are
  pinned down.
- Tool-call event shape remains a manual follow-up because the automated probe
  would require an external model to run local shell commands with
  `--dangerously-skip-permissions` outside the workspace sandbox.

Commit:

- Suggested message: `docs(opencode): capture cli integration contract`

### Phase 1 - Backend adapter and provider registration

Goal: make `opencode` a registered backend provider that can be unit-tested
without touching the UI.

Files likely touched:

- `server/agents/opencode_adapter.py`
- `server/agents/__init__.py`
- `server/model_aliases.py`
- `server/usage.py`
- `server/prompt_hardening.py`
- `server/validation.py`
- `server/init.py`
- `tests/test_agents.py`
- `tests/test_usage.py`
- `tests/test_validation.py`
- prompt-hardening tests, either existing or new

Work:

- Add `OpenCodeAdapter` with:
  - binary discovery via `BULLPEN_OPENCODE_PATH`, `PATH`, and common install
    paths
  - provider-specific unavailable message
  - argv construction from the Phase 0 prompt-transport decision
  - per-run temp/config isolation
  - per-run MCP config generation for the Bullpen stdio MCP server
  - JSON stream formatting for focus/chat display
  - final output parsing for success, errors, and usage
- Register the adapter in `server/agents/__init__.py`.
- Add `opencode` model normalization as pass-through.
- Normalize usage from OpenCode fixtures into Bullpen token fields.
- Implement the Phase 0 trust-mode strategy.
- Add `opencode` to server-side provider/color allowlists.
- Raise worker `model` validation length to at least 128 characters.
- Add the `#63b3ed` backend provider color default.
- Extend non-retryable provider error classification for obvious OpenCode auth
  and model failures if fixtures make them reliable.

Verification:

- `pytest tests/test_agents.py`
- `pytest tests/test_usage.py`
- `pytest tests/test_validation.py`
- prompt-hardening test file once identified or added
- targeted worker lifecycle fake-executable test if it already exists in a
  suitable place

Phase-end checkpoint:

- Confirm the adapter can be resolved with `get_adapter("opencode")`.
- Confirm long model IDs and `agent: "opencode"` are accepted server-side.
- Confirm trusted and untrusted argv behavior matches the Phase 0 decision.
- Update the plan with any adapter limitations found during tests.

Commit:

- Suggested message: `feat(opencode): add backend adapter`

### Phase 2 - Model catalog backend API

Goal: provide a cacheable server-backed OpenCode model catalog before building
the UI picker.

Files likely touched:

- new `server/opencode_models.py` or `server/model_catalog.py`
- `server/app.py` or the relevant route registration module
- possibly `server/events.py` only if the existing app favors Socket.IO for
  this kind of data
- tests for the catalog helper and route

Work:

- Add a backend helper that shells out to the configured `opencode` binary for:
  - `opencode models`
  - `opencode models --refresh`
  - optional provider filtering, if Phase 0 confirms the CLI supports it
- Parse model lines into records:
  - `id`: full `provider/model`
  - `provider`: prefix before first slash
  - `model`: remainder after first slash
  - optional metadata from verbose output only if stable
- Cache catalog results per workspace and executable/config context with a
  short TTL.
- Add an explicit refresh path that bypasses the cache.
- Return structured non-fatal setup states:
  - binary missing
  - auth/provider unavailable
  - refresh failed
  - no models returned
- Ensure custom model entry remains possible even when the catalog endpoint
  returns an error.

Verification:

- catalog helper unit tests with Phase 0 fixtures
- route tests for cache hit, refresh, parse failure, binary missing, and
  auth/model-list failure
- targeted regression that no external network call is made by tests

Phase-end checkpoint:

- Confirm API shape with a sample response in this doc or adjacent fixture.
- Confirm frontend can build provider-first picker from the response without
  extra server calls per provider.
- Update open items around catalog behavior.

Commit:

- Suggested message: `feat(opencode): add model catalog endpoint`

### Phase 3 - Worker configuration UI

Goal: let users create and edit OpenCode workers, including provider-first
model selection, without disturbing existing provider workflows.

Files likely touched:

- `static/utils.js`
- `static/components/WorkerConfigModal.js`
- `static/components/TopToolbar.js`
- `static/style.css`
- frontend/static tests
- possibly a new model-picker component under `static/components/`

Work:

- Add OpenCode to frontend provider lists and labels.
- Add OpenCode to `DEFAULT_AGENT_COLORS` and provider color menu rows.
- Replace the OpenCode model select path with a catalog-backed picker:
  - provider/vendor selector
  - searchable scoped model selector
  - refresh action
  - custom `provider/model` entry
  - setup/error hint when catalog load fails
- Keep Claude/Codex/Gemini on the existing static model selector for this
  phase.
- Preserve saved worker round-tripping, including custom OpenCode model IDs.
- Ensure the worker card, roster, minimap, and color menu render the OpenCode
  color.
- Keep layout stable on narrow screens; use a modal picker if the inline form
  becomes cramped.

Verification:

- frontend/static tests covering:
  - provider option present
  - model picker states: loading, catalog success, catalog error, custom entry
  - provider color default and menu row
  - save payload with long custom model
- browser/manual check:
  - open worker config
  - choose OpenCode
  - select catalog model
  - type custom model
  - save/reopen worker

Phase-end checkpoint:

- Capture a short UI note in this doc if the picker uses a modal or inline
  layout.
- Confirm no regressions to Claude/Codex/Gemini model selection.

Commit:

- Suggested message: `feat(opencode): add worker configuration UI`

### Phase 4 - Worker lifecycle integration and smoke test

Goal: prove an OpenCode worker can execute a Bullpen ticket through the normal
queue lifecycle.

Files likely touched:

- `server/workers.py`, if provider-specific failure handling needs adjustment
- worker lifecycle tests
- fake OpenCode executable fixture/script under tests
- release/manual smoke checklist docs, if not already present

Work:

- Add or extend fake-executable lifecycle tests so OpenCode can:
  - start from an assigned ticket
  - stream focus output
  - produce final assistant output
  - record provider/model usage metadata
  - fail non-retryably on missing auth/model where classified
  - cancel cleanly
- Verify MCP config is generated with the active workspace `.bullpen` host and
  port.
- Verify temp/config directories are cleaned up.
- Run a local manual smoke with the installed OpenCode:
  - create OpenCode worker
  - assign a small ticket
  - watch focus streaming
  - verify ticket history and usage
  - verify trust-mode behavior selected in Phase 0

Verification:

- worker lifecycle pytest targets
- `pytest tests/test_agents.py tests/test_validation.py`
- manual smoke checklist result recorded in this doc or a release checklist

Phase-end checkpoint:

- Decide whether worker support is ready to ship behind normal UI, or whether
  it needs a temporary "experimental" note.
- Close worker-path open items or move them to hardening.

Commit:

- Suggested message: `test(opencode): verify worker lifecycle`

### Phase 5 - Live Agent Chat support

Goal: add OpenCode to direct chat after the worker path is stable.

Files likely touched:

- `static/components/LiveAgentChatTab.js`
- shared model picker component from Phase 3, if extracted
- `server/events.py`
- chat tests

Work:

- Add OpenCode to Live Agent provider options.
- Reuse the OpenCode catalog picker or a compact variant of it for chat model
  selection.
- Reuse adapter stream parsing and output parsing in chat.
- Apply chat hardening through the Phase 0/Phase 1 trust-mode strategy.
- Preserve existing in-memory Bullpen chat-session assembly unless Phase 0
  selected OpenCode-native sessions.
- Ensure stop/cancel, errors, and chat-to-ticket logging work.
- Record provider/model usage on chat-created tickets.

Verification:

- chat provider/model tests
- fake streamed OpenCode chat output test
- manual browser check:
  - open Live Agent
  - choose OpenCode
  - send prompt
  - stop a run
  - verify chat ticket logging

Phase-end checkpoint:

- Decide whether OpenCode chat is included in the same release note as workers
  or called out as separately validated.
- Update open item for Live Agent session strategy.

Commit:

- Suggested message: `feat(opencode): support live agent chat`

### Phase 6 - Setup, manager, Docker, and Microsandbox

Goal: make OpenCode install/auth visible and runnable in packaged deployment
paths.

Files likely touched:

- `README.md`
- `docs/docker.md`
- `Dockerfile`
- `docker-compose.yml`
- `deploy-sandbox.py`
- `server/manager.py`
- `static/manager/manager.js`
- deployment tests, if present

Work:

- Update README provider prerequisites and environment path list with
  `BULLPEN_OPENCODE_PATH`.
- Add OpenCode install to Docker image build using the package name confirmed
  in Phase 0.
- Document optional Docker mounts for:
  - `~/.local/share/opencode`
  - OpenCode config directories
  - provider env vars
- Add OpenCode to Microsandbox:
  - base snapshot install
  - runtime env (`BULLPEN_OPENCODE_PATH`)
  - forwarded auth/config env vars
  - `auth` command target
  - `test-provider` target
  - first-light target, if quick enough and reliable
- Add OpenCode to Bullpen Manager provider labels and setup/auth display.
- Preserve clear messaging that OpenCode auth may be API-key/config based, not
  necessarily an OAuth login like Claude/Codex.

Verification:

- targeted tests for manager provider display, if present
- `python3 deploy-sandbox.py --help` and subcommand help checks
- Dockerfile syntax/build smoke if available locally
- Microsandbox command dry-run/help checks if full sandbox is not run

Phase-end checkpoint:

- Decide whether Docker and Microsandbox validation is complete or needs a
  release-blocking manual run.
- Update deployment limitations and open items.

Commit:

- Suggested message: `chore(opencode): wire setup and deployment`

### Phase 7 - Hardening, docs, and release readiness

Goal: make the integration boring enough to release.

Files likely touched:

- `docs/opencode.md`
- README/troubleshooting docs
- tests added in earlier phases
- any small fixes uncovered by manual testing

Work:

- Expand failure classification based on real local runs.
- Add redaction tests for env/config paths and sensitive output where practical.
- Verify no orphan OpenCode process remains after worker/chat cancellation.
- Verify cleanup of temp dirs and generated config files.
- Run a focused regression suite across touched surfaces.
- Run manual smoke checks on:
  - local macOS/dev environment
  - Docker, if Docker support is included in the release
  - Microsandbox, if Microsandbox support is included in the release
  - Windows/WSL, if available
- Update docs with:
  - setup instructions
  - known limitations
  - model picker behavior
  - troubleshooting matrix
- Remove or resolve all remaining open items, or explicitly move them to a
  post-release section.

Verification:

- `pytest` target set agreed at Phase 7 start
- browser check for worker config and Live Agent
- manual smoke checklist results recorded

Phase-end checkpoint:

- Confirm release readiness:
  - worker path validated
  - chat path validated or explicitly deferred
  - setup/deployment path validated or explicitly scoped out
  - no unresolved blocker open items

Commit:

- Suggested message: `docs(opencode): finalize release readiness`

## Open items

- Capture real tool-call and tool-result JSON event shapes manually, with
  explicit human approval, if richer focus-view rendering is required before
  release. The adapter should gracefully ignore or summarize unknown event types
  until then.
- Add fake-executable auth failure fixtures unless a safe real missing-auth
  probe becomes available.
- Decide the complete env/auth pass-through set for Docker and Microsandbox
  during Phase 6 setup work.

## Review comments not adopted

- None. The review's substantive comments were accepted and incorporated into
  the requirements, test plan, or phase gates. Pure affirmation comments were
  removed rather than preserved as requirements.
