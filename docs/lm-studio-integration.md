# LM Studio Integration Feature Specification

Status: Proposed  
Audience: Bullpen maintainers and implementers  
Last reviewed: 2026-10-12

## 1. Executive Summary

Bullpen should integrate LM Studio as a model backend for an existing coding-agent harness, not as a new autonomous agent harness of its own.

The first supported execution path should be:

```text
Bullpen worker
  -> Codex CLI agent harness
    -> LM Studio-compatible local model server
      -> selected local model
```

Codex supplies the agent loop, workspace tools, shell execution, sandbox behavior, structured event stream, and Bullpen MCP connection. LM Studio supplies inference through its OpenAI-compatible Responses API. This preserves Bullpen's current subprocess architecture and avoids implementing a second coding-agent runtime inside Bullpen.

The literal LM Studio one-shot command, `lms chat <model> -p <prompt>`, is not the primary integration. It returns model output but does not provide the coding tools and multi-step agent behavior Bullpen workers require.

LM Studio Bionic is also not a Bullpen-driven harness in this version. Bionic exposes model inference APIs, but its public documentation does not expose an API or headless CLI for creating Bionic projects, starting Bionic sessions, submitting turns to the Bionic agent, handling approvals, or collecting session results. Bullpen must not automate Bionic's UI, Electron internals, private IPC, or undocumented deep links.

The feature introduces an explicit model-backend dimension while keeping the existing agent field intact:

```json
{
  "agent": "codex",
  "model_backend": "lmstudio",
  "model": "openai/gpt-oss-20b"
}
```

Existing workers remain backward compatible: a missing `model_backend` means `native`.

## 2. Goals

The feature must:

- Let a user select LM Studio as the model backend for a Codex worker or live agent chat.
- Discover locally available LM Studio models dynamically.
- Display model capability and load-state information useful for agent selection.
- Reuse Bullpen's current Codex subprocess execution, streaming, cancellation, sandbox, MCP, usage, retry, and lifecycle behavior.
- Keep model discovery read-only and free of model-loading side effects.
- Preserve existing worker and profile data without migration requirements.
- Work with either the LM Studio desktop server or `llmster` where the execution topology is supported.
- Produce clear diagnostics when LM Studio, Codex, the selected model, or the configured endpoint is unavailable.
- Avoid exposing LM Studio API credentials to the browser or persisted workspace files.
- Establish an architecture that can later support Ollama or another local model server without adding each server as a fake agent harness.

## 3. Non-Goals

The first version will not:

- Drive Bionic projects or sessions.
- Use `lms chat` as an autonomous coding worker.
- Build a Bullpen-owned shell/file/tool agent loop around `/api/v1/chat` or `/v1/responses`.
- Download models from Bullpen.
- Automatically start, stop, upgrade, or reconfigure LM Studio or `llmster`.
- Automatically load a model during discovery.
- Expose embedding or decision models as worker choices.
- Guarantee that every model marked as tool-trained behaves reliably as a coding agent.
- Add LM Studio cloud billing, account management, or Bionic cloud-model discovery.
- Support undocumented Bionic APIs or private application state.
- Change existing Claude, Codex, Antigravity, or OpenCode behavior when `model_backend` is absent or `native`.

## 4. Current Bullpen Architecture

Bullpen currently treats an agent as a local executable. `AgentAdapter` builds argv, prepares an environment, formats streaming lines, and parses final subprocess output. `server/workers.py` and live Agent Chat launch the executable in the selected workspace and stream its stdout and stderr.

The built-in adapters are registered by agent name:

- `antigravity`
- `claude`
- `codex`
- `opencode`

The worker schema and frontend currently conflate three concepts:

1. Agent harness: the program that plans and uses tools.
2. Model backend: the service that performs inference.
3. Model: the selected model identifier.

That conflation is tolerable when Claude always talks to Anthropic and Codex always uses its default OpenAI backend. It becomes incorrect when Codex can use LM Studio or Ollama. Adding `lmstudio` directly to `VALID_AGENTS` would make the UI simple but would encode the wrong abstraction and duplicate Codex behavior.

Current model discovery is provider-specific and request-correlated over Socket.IO:

| Agent | Discovery source | Cache policy |
| --- | --- | --- |
| Claude | OpenRouter public catalog translated to Claude slugs | One hour, single-flight, stale-last-good fallback |
| Codex | `codex debug models`, then bundled CLI catalog | Five minutes |
| OpenCode | `opencode models` | Five minutes |
| Antigravity | Static built-in options | None |

The browser sends `models:<agent>` with `workspaceId`, `request_id`, and an optional `refresh` flag. The server replies with `models:<agent>:listed` or an error event. LM Studio should initially follow this transport convention while using a shared backend-oriented service internally.

## 5. Product Model

### 5.1 Terminology

- **Agent harness**: Codex, Claude Code, OpenCode, or Antigravity. It owns planning, tool calls, and task execution.
- **Model backend**: The inference service used by the harness. Initial values are `native` and `lmstudio`.
- **Model**: A stable backend-specific identifier, such as `openai/gpt-oss-20b`.
- **LM Studio server**: Either the desktop application's server or the `llmster` headless service.
- **Bionic**: LM Studio's interactive agent application. It is not the execution target of this feature.

### 5.2 Supported Matrix

V1 supports only the following matrix:

