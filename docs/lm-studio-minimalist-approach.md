# LM Studio Minimalist Integration

## 1. Status

Proposal.

This document specifies a deliberately narrow path for making locally available
LM Studio chat models discoverable and runnable in Bullpen. It uses Bullpen's
existing OpenCode worker and live-chat paths instead of introducing a new agent,
a new worker backend field, or the broader Codex-backed architecture described
in `docs/lm-studio-integration.md`.

The proposal replaces routine hand editing of
`~/.config/opencode/opencode.jsonc`. A small manual escape hatch remains for a
runtime alias that LM Studio cannot relate to a native catalog record without
guessing.

## 2. Decision Summary

Bullpen will:

1. Read LM Studio's native model catalog from `127.0.0.1:1234`.
2. Keep only LLMs that LM Studio marks as trained for tool use.
3. Present those models under the existing OpenCode provider selector as
   `lmstudio/<native-key>`.
4. Add the same discovered model definitions to the temporary OpenCode config
   Bullpen already creates for each OpenCode run.
5. Refresh on demand and on relevant UI activity, with a short process-local
   cache and last-good fallback.
6. Leave the user's global OpenCode config untouched.

OpenCode remains the agent harness and LM Studio remains the inference server:

```text
Bullpen worker or live chat
        |
        v
OpenCode agent and tool loop
        |
        v
LM Studio OpenAI-compatible API on 127.0.0.1:1234
```

## 3. Goals

- Show downloaded or LM Link-visible, tool-trained LM Studio LLMs in Bullpen's
  existing OpenCode model selector.
- Remove the need to add each ordinary model to the user's global OpenCode
  configuration by hand.
- Make catalog additions and removals visible without restarting Bullpen.
- Ensure every dynamically listed model is also registered in the OpenCode
  process that runs it.
- Preserve the current `lmstudio/<model-id>` worker model value.
- Keep discovery read-only and avoid loading models merely to inspect them.
- Preserve a usable last-good list during temporary LM Studio outages.
- Use one implementation for the worker modal and Live Agent Chat.

## 4. Non-Goals

- Adding `lmstudio` to Bullpen's agent list.
- Adding `model_backend` to workers, profiles, chats, imports, or exports.
- Adding a Codex-to-LM-Studio execution path.
- Managing LM Studio startup, shutdown, downloads, JIT settings, eviction, or
  authentication.
- Exposing decision models, embedding models, or LLMs not marked as trained for
  tool use.
- Probing every model with an inference request.
- Choosing or loading an LM Studio variant.
- Providing reasoning-level controls.
- Providing remote endpoint configuration in the first implementation.
- Rewriting `~/.config/opencode/opencode.jsonc`.
- Guaranteeing that a model advertised as tool-trained performs well as a coding
  agent. The capability is catalog metadata, not a Bullpen quality certification.

## 5. Current State

The current proof of concept defines a custom `lmstudio` provider in the user's
global OpenCode configuration:

```json
{
  "provider": {
    "lmstudio": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LM Studio (local)",
      "options": {
        "baseURL": "http://127.0.0.1:1234/v1"
      },
      "models": {
        "qwen/qwen3.8-27b": {
          "name": "Qwen 3.8 27B (local)"
        }
      }
    }
  }
}
```

`opencode models` reads those definitions. Bullpen invokes that command through
`server/opencode_models.py`, returns the records through the
`models:opencode` Socket.IO exchange, and displays them in the worker and chat
selectors. Bullpen caches the OpenCode result for five minutes; the existing
Refresh action bypasses that cache.

This works, but discovery is manual. A newly downloaded model is invisible until
the configuration is edited, while a deleted or remote model can remain listed
indefinitely.

OpenCode also requires a custom model ID to be a key in the custom provider's
`provider.models` object. Bullpen therefore cannot solve the problem by changing
only the visible selector. The execution subprocess must receive matching model
configuration. OpenCode documents both this model identity rule and runtime
configuration overlays. Its configuration layers are merged, and
`OPENCODE_CONFIG_CONTENT` is the highest-precedence ordinary runtime layer.

## 6. Source of Truth

Use LM Studio's native endpoint:

```http
GET http://127.0.0.1:1234/api/v1/models
Accept: application/json
```

Do not use OpenCode's catalog as the source of LM Studio capabilities. OpenCode
does not expose LM Studio's model type or `trained_for_tool_use` flag.

Do not use LM Studio's OpenAI-compatible `/v1/models` endpoint as the primary
catalog. It is useful for runtime diagnostics but lacks the native capability
metadata required for safe filtering.

The first version supports only the same-host, default-port endpoint. Define the
URL once in server code so it can later be replaced by a setting without
changing call sites:

```text
BULLPEN_LMSTUDIO_BASE_URL=http://127.0.0.1:1234
```

The environment variable may be accepted in the initial implementation for
development, but the UI does not expose it and Bullpen does not claim remote or
authenticated endpoint support.

## 7. Eligibility Rules

A native catalog record is selectable only when all of these are true:

```text
type == "llm"
capabilities.trained_for_tool_use == true
key is a non-empty string
```

The implementation must not infer tool capability from publisher, architecture,
model name, reasoning support, vision support, or prior knowledge.

Consequences:

- Decision models are excluded even when they have a vision adapter.
- Embedding models are excluded.
- An LLM with `trained_for_tool_use: false` is excluded.
- An LLM with a missing or malformed capability flag is excluded.
- Reasoning support does not make a record a decision model and does not affect
  eligibility.

Use the native `key` as the model ID and `display_name` as the label. Do not
persist `selected_variant` as the model ID.

## 8. Normalized Model Record

Add `server/lmstudio_models.py` with a bounded parser and a record similar to:

```python
@dataclass(frozen=True)
class LMStudioModelRecord:
    id: str
    display_name: str
    publisher: str = ""
    architecture: str = ""
    format: str = ""
    quantization: str = ""
    parameters: str = ""
    max_context_length: int | None = None
    vision: bool = False
    reasoning_options: tuple[str, ...] = ()
    default_reasoning: str | None = None
    loaded: bool = False
    selected_variant: str | None = None
```

The browser-facing record is:

```json
{
  "id": "lmstudio/qwen/qwen3.8-27b",
  "provider": "lmstudio",
  "model": "qwen/qwen3.8-27b",
  "display_name": "Qwen3.8 27B",
  "source": "lmstudio-api",
  "tool_capable": true,
  "loaded": false,
  "max_context_length": 262144,
  "format": "mlx",
  "quantization": "4bit"
}
```

The `id` includes OpenCode's provider prefix. The native model key remains in
`model`. This matches the existing OpenCode selector contract.

Parser requirements:

- Require a top-level `models` array.
- Ignore non-object array members.
- Bound response bytes, record count, and individual string lengths.
- Deduplicate by exact native key.
- Sort by case-insensitive display name and then by key.
- Treat malformed optional metadata as absent.
- Reject a response without a structurally valid `models` array.
- Never return decision or embedding records as selectable models.

## 9. Catalog Cache and Refresh

Use a process-local cache with a 30-second TTL and one last-good snapshot.

Only one request may refresh a given endpoint at a time. Concurrent callers wait
for or reuse that refresh instead of issuing duplicate requests.

| State | Result |
|---|---|
| Fresh cache | Return immediately with `status: ok`, `cached: true`. |
| Cache miss and fetch succeeds | Store and return the new snapshot. |
| Manual refresh succeeds | Replace the cache even when the old entry is fresh. |
| Refresh fails with a last-good snapshot | Return it with `status: stale` and a sanitized warning. |
| Refresh fails without a last-good snapshot | Return `status: unavailable` or `error` with an empty list. |

The cache key is the normalized endpoint origin. Never include secrets in the
key, log messages, or browser payloads.

### 9.1 Refresh Triggers

The minimalist implementation does not run a permanent background poller.
Refresh occurs when:

- an OpenCode worker modal first needs its model catalog;
- Live Agent Chat first needs its model catalog;
- the user selects the `lmstudio` provider after the cache TTL has elapsed;
- the page regains focus while `lmstudio` is selected and the cache is stale;
- the user presses Refresh, which forces a fetch.

If the model picker remains open, the client may request a refresh every 30
seconds. Stop that timer when the picker closes, the provider changes, or the
component unmounts.