| Agent | Model backend | Supported |
| --- | --- | --- |
| Codex | `native` | Existing behavior |
| Codex | `lmstudio` | New behavior |
| Claude | `native` | Existing behavior |
| Claude | `lmstudio` | Deferred |
| OpenCode | `native` | Existing behavior |
| OpenCode | `lmstudio` | Deferred; OpenCode can be configured separately today |
| Antigravity | `native` | Existing behavior |
| Antigravity | `lmstudio` | Unsupported |

The UI must not offer unsupported combinations. Server validation must reject them even if a client submits them manually.

### 5.3 Worker Identity and Display

An LM Studio-backed worker remains a Codex worker for behavior, styling, safety, and usage attribution. The UI should distinguish it without inventing a new agent identity:

```text
Codex · LM Studio
openai/gpt-oss-20b
```

Provider colors remain keyed by the agent harness. A secondary backend badge or label may identify LM Studio. V1 does not add `lmstudio` to `provider_colors`.

## 6. User Experience

### 6.1 Worker Configuration

When the worker type is AI, the configuration modal should contain:

1. Agent: existing selector.
2. Model source: shown for agents that support multiple backends.
3. Model: dynamic selector appropriate to the selected source.
4. Capability summary or warning for the selected model.

For Codex:

```text
Agent          Codex
Model source   OpenAI / LM Studio
Model          GPT-OSS 20B
Status         Downloaded · loaded · tool use · 131K maximum context
```

Selecting `OpenAI` maps to `model_backend: native`. Selecting `LM Studio` maps to `model_backend: lmstudio` and triggers LM Studio discovery.

### 6.2 Model Picker

The LM Studio picker should:

- List LLMs only.
- Lead with tool-trained models that have adequate context.
- Show loaded state.
- Show model size, quantization, format, and maximum context when available.
- Show the configured context of a loaded instance when available.
- Indicate vision and reasoning support.
- Warn rather than prohibit when a model lacks advertised tool training or has a small context window.
- Retain a free-form model entry path for identifiers omitted by the catalog.
- Preserve the user's currently configured model even when the server is offline or the model no longer appears in discovery.

Suggested grouping:

```text
Recommended for agents
  GPT-OSS 20B                    Loaded · tools · 131K
  Qwen Coder ...                 Downloaded · tools · 64K

Other language models
  Small Instruct ...             Downloaded · no tool metadata · 8K
```

### 6.3 Live Agent Chat

Live Agent Chat should expose the same Agent, Model source, and Model controls as the worker modal. A chat configured with `codex + lmstudio` uses the existing Codex chat execution path and remains independently cancellable.

### 6.4 Errors

User-facing errors must distinguish:

- Codex CLI missing.
- LM Studio server unreachable.
- LM Studio authentication required or rejected.
- Model catalog malformed.
- Selected model absent.
- Model load failed, including insufficient memory.
- Model does not successfully perform tool calls.
- Context limit is too small.
- Request timed out.
- Endpoint topology is unsupported, such as an unreachable host server from Docker.

Errors must not expose API tokens, authorization headers, raw credential paths, or unbounded upstream response bodies.

## 7. Persistent Data Model

### 7.1 Worker Fields

Add an optional `model_backend` field to AI workers:

```json
{
  "type": "ai",
  "agent": "codex",
  "model_backend": "lmstudio",
  "model": "openai/gpt-oss-20b"
}
```

Rules:

- Missing, null, or empty `model_backend` normalizes to `native`.
- `native` is not required to be persisted for existing workers.
- `model_backend` is allowed only on AI workers.
- V1 allows `lmstudio` only when `agent == "codex"`.
- `model` remains an opaque string with length and control-character validation.
- A catalog miss does not invalidate an already saved worker; execution will provide the authoritative failure.

### 7.2 Profiles

Add optional `default_model_backend` to profiles:

```json
{
  "default_agent": "codex",
  "default_model_backend": "lmstudio",
  "default_model": "openai/gpt-oss-20b"
}
```

Missing `default_model_backend` means `native`. Built-in profiles remain unchanged. Saving a custom LM Studio-backed profile must persist all three fields.

### 7.3 Last Selection

The current preferred selection stores agent and model. Extend it to include the optional backend:

```json
{
  "agent": "codex",
  "model_backend": "lmstudio",
  "model": "openai/gpt-oss-20b"
}
```

Old two-field selections remain valid and normalize to `native`.

### 7.4 Usage Records

Keep the existing `provider` or `agent` attribution as `codex`. Add backend information rather than rewriting historical semantics:

```json
{
  "provider": "codex",
  "model_backend": "lmstudio",
  "model": "openai/gpt-oss-20b",
  "input_tokens": 1234,
  "output_tokens": 456
}
```

Local inference has no implied monetary cost. Cost fields should remain absent or null unless Bullpen later supports a user-defined electricity or amortization model. Token usage should be recorded only when Codex emits trustworthy usage events.

## 8. Configuration

### 8.1 Environment

Proposed server-side settings:

```text
BULLPEN_LMSTUDIO_BASE_URL=http://127.0.0.1:1234
BULLPEN_LMSTUDIO_API_TOKEN=
BULLPEN_LMSTUDIO_CATALOG_TIMEOUT_SECONDS=10
BULLPEN_LMSTUDIO_CATALOG_CACHE_SECONDS=30
```

Initial implementation limits:

```text
Maximum catalog response body: 10 MiB
Maximum normalized models:      5,000
Maximum model ID:               512 characters
Maximum display/publisher text: 512 characters per field
Maximum description text:       2,000 characters
Catalog request deadline:       10 seconds by default
Browser request deadline:       30 seconds
```

The discovery endpoint requires LM Studio 0.4.0 or newer because the native `/api/v1/models` API was introduced in 0.4.0. The minimum end-to-end version tuple remains a Phase 0 result because discovery availability alone does not prove Codex tool-loop compatibility.

Requirements:

- The browser never receives `BULLPEN_LMSTUDIO_API_TOKEN`.
- Logs must redact bearer tokens and authorization headers.
- The base URL is normalized by removing a trailing slash.
- The base URL must use `http` or `https`.
- Embedded credentials in URLs are rejected.
- Query strings and fragments are rejected.
- Redirects must not forward authorization to a different origin.
- Response size must be bounded.
- Timeouts must be finite.

### 8.2 Configuration Ownership

V1 should prefer process environment configuration over a workspace-editable URL. A remote base URL causes the Bullpen server to make network requests and therefore creates an SSRF and data-routing boundary. A later UI setting may be added only with explicit validation, authentication, audit, and deployment guidance.

### 8.3 Server Lifecycle

Bullpen does not own LM Studio's lifecycle. Setup instructions may recommend:

```bash
lms daemon up
lms server start --port 1234
```

Bullpen must not silently start or install `llmster`, download models, change server settings, expose LM Studio on the network, or toggle authentication.

## 9. Model Discovery

### 9.1 Source Endpoint

Use LM Studio's native endpoint:

```http
GET {base_url}/api/v1/models
Accept: application/json
Authorization: Bearer <token>   # only when configured
```

The native endpoint is preferred over OpenAI-compatible `/v1/models` because it exposes model type, display name, architecture, format, quantization, parameter count, maximum context, loaded instances, configured parallelism, vision capability, tool-use training, and reasoning options.

Official reference: <https://lmstudio.ai/docs/developer/rest/list>

### 9.2 Discovery Is Read-Only

Discovery must not:

- Call `/api/v1/models/load`.
- Trigger a probe generation.
- Download a model.
- Change JIT loading or eviction settings.
- Validate every model through Codex.

An explicit maintainer diagnostic may separately perform a tiny real invocation, following the existing `bullpen.py model-catalog validate` pattern. Such probes are opt-in because they consume time, compute, memory, and possibly cloud credits if an endpoint is misconfigured.

### 9.3 Normalization

Add `server/lmstudio_models.py` with a `ModelRecord` similar to:

```python
@dataclass(frozen=True)
class ModelRecord:
    id: str
    display_name: str
    publisher: str = ""
    model_type: str = "llm"
    architecture: str = ""
    format: str = ""
    quantization: str = ""
    parameters: str = ""
    size_bytes: int | None = None
    max_context_length: int | None = None
    loaded: bool = False
    loaded_instance_count: int = 0
    loaded_context_length: int | None = None
    parallel_capacity: int | None = None
    vision: bool = False
    tool_call: bool = False
    reasoning_options: tuple[str, ...] = ()
    default_reasoning: str | None = None
    variants: tuple[str, ...] = ()
    selected_variant: str | None = None
```

Parsing rules:

- Require a top-level `models` array.
- Ignore non-object entries.
- Keep only records with `type == "llm"` in the worker catalog.
- Use `key` as the stable model ID.
- Deduplicate by exact model ID.
- Do not invent missing capabilities.
- Treat malformed optional metadata as absent, not as a catalog-wide failure.
- Reject a response that has no structurally valid `models` array.
- Bound model count and string lengths before returning data to the browser.
- Set `loaded_instance_count` to the number of structurally valid loaded instances.
- If exactly one valid instance is loaded, expose its context and parallel capacity.
- If several loaded instances report identical context and parallel values, expose those common values.
- If loaded instances disagree, expose aggregate loaded state but set the ambiguous context or parallel field to null and add a warning. Do not guess which instance an external Codex request will use.

### 9.4 Compatibility Classification

Compatibility is advisory:

```text
recommended:
  type is llm
  AND trained_for_tool_use is true
  AND effective context is at least the configured recommendation threshold

available_with_warning:
  type is llm
  BUT tool-use metadata is false/missing or context is small
```

The effective context for a loaded model is its loaded instance context. For an unloaded model it is the advertised maximum context. A model with a large maximum but a loaded 8K instance must be warned based on 8K.

The initial recommended context threshold should be 25,000 tokens, matching LM Studio's integration guidance for coding harnesses. It is a warning threshold, not a validator.

### 9.5 Catalog Response

The normalized response shape is:

```json
{
  "ok": true,
  "status": "ok",
  "provider": "lmstudio",
  "source": "lmstudio-api",
  "cached": false,
  "cached_at": 1791817200.0,
  "workspaceId": "workspace-id",
  "request_id": "lmstudio-models-1791817200000-1",
  "models": [
    {
      "id": "openai/gpt-oss-20b",
      "display_name": "GPT-OSS 20B",
      "publisher": "openai",
      "type": "llm",
      "format": "gguf",
      "quantization": "Q4_K_M",
      "parameters": "20B",
      "context_limit": 131072,
      "loaded": true,
      "loaded_instance_count": 1,
      "loaded_context_length": 65536,
      "parallel_capacity": 1,
      "vision": false,
      "tool_call": true,
      "reasoning_options": ["low", "medium", "high"],
      "default_reasoning": "medium",
      "agent_compatibility": "recommended",
      "warnings": []
    }
  ]
}
```