This provides near-live behavior while somebody is actively selecting a model,
without keeping LM Studio traffic active for idle Bullpen sessions.

### 9.2 Change Detection

Compute a stable fingerprint from the sorted normalized records. The fingerprint
must include identity and fields shown by the UI, but not volatile timestamps.

When a refresh changes the fingerprint, return `changed: true`. The requesting
client updates immediately. A future optimization may broadcast the new snapshot
to the workspace room, but broadcasting is not required for the first version.

Do not remove the currently selected value from an open form merely because it
disappears from a refreshed catalog. Keep it visible and mark it unavailable so
the user can deliberately replace it.

## 10. Socket.IO Contract

Add a dedicated request rather than overloading OpenCode CLI discovery:

```text
client -> models:lmstudio
server -> models:lmstudio:listed
server -> models:lmstudio:error
```

Request:

```json
{
  "workspaceId": "workspace-id",
  "request_id": "lmstudio-models-1792000000000-1",
  "refresh": true
}
```

Successful response:

```json
{
  "workspaceId": "workspace-id",
  "request_id": "lmstudio-models-1792000000000-1",
  "ok": true,
  "status": "ok",
  "source": "lmstudio-api",
  "cached": false,
  "changed": true,
  "models": []
}
```

Stale response keeps `ok: true`, sets `status: stale`, returns the last-good
`models`, and includes a user-safe `warning`.

An empty-cache failure sets `ok: false`, returns an empty list, and includes a
user-safe `error`. Correlate every response by `request_id` and `workspaceId`, as
the existing provider catalog requests do.

## 11. Selector Integration

The worker modal and Live Agent Chat continue to present `OpenCode` as the AI
provider. Within the existing OpenCode model controls:

- `lmstudio` appears in the Model Provider selector when an eligible LM Studio
  record exists or the current selection already uses that prefix.
- Selecting `lmstudio` shows the native, filtered records.
- The stored worker/chat model remains the full OpenCode identity, for example
  `lmstudio/google/gemma-4-31b`.
- Search matches the ID and display name.
- Optional metadata may show context, quantization, loaded state, vision, and
  reasoning support, but these fields do not block selection.
- The Refresh action forces native LM Studio discovery and then updates the
  OpenCode runtime overlay described below.

The existing general OpenCode catalog remains authoritative for all other
providers. The UI merges the two sources by exact full ID, preferring the richer
LM Studio native record on a collision.

## 12. OpenCode Runtime Registration

Discoverability and execution must use the same snapshot.

Bullpen's `OpenCodeAdapter.prepare_env()` already creates a private temporary
OpenCode configuration for the Bullpen MCP server. Extend that generated config
with the `lmstudio` provider and every eligible model from the latest usable LM
Studio snapshot:

```json
{
  "provider": {
    "lmstudio": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LM Studio (local)",
      "options": {
        "baseURL": "http://127.0.0.1:1234/v1"
      },
      "models": {
        "google/gemma-4-31b": {
          "name": "Gemma 4 31B",
          "limit": {
            "context": 262144
          }
        }
      }
    }
  }
}
```

Use the adapter's existing private temporary file rather than editing the global
OpenCode config. OpenCode merges configuration layers, so unrelated user
settings remain available. The generated runtime definition supplies the model
keys required by OpenCode for custom providers.

Rules:

- Generate the provider block only when the selected model begins with
  `lmstudio/` or when catalog discovery invokes OpenCode with the overlay.
- Register all records from the current or last-good snapshot so model lookup is
  deterministic for the life of the subprocess.
- Use the selected model's native key exactly; do not rewrite slashes.
- Omit `limit.context` when LM Studio does not provide a valid positive value.
- Do not place LM Studio API credentials in generated config in this version.
- Keep the existing MCP configuration in the same temporary config.
- Delete the temporary directory through the adapter's existing cleanup path.

If no usable LM Studio snapshot exists when a worker starts, fail before launch
with a targeted message. Do not run an unregistered custom model and hope that
OpenCode accepts it.

## 13. Stable Keys, Runtime IDs, and Aliases

LM Studio can expose more than one identity for what appears to be the same
download. In the verified Qwen case:

- the native catalog key was `qwen/qwen3.8-27b`;
- a loaded OpenAI-compatible runtime ID was `qwen3.8-27b-mlx`.