The response must not contain the configured token. The returned endpoint, if included for diagnostics, must be a sanitized origin only.

### 9.6 Socket.IO Contract

Request:

```json
event: "models:lmstudio"
{
  "workspaceId": "workspace-id",
  "request_id": "lmstudio-models-...",
  "refresh": false
}
```

Success or data-bearing failure:

```text
event: models:lmstudio:listed
```

Request validation failure:

```text
event: models:lmstudio:error
```

The response echoes `workspaceId` and `request_id`. The UI ignores replies that do not match both values. The client timeout remains 30 seconds; the upstream catalog timeout should be shorter.

### 9.7 Cache and Concurrency

Use a process-local, last-good cache keyed by normalized base URL and a non-secret credential identity. Do not put the raw token in the cache key, logs, or error messages.

Recommended behavior:

| State | Result |
| --- | --- |
| Fresh cache | Return immediately with `status: ok`, `cached: true`. |
| Stale cache, refresh succeeds | Publish and return new catalog. |
| Stale cache, refresh fails | Return last-good catalog with `status: stale`. |
| Empty cache, request fails | Return `status: unavailable` or `error`, models empty. |
| Explicit refresh | Bypass TTL but join an already active refresh. |

Use a short 30-second TTL because downloaded and loaded state changes locally. Use single-flight refresh to prevent several open modals or browser tabs from issuing duplicate requests.

### 9.8 Failure Classification

Normalize failures as:

- `unavailable`: refused connection, unreachable host, DNS failure, or no server.
- `unauthorized`: HTTP 401 or 403.
- `timeout`: connection or response deadline exceeded.
- `invalid_response`: invalid JSON or missing `models` array.
- `response_too_large`: configured size ceiling exceeded.
- `error`: other bounded error.
- `stale`: last-good data returned after a current failure.

## 10. Agent Execution

### 10.1 Command

The intended execution command is equivalent to:

```bash
codex exec \
  --oss \
  --local-provider lmstudio \
  --model openai/gpt-oss-20b \
  --sandbox workspace-write \
  --json \
  --skip-git-repo-check \
  -
```

Bullpen continues to add its approval policy and MCP overrides and writes the assembled task prompt to stdin.

Official references:

- Codex OSS mode: <https://learn.chatgpt.com/docs/config-file/config-advanced#oss-mode-local-providers>
- LM Studio Codex integration: <https://lmstudio.ai/docs/integrations/codex>

### 10.2 Adapter Resolution

Do not register `lmstudio` as a public agent. Extend adapter resolution to include the backend:

```python
adapter = get_adapter(agent, model_backend=model_backend)
```

Suggested registry shape:

```python
_adapters = {
    ("antigravity", "native"): AntigravityAdapter(),
    ("claude", "native"): ClaudeAdapter(),
    ("codex", "native"): CodexAdapter(),
    ("codex", "lmstudio"): LMStudioCodexAdapter(),
    ("opencode", "native"): OpenCodeAdapter(),
}
```

`LMStudioCodexAdapter` should reuse Codex parsing, stream formatting, MCP overrides, sandbox flags, and availability checks. Prefer refactoring `CodexAdapter` to accept execution-mode flags over duplicating its parser.

The adapter name used for worker policy and usage remains `codex`. It may expose a separate `model_backend` property for diagnostics.

### 10.3 Preflight

Before starting a run, Bullpen should perform bounded checks in this order:

1. Codex executable is available.
2. The configured LM Studio endpoint is reachable when Bullpen can address it directly.
3. The selected model appears in a fresh-enough or last-good catalog, if a catalog is available.
4. The command is constructed with LM Studio OSS flags.

A catalog miss should normally produce a clear failure before launch, but a stale or unavailable catalog should not categorically block execution: the Codex-to-LM-Studio path remains authoritative and JIT/model state may have changed.

### 10.4 Streaming and Completion

No new output protocol is required. Codex continues to emit JSONL. Existing behavior remains responsible for:

- Agent messages.
- Shell command display and results.
- File-change display.
- MCP calls.
- Usage aggregation.
- Turn failures.
- Process timeout and termination.
- Worker output persistence.

### 10.5 Cancellation

Cancellation uses the existing subprocess termination path. Bullpen is not responsible for separately cancelling an LM Studio HTTP request; termination of the Codex client must cause the client connection to close. An integration test must confirm that LM Studio does not leave a generation indefinitely active after Codex is terminated.

### 10.6 Permissions and Trust

LM Studio does not change Bullpen's trust model. The Codex harness continues to enforce the configured sandbox and approval policy. A local model's tool requests are untrusted to the same degree as cloud-model tool requests.

Do not relax sandboxing merely because inference is local. Prompt injection, destructive commands, and mistaken file operations remain possible.

### 10.7 Model Loading

Bullpen does not explicitly load models in V1. Operators may:

- Preload a model with `lms load`.
- Enable LM Studio just-in-time model loading.
- Configure idle eviction in LM Studio.

If several workers use different large models, JIT loading and eviction can cause severe thrashing. Bullpen should warn about this but should not manage eviction policy in V1.

## 11. Server and Deployment Topologies

### 11.1 Same-Host Native Process

This is the required V1 topology:

```text
Bullpen process -> 127.0.0.1:1234 -> LM Studio/llmster
Codex process   -> 127.0.0.1:1234 -> LM Studio/llmster
```

It is compatible with Codex's documented `--local-provider lmstudio` behavior and requires no network exposure when authentication is disabled.

### 11.2 Bullpen in Docker, LM Studio on Host

Inside a container, `127.0.0.1` refers to the container, not the host. Discovery may be able to use `host.docker.internal`, but execution must use the same endpoint. Support is blocked until the implementation proves a supported way to override the LM Studio base URL used by Codex OSS mode or deploys `llmster` within the same container/network namespace.

If LM Studio binds beyond loopback, authentication should be enabled. Bullpen documentation must not instruct users to bind `0.0.0.0` without an explicit warning and API token.

### 11.3 Separate `llmster` Host

Remote GPU-host support has the same endpoint and authentication requirements as Docker. It is deferred until endpoint and token forwarding are verified through the actual Codex execution path.

### 11.4 Microsandbox

Microsandbox support is deferred. The sandbox guest must be able to reach the model server, and the configured address must work identically for Bullpen discovery and the Codex child process. The feature must not silently weaken the sandbox's network policy.

## 12. Bionic Boundary

Bionic can run local, LM Link, and LM Studio cloud models and provides a full interactive coding/document agent. That does not by itself make Bionic an automation harness.

As of this specification, the documented Bionic surface does not provide the minimum control-plane operations Bullpen would require:

- List or create Bionic projects programmatically.
- Bind a project to a workspace directory.
- Create a session.
- Submit an agent turn.
- Stream agent/tool/file/command events.
- Approve or deny requested actions.
- Cancel or resume work.
- Retrieve a final structured result and usage.

The local API endpoints visible in Bionic releases are model inference and management APIs. Calling `/v1/responses` or `/api/v1/chat` does not establish that Bionic's project/session coding harness is being invoked.

Bullpen may support Bionic as a first-class harness later only if LM Studio publishes a supported API or headless CLI with lifecycle, streaming, approval, workspace, and result contracts. UI automation and undocumented internal endpoints are explicitly prohibited.

The inverse integration is allowed: a user may configure Bionic to call Bullpen's MCP server. That makes Bionic a client of Bullpen; it does not let Bullpen schedule Bionic workers.

Official references:

- Bionic overview: <https://lmstudio.ai/docs/bionic>
- Bionic projects and sessions: <https://lmstudio.ai/docs/bionic/projects-and-sessions>
- LM Studio API overview: <https://lmstudio.ai/docs/developer/rest>

## 13. Security Review

### 13.1 Credentials

- API tokens are read only by the Bullpen server and, if supported, forwarded to the Codex child through a documented mechanism.
- Tokens are not stored in worker JSON, profiles, workspace config, browser storage, usage records, or Socket.IO payloads.
- Errors and logs redact tokens and authorization headers.
- Temporary Codex configuration containing a token, if required, must use a private run directory and be removed after the run.

### 13.2 SSRF and Network Scope

- Default to loopback.
- Do not permit arbitrary browser-supplied endpoints.
- Validate scheme and authority.
- Reject embedded credentials.
- Bound redirects and do not forward authentication cross-origin.
- Apply connect, read, total, and response-size limits.
- Treat remote endpoints as an explicit data-egress choice.

### 13.3 Model Output and Tool Calls

- Local inference is not trusted inference.
- Codex sandbox and Bullpen trust-mode rules remain in force.
- MCP configuration remains workspace-scoped.
- The feature adds no direct arbitrary shell endpoint.
- Tool-capability metadata is informational and cannot authorize actions.

### 13.4 Browser Exposure

- Catalog records are untrusted strings and must be escaped by the UI.
- Model IDs and display names receive length limits.
- Upstream error bodies are truncated and rendered as text.
- The model catalog Socket.IO event uses the existing authenticated connection and workspace resolution.

### 13.5 Denial of Service

- Catalog calls are cached and single-flight.
- Response size and model count are bounded.
- Worker concurrency remains governed by Bullpen's worker model, but documentation warns that a local server may serialize requests.
- A future per-backend concurrency limit is desirable before advertising high worker counts on one GPU.

## 14. Observability and Diagnostics

Add bounded structured log fields:

```text
agent=codex
model_backend=lmstudio
model=openai/gpt-oss-20b
catalog_status=ok|stale|unavailable|unauthorized|error
catalog_cached=true|false
endpoint_origin=http://127.0.0.1:1234
```

Never log full authorization headers or request bodies.

Add a diagnostic command modeled after the existing catalog validator:

```bash
python3 bullpen.py model-catalog --workspace /path/to/project validate \
  --provider lmstudio \
  --model openai/gpt-oss-20b \
  --output text
```

The diagnostic should separately report:

1. Endpoint reachability.
2. Authentication.
3. Model discovery.
4. Codex CLI availability.
5. Exact command-mode support.
6. A tiny opt-in real agent invocation.

The real invocation must not run automatically at Bullpen startup or during normal catalog enumeration.

## 15. Required Code Changes

### 15.1 Backend

Add:

- `server/lmstudio_models.py`: HTTP catalog, normalization, caching, and error classification.
- `LMStudioCodexAdapter` or parameterized Codex execution mode.
- Backend-aware adapter resolution.
- Socket.IO handler for `models:lmstudio`.
- Validation for `model_backend` and the supported matrix.
- Model-backend attribution in usage records.
- Optional model-catalog validator support.