The base rule is to use the native key. Bullpen must not infer aliases by fuzzy
matching names, architectures, publishers, sizes, or parameter counts.

Provide a small explicit alias setting for exceptional deployments:

```text
BULLPEN_LMSTUDIO_MODEL_ALIASES_JSON=
  {"qwen3.8-27b-mlx":"qwen/qwen3.8-27b"}
```

Semantics:

- The JSON object maps a runtime model ID to an eligible native key.
- The target native key must exist in the current or last-good eligible catalog.
- A valid alias is added to the selector as
  `lmstudio/<runtime-model-id>` and to the generated OpenCode provider models.
- The UI labels it as an alias of the native display name.
- Invalid, duplicate, oversized, or unknown mappings are ignored with a
  sanitized server warning.
- Aliases are process configuration, not workspace or ticket data.

This escape hatch replaces hand editing for known runtime-identity exceptions
without introducing heuristic identity resolution.

## 14. Failure Behavior

| Condition | User-visible behavior |
|---|---|
| LM Studio is unreachable and no cache exists | `LM Studio is unavailable at 127.0.0.1:1234.` |
| LM Studio is unreachable and a last-good list exists | Keep the list, label it stale, and allow manual refresh. |
| Native response is malformed | Report an invalid catalog response; keep last-good data when available. |
| No eligible models exist | `No tool-capable chat models were reported by LM Studio.` |
| Selected model disappeared | Preserve the value, label it unavailable, and block a new run unless it exists in last-good data. |
| OpenCode is unavailable | Use the existing OpenCode unavailable error. |
| OpenCode rejects the generated config | Report a configuration error without falling back to the global hand-edited catalog. |
| LM Studio rejects inference | Surface the existing OpenCode run failure with the selected model ID. |

Errors sent to the browser must not include tokens, environment dumps, complete
response bodies, or arbitrary HTML returned by an endpoint.

## 15. Security and Operational Boundaries

- Discovery is server-side. The browser never calls port 1234 directly.
- Discovery uses loopback only in this version.
- Catalog requests are GET requests and must not load, unload, or download a
  model.
- Treat all catalog strings as untrusted data; bound, normalize, and escape them.
- Do not enable CORS or expose LM Studio on the LAN for Bullpen discovery.
- Do not automatically start LM Studio or change its settings.
- Preserve OpenCode and Bullpen's existing worker trust and tool policies.
- The generated provider config is private temporary state and must not be
  written into the workspace or committed.

## 16. Implementation Outline

### 16.1 Server

1. Add `server/lmstudio_models.py` for HTTP discovery, parsing, eligibility,
   aliases, caching, single-flight refresh, and runtime provider generation.
2. Add `models:lmstudio` handlers in `server/events.py`.
3. Add a helper that returns the latest usable LM Studio snapshot without
   starting a second refresh during worker launch.
4. Extend `OpenCodeAdapter.prepare_env()` to merge the dynamic provider block
   into its existing temporary MCP config.
5. Add a targeted pre-launch error for an unavailable selected LM Studio model.

### 16.2 Browser

1. Add `requestLMStudioModels()` beside the existing provider catalog request
   helpers in `static/app.js`.
2. Add shared LM Studio catalog state and refresh methods to the worker modal and
   Live Agent Chat.
3. Merge native LM Studio records into the existing OpenCode model list.
4. Refresh on first use, explicit Refresh, provider selection after TTL, and
   focus after TTL.
5. Preserve a selected-but-missing value and show stale/unavailable state.

### 16.3 Configuration

Add server-side constants with environment overrides:

```text
BULLPEN_LMSTUDIO_BASE_URL=http://127.0.0.1:1234
BULLPEN_LMSTUDIO_CATALOG_TIMEOUT_SECONDS=10
BULLPEN_LMSTUDIO_CATALOG_CACHE_SECONDS=30
BULLPEN_LMSTUDIO_MODEL_ALIASES_JSON={}
```

Do not add these values to workspace serialization in this phase.

## 17. Test Plan

### 17.1 Unit Tests