Modify likely files:

- `server/agents/base.py`
- `server/agents/codex_adapter.py`
- `server/agents/__init__.py`
- `server/events.py`
- `server/workers.py`
- `server/validation.py`
- `server/usage.py`
- `server/model_catalog_validator.py`
- `server/init.py` if a default or durable config entry is added
- profile loading and validation paths

### 15.2 Frontend

Modify:

- `static/utils.js`: backend metadata and preferred-selection normalization.
- `static/app.js`: request-correlated LM Studio model discovery.
- `static/components/WorkerConfigModal.js`: model-source selector, catalog state, warnings, and refresh.
- `static/components/LiveAgentChatTab.js`: equivalent live-chat controls.
- Worker-card and focus displays for optional backend labels.
- Usage views if they currently assume provider uniquely identifies inference source.

### 15.3 Documentation

Add setup instructions for:

- LM Studio desktop on the same host.
- `llmster` on the same host.
- Enabling the API server.
- Choosing a tool-trained model with adequate context.
- JIT loading and memory implications.
- Authentication when exposing the server beyond loopback.
- Known limitations for Docker, remote hosts, Bionic, and concurrency.

## 16. Testing Plan

### 16.1 Catalog Unit Tests

Test:

- Parsing a representative `/api/v1/models` response.
- Filtering embedding and decision models.
- Missing optional capability fields.
- Loaded and unloaded models.
- Multiple loaded instances and deterministic effective-context selection.
- Reasoning options and defaults.
- Variants and selected variant.
- Duplicate IDs.
- Malformed JSON and missing `models` array.
- Oversized response and excessive model count.
- 401/403, connection refused, timeout, and HTTP 500 classification.
- Token redaction.
- TTL, forced refresh, single-flight behavior, and last-good fallback.

### 16.2 Socket.IO Tests

Test:

- Workspace resolution.
- `request_id` echo.
- Success, stale, unavailable, unauthorized, and validation-error responses.
- No credential fields in emitted payloads.
- Concurrent requests join one catalog fetch.
- Unknown workspace behavior.

### 16.3 Adapter Tests

Test:

- Native Codex argv is unchanged.
- LM Studio Codex argv includes `--oss` and `--local-provider lmstudio` exactly once.
- Model IDs pass as one argv element without shell interpolation.
- MCP overrides remain present.
- Sandbox/trust flags remain unchanged.
- Existing Codex JSONL parsing and usage aggregation work unchanged.
- Missing Codex produces a precise setup error.

### 16.4 Worker Lifecycle Tests

Using a fake Codex executable, prove:

- A worker with `model_backend: lmstudio` selects the LM Studio execution mode.
- Prompt delivery remains stdin-based.
- Output streams to the focus view.
- Success moves the ticket according to existing disposition rules.
- Failure and non-retryable configuration errors are classified correctly.
- Stop terminates the active process.
- Usage includes both `provider: codex` and `model_backend: lmstudio`.
- Native Codex workers remain unchanged.

### 16.5 Frontend Tests

Test:

- The model-source selector appears only for supported agents.
- Switching source does not retain an incompatible model silently.
- Returning to native restores or selects a valid native model.
- Catalog responses are request- and workspace-correlated.
- Manual refresh bypasses the frontend cache.
- The saved custom model remains visible during an outage.
- Capability warnings are accessible and do not rely on color alone.
- Unsupported agent/backend combinations cannot be saved.

### 16.6 Opt-In Integration Tests

An opt-in local test should require a running LM Studio server and a configured model. It should:

1. Fetch the catalog.
2. Confirm the selected model is present.
3. Run a tiny Codex task against a temporary Git repository.
4. Exercise a harmless shell or file tool.
5. Exercise the Bullpen MCP connection against a test workspace.
6. Confirm final JSONL completion and usage handling.
7. Cancel one long-running request and confirm both Codex and LM Studio settle.

This test is not part of ordinary CI because it requires model weights and substantial local resources.

## 17. Rollout Plan

### Phase 0: Compatibility Spike

Before product code:

- Verify the installed minimum supported Codex CLI accepts `codex exec --oss --local-provider lmstudio --json -`.
- Verify a tool-trained local model can read files, edit a temporary file, run a harmless command, and call Bullpen MCP.
- Verify cancellation behavior.
- Determine supported endpoint override and token-forwarding mechanisms.
- Record exact minimum LM Studio, Bionic if applicable, `llmster`, and Codex versions.

Exit criterion: all P0 open issues in Section 19 have an implementation decision.

### Phase 1: Same-Host Experimental Support

- Add backend field and validation.
- Add LM Studio model discovery.
- Add Codex LM Studio execution mode.
- Add worker and live-chat UI.
- Support same-host loopback server without required authentication.
- Mark the feature Experimental.

### Phase 2: Hardening

- Add token support after the execution path is proven.
- Add remote/Docker topology after endpoint override is proven.
- Add diagnostics and setup documentation.
- Add single-flight cache and last-good behavior.
- Add capability warnings and concurrency guidance.

### Phase 3: General Availability

- Remove Experimental label after supported-version testing.
- Add deployment coverage for supported Docker or remote configurations.
- Confirm no regressions in native Codex workers.
- Publish limitations for local model quality, context, and hardware capacity.

## 18. Acceptance Criteria

The feature is complete when:

- Existing worker and profile files load without modification.
- A user can configure a Codex worker with `model_backend: lmstudio`.
- Bullpen discovers models through `/api/v1/models` without loading them.
- The UI presents tool, reasoning, vision, context, quantization, and loaded-state metadata when supplied.
- Catalog failures are bounded, classified, and do not leak credentials.
- The selected model key is saved and restored exactly.
- Bullpen invokes Codex with the documented LM Studio OSS flags.
- Codex retains Bullpen MCP access, sandbox behavior, streaming, cancellation, and usage parsing.
- A same-host end-to-end test edits a temporary workspace and completes a Bullpen test ticket.
- Unsupported agent/backend combinations are rejected server-side.
- Native Codex execution and model discovery remain unchanged.
- Bionic is not presented as externally controllable unless a supported Bionic control API exists.
- Setup documentation identifies the supported topology and all known limitations.
- Every P0 issue below is resolved or explicitly removed from the claimed support matrix.

## 19. Open-Issue Review

| Issue | Priority | Current disposition | Blocks |
| --- | --- | --- | --- |
| LMSTUDIO-01 | P0 | Same-host/default-port boundary until endpoint override is proven | Docker, remote, non-default port |
| LMSTUDIO-02 | P0 | Unauthenticated loopback only until token forwarding is proven | Authenticated and network-exposed execution |
| LMSTUDIO-03 | P0 | Compatibility spike must establish a reference model | Any supported end-to-end release |
| LMSTUDIO-04 | P1 | Centralize `model_backend` normalization and test every serialization path | Reliable persistence/import/export |
| LMSTUDIO-05 | P1 | Report capacity in Phase 1; add conservative scheduling before GA | Predictable concurrent execution |
| LMSTUDIO-06 | P1 | Warn from effective loaded context; do not hard-block | User guidance and reliability |
| LMSTUDIO-07 | P1 | Verify process termination ends or settles inference | Reliable cancellation |
| LMSTUDIO-08 | P1 | Persist base key; leave variant selection in LM Studio | Deterministic quantization selection |
| LMSTUDIO-09 | P1 | Add local-server error classifications | Safe retry behavior |
| LMSTUDIO-10 | P2 | Display reasoning capability; defer control | Reasoning selector |
| LMSTUDIO-11 | P2 | Explicitly out of V1 scope | Bionic cloud and LM Link support |
| LMSTUDIO-12 | P2 | Watch official Bionic control surfaces | Bionic as a harness |
| LMSTUDIO-13 | P2 | Use Codex token usage only | Local performance telemetry |
| LMSTUDIO-14 | P2 | Record tested versions during Phase 0 | Published compatibility matrix |

### LMSTUDIO-01 — P0: Codex endpoint override for Docker and remote hosts

**Issue:** Official Codex and LM Studio documentation establishes `--oss --local-provider lmstudio`, but the reviewed public documentation does not establish how Bullpen can provide an arbitrary LM Studio base URL to that built-in provider. Discovery can use a configured URL while execution may still target `localhost:1234`, producing a split-brain configuration.

**Impact:** Docker-host, remote GPU host, Microsandbox, and non-default-port support cannot be claimed.

**Required resolution:** Prove and document a supported Codex configuration or command-line override for the endpoint. If none exists, restrict V1 to same-host default-port use or define a supported custom Codex model-provider configuration and test it end to end.

**Recommendation:** Treat same-host `127.0.0.1:1234` as the Phase 1 support boundary. Do not infer that successful catalog discovery proves execution connectivity.

### LMSTUDIO-02 — P0: API-token forwarding through Codex

**Issue:** Bullpen can authenticate its catalog request, but the supported mechanism for the Codex LM Studio provider to send the same API token has not been established.

**Impact:** Authenticated LM Studio endpoints may be discoverable by Bullpen but unusable by the worker. Network-exposed configurations should not be supported without authentication.

**Required resolution:** Identify a documented Codex environment or provider configuration for the bearer token, prove it does not leak through argv or logs, and test 401/403 behavior. Otherwise limit V1 execution to an unauthenticated loopback server.

**Recommendation:** Do not store the token in worker or workspace data. Use a private environment or temporary Codex configuration only after its behavior is documented and tested.

### LMSTUDIO-03 — P0: Minimum compatible model behavior

**Issue:** `trained_for_tool_use` is metadata, not proof that the model can complete a Codex coding loop. Small or weak models may emit malformed calls, loop, or exhaust context.

**Impact:** The feature can appear operational while workers fail unpredictably.

**Required resolution:** Establish at least one tested reference model and quantization for each supported platform class, plus a compatibility test covering shell, file edit, MCP, and completion.

**Recommendation:** Keep the picker permissive but label unverified models. Document that compatibility is model-specific.

### LMSTUDIO-04 — P1: Agent/backend schema breadth

**Issue:** Adding `model_backend` touches workers, profiles, last-selection state, live chat, usage, import/export, Bento packaging, validation, and tests.

**Impact:** A partial implementation can silently drop the backend and run a local model selection against native Codex.

**Required resolution:** Inventory every serialization and copy path before implementation. Round-trip tests must cover worker save/load, duplicate, profile save/apply, team/Bento export/import, and chat defaults.

**Recommendation:** Centralize normalization rather than sprinkling `or "native"` across the frontend and backend.

### LMSTUDIO-05 — P1: Concurrency and local resource scheduling