- Parse representative native records for LLM, decision, and embedding models.
- Include only `type: llm` plus explicit `trained_for_tool_use: true`.
- Exclude missing and false tool-use flags.
- Parse optional reasoning, vision, quantization, context, variants, and loaded
  state.
- Deduplicate and sort deterministically.
- Reject malformed top-level responses and bound oversized input.
- Verify fresh cache, forced refresh, last-good fallback, and single-flight
  behavior.
- Verify alias validation without fuzzy matching.
- Verify errors redact endpoint response bodies and secrets.

### 17.2 Socket.IO Tests

- Correlate replies by workspace and request ID.
- Forward `refresh: true` to the catalog service.
- Return `ok`, `stale`, `unavailable`, and `error` states correctly.
- Reject unknown workspaces through the existing event conventions.

### 17.3 Frontend Tests

- Merge LM Studio records into the OpenCode catalog without duplicates.
- Show only eligible records returned by the server.
- Filter on `lmstudio` and search by ID or display name.
- Force refresh from both the worker modal and Live Agent Chat.
- Preserve the current selection when it disappears.
- Stop active refresh timers when the UI no longer needs them.
- Ignore out-of-order request responses.

### 17.4 Adapter Tests

- Generated temporary config contains the LM Studio provider and eligible model
  keys.
- Generated config retains the Bullpen MCP block.
- Global and project OpenCode configuration files are not modified.
- The selected `lmstudio/<key>` is passed unchanged to `opencode run --model`.
- Context limits are included only when valid.
- Temporary config is removed by normal cleanup and cancellation paths.

### 17.5 Opt-In Local Test

With LM Studio running on port 1234:

1. Fetch the live native catalog.
2. Confirm all and only tool-trained LLMs appear under `lmstudio` in both
   selectors.
3. Add or remove a model, force refresh, and confirm the selector changes without
   restarting Bullpen.
4. Run one selected model through an OpenCode Bullpen worker.
5. Confirm it invokes a harmless read-only tool and returns the result.
6. Stop LM Studio and confirm the last-good catalog is shown as stale.
7. Restart LM Studio, refresh, and confirm the status returns to current.

## 18. Acceptance Criteria

The minimalist integration is complete when:

- A newly available tool-trained LM Studio LLM appears in Bullpen after refresh
  without editing global OpenCode configuration.
- Decision, embedding, and non-tool-trained LLM records do not appear.
- A dynamically discovered model launches successfully through the existing
  OpenCode adapter and Bullpen MCP tool loop.
- Worker and live-chat selectors return the same LM Studio model set.
- Removing a model updates the selector without discarding an in-progress form
  selection.
- A temporary LM Studio outage preserves and labels the last-good list.
- Bullpen never writes `~/.config/opencode/opencode.jsonc`.
- Existing non-LM-Studio OpenCode models behave unchanged.
- No new worker schema field or agent identity is introduced.

## 19. Rollout and Removal of the Kludge

Ship behind an environment flag for one release:

```text
BULLPEN_LMSTUDIO_MINIMAL_DISCOVERY=1
```

During the trial, compare the native discovered list with `opencode models
lmstudio` and log counts only. Do not log full configuration or inference data.

After the local acceptance test passes:

1. Enable minimalist discovery by default for same-host OpenCode users.
2. Remove ordinary downloaded-model entries from the global hand-edited
   `opencode.jsonc`.
3. Keep only required explicit runtime aliases in
   `BULLPEN_LMSTUDIO_MODEL_ALIASES_JSON`.
4. Remove the feature flag after one stable release.

The broader design in `docs/lm-studio-integration.md` remains the path for a
first-class backend abstraction, Codex execution, authentication, remote
endpoints, profile persistence, and richer reasoning controls. This proposal is
an intentionally smaller bridge that provides useful discovery now.

## 20. References

- [LM Studio native model listing](https://lmstudio.ai/docs/developer/rest/list)
- [OpenCode model identity and custom model configuration](https://docs.opencode.ai/docs/models/)
- [OpenCode configuration layering and runtime overrides](https://dev.opencode.ai/docs/config)
- `docs/lm-studio-integration.md`
- `server/opencode_models.py`
- `server/agents/opencode_adapter.py`
- `static/components/WorkerConfigModal.js`
- `static/components/LiveAgentChatTab.js`