**Issue:** Bullpen may start several workers concurrently while one local model instance has `parallel: 1`, limited context memory, or insufficient RAM/VRAM for multiple models.

**Impact:** Requests queue invisibly, time out, or cause model eviction thrash.

**Required resolution:** Decide whether V1 merely reports loaded parallel capacity or also limits concurrent LM Studio-backed workers.

**Recommendation:** Phase 1 should display capacity and document the limitation. Before GA, add a per-backend semaphore defaulting conservatively to one when capacity is unknown.

### LMSTUDIO-06 — P1: Effective context and Codex context expectations

**Issue:** LM Studio reports both maximum model context and per-instance loaded context. Codex can consume substantial context, and the loaded value may be much lower than the advertised maximum.

**Impact:** Tool definitions and repository context can crowd out the task or cause truncation.

**Required resolution:** Define which value the UI uses and whether execution should warn or block.

**Recommendation:** Use loaded-instance context when loaded, otherwise maximum context. Warn below 25K; do not hard-block in V1.

### LMSTUDIO-07 — P1: Cancellation semantics

**Issue:** Killing Codex is expected to close the inference stream, but LM Studio may continue generation briefly or retain queued work.

**Impact:** GPU resources can remain occupied after Bullpen reports a stopped worker.

**Required resolution:** Test cancellation against supported LM Studio and Codex versions and document observed settling behavior.

**Recommendation:** Do not add an undocumented LM Studio cancellation call. Escalate to explicit API cancellation only if a supported endpoint exists.

### LMSTUDIO-08 — P1: Catalog identity and variants

**Issue:** LM Studio can expose model variants and a selected variant. It is unclear whether Bullpen should persist the base `key`, the selected variant, or allow choosing a variant separately.

**Impact:** Runs may use a different quantization than the user expects, especially after local settings change.

**Required resolution:** Confirm what model ID Codex must send for deterministic selection.

**Recommendation:** V1 persists the `key` and displays the selected variant. Variant selection remains in LM Studio until an end-to-end deterministic contract is proven.

### LMSTUDIO-09 — P1: Retry classification

**Issue:** Existing worker retries distinguish certain provider failures. Local-server failures introduce new permanent and transient classes.

**Impact:** Bullpen may repeatedly retry a missing model or fail immediately on a temporary model load.

**Required resolution:** Classify missing model, unsupported tool call, authentication, and invalid endpoint as non-retryable; classify temporary load contention, connection reset, and server busy conservatively.

**Recommendation:** Bound retries and show the original classified cause in the worker output.

### LMSTUDIO-10 — P2: Reasoning controls

**Issue:** LM Studio exposes reasoning options, but Bullpen's worker schema does not currently have a backend-neutral reasoning field and Codex may map local reasoning differently.

**Impact:** The UI may advertise a setting it cannot reliably apply.

**Required resolution:** Verify Codex's local-provider reasoning controls for the supported model.

**Recommendation:** Display reasoning capability in V1 but defer a selectable reasoning control unless the mapping is proven.

### LMSTUDIO-11 — P2: Bionic cloud and LM Link models

**Issue:** Bionic's UI can select cloud and LM Link models, but the native model-list API documentation does not establish that these are exposed with a stable execution contract to external Codex clients.

**Impact:** Users may expect Bullpen to see every model visible in Bionic.

**Required resolution:** None for V1; explicitly document the local-server scope.

**Recommendation:** Add cloud or LM Link discovery only when LM Studio documents external API behavior, identifiers, authentication, and billing.

### LMSTUDIO-12 — P2: Bionic harness API watch

**Issue:** Bionic is a natural conceptual harness, but no supported external project/session control plane is documented.

**Impact:** A potentially better future integration is unavailable today.

**Required resolution:** Monitor official Bionic documentation and changelog for a session API or headless agent command.

**Recommendation:** Preserve the agent/backend separation so a future `bionic` harness can be added without changing the LM Studio backend catalog.

### LMSTUDIO-13 — P2: Usage and performance metrics

**Issue:** Codex JSONL usage may not include LM Studio-specific throughput, time-to-first-token, model-load time, or cache statistics.

**Impact:** Bullpen's usage view may be less informative for local models.

**Required resolution:** Decide whether to rely solely on Codex usage or correlate LM Studio request logs/API data.

**Recommendation:** Use Codex token usage in V1. Do not scrape LM Studio logs or infer costs. Add backend performance telemetry only through a supported API with a reliable request correlation ID.

### LMSTUDIO-14 — P2: Server version and capability negotiation

**Issue:** The exact minimum versions for `/api/v1/models`, Codex OSS mode, tool-call streaming, authentication, and cancellation behavior are not recorded.

**Impact:** Users may run combinations that partially work.

**Required resolution:** The compatibility spike must capture tested version tuples and feature checks.

**Recommendation:** Prefer capability checks over version checks where practical, but include tested minimum versions in setup documentation.

## 20. Final Recommendation

Proceed with a compatibility spike, then implement same-host experimental support using Codex as the harness and LM Studio as the backend. Do not implement a raw `lms chat -p` worker and do not present Bionic as externally schedulable.

The architecture should make `model_backend` explicit now. That is a slightly broader schema change than adding an `lmstudio` agent string, but it prevents immediate conceptual debt and provides the correct foundation for Ollama, remote inference servers, and any future Bionic harness API.

General availability should wait until endpoint override, authentication forwarding, and at least one reference model's agent behavior are proven end to end.

