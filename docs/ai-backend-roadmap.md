# AI Backend Roadmap

Last reviewed: 2026-04-12

## Executive Summary

Bullpen should prioritize new AI backends that look like Claude CLI and Codex CLI from the server's point of view: a local executable, non-interactive prompt input, streamable output, workspace-aware file editing, and subscription-friendly access. On that basis, the next three integrations to consider are:

1. **Gemini CLI** - best next integration. It is a first-party, open-source terminal coding agent with MCP support, high coding capability, and a subscription/account model intended for CLI use.
2. **Cursor Agent CLI** - best "Claude-shaped" adapter. Its documented `--print` plus `stream-json` output closely matches Bullpen's existing Claude adapter and gives access to Cursor's coding-agent stack through a paid subscription.
3. **GitHub Copilot CLI / coding agent** - best ecosystem integration. It is subscription-backed, developer-friendly, and likely attractive to many users, but its programmatic/headless integration should be spiked because the CLI/agent surface is less obviously isomorphic to Bullpen's current one-shot subprocess path.

OpenRouter, ChatGPT, Windsurf, Aider, Amazon Q/Kiro, Qwen Code, and local Ollama-style backends remain relevant, but they are either already covered by the current Codex adapter, not clearly headless CLI-friendly, API/router rather than coding-agent CLI, or lower confidence for Bullpen's current usage model.

## Current Bullpen Backend

Bullpen currently has a process-backed agent abstraction:

- `server/agents/base.py` defines `AgentAdapter` with `available()`, `build_argv()`, `parse_output()`, and `format_stream_line()`.
- `server/agents/claude_adapter.py` launches `claude --print --output-format stream-json --verbose --dangerously-skip-permissions --model ...` and optionally writes a temporary MCP config.
- `server/agents/codex_adapter.py` launches `codex exec --model ... --full-auto --json -` and injects Bullpen's MCP server through `-c mcp_servers...` overrides.
- `server/workers.py` assumes every worker adapter can build an argv, receive a prompt on stdin, stream stdout/stderr, and return a final parse result.
- `server/events.py` repeats the same subprocess shape for Live Agent Chat.
- Provider choices are hard-coded in `server/validation.py`, `static/utils.js`, `static/components/WorkerConfigModal.js`, and `static/components/LiveAgentChatTab.js`.

That shape is a good fit for CLI coding agents, but it is not enough for pure model APIs. OpenRouter, Gemini API, OpenAI Responses API, Ollama, and similar APIs would require Bullpen to own a tool loop, workspace context selection, patch application, cancellation, and audit semantics. That is doable, but it is a larger product than "add another agent backend."

## Selection Criteria

The ranking below uses three primary filters:

- **Coding-agent capability:** can do broad repository work, inspect/edit files, and run multi-step coding tasks like Claude CLI or Codex CLI.
- **CLI/headless fit:** has a local command-line interface suitable for non-interactive execution and streaming output.
- **Terms/subscription fit:** intended to be used by a logged-in developer or subscription plan from a local developer tool, rather than requiring Bullpen to resell API access or scrape an editor UI.

Secondary filters:

- MCP/tool support or a path to Bullpen MCP.
- Structured output support.
- Setup discoverability and cross-platform install story.
- Provider/model diversity.
- Stability of documented interface.

## Priority 1: Gemini CLI

### Why It Should Be First

Gemini CLI is the strongest new Bullpen fit because it is explicitly a terminal-native AI agent, is open source, supports MCP, and is distributed for the exact "developer in a terminal" workflow Bullpen orchestrates. Google's launch materials describe Gemini CLI as an open-source AI agent for the terminal, integrated with Gemini Code Assist, MCP, and Google Search, with generous free preview usage through a Gemini Code Assist license. The GitHub repository documents authentication options including personal Google login, Gemini API key, and Vertex AI.

Compared with OpenRouter or a raw Gemini API adapter, Gemini CLI gives Bullpen a ready-made agent runtime: repository context, shell/file operations, model access, and existing user auth. That keeps Bullpen in the same product lane as the current Claude/Codex adapters.

### Terms And Usage Fit

This is a good fit if Bullpen treats Gemini CLI as a user-installed tool running under the user's own Google/Gemini Code Assist account. Bullpen should not bundle credentials, proxy shared accounts, or present Google's free tier as guaranteed capacity. The doc should describe it as "bring your own Gemini CLI login/API key."

### Implementation Architecture

Add `server/agents/gemini_adapter.py` as a `ProcessAgentAdapter`.

Responsibilities:

- Discover `gemini` with `shutil.which("gemini")`, plus common npm/binary paths if needed.
- Support `BULLPEN_GEMINI_PATH` for explicit binary selection.
- Build a non-interactive argv that reads the prompt from stdin or from a temp file, depending on Gemini CLI's stable headless mode.
- Prefer structured/JSON output if the CLI exposes it; otherwise parse line-oriented text conservatively.
- Inject Bullpen MCP configuration if Gemini CLI accepts MCP server config through a project/user config file or command-line flag.
- Format stream lines for focus/chat display, truncating large tool outputs the same way Claude/Codex do.
- Parse final success/failure and usage if the CLI exposes usage; otherwise return an empty usage dict.

Recommended adapter sketch:

```python
class GeminiAdapter(AgentAdapter):
    @property
    def name(self):
        return "gemini"

    def available(self):
        return _find_gemini() is not None

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        argv = [_find_gemini() or "gemini"]
        argv.extend(["--model", model])
        argv.extend(["--output-format", "json"])  # only if documented/stable
        if bp_dir:
            argv.extend(self._mcp_config_args(bp_dir))
        argv.append("-")  # if stdin is supported; otherwise add prompt_delivery metadata
        return argv
```

Expected code changes:

- Add `gemini` to `server/agents/__init__.py`.
- Add `gemini` to provider validation.
- Add Gemini models to frontend `MODEL_OPTIONS`, ideally after moving provider metadata to the backend.
- Add tests mirroring `TestClaudeAdapter` and `TestCodexAdapter`.
- Add chat hardening rules only if Gemini needs provider-specific MCP startup handling.
- Document setup: install CLI, authenticate, verify `gemini --version`, then start Bullpen.

Risks:

- Gemini CLI's exact headless flags and JSON output should be confirmed in a spike before implementation.
- If MCP config is project-level rather than per-run, Bullpen may need a temp config directory per invocation.
- The free preview/subscription terms and quota can change; the integration should make rate-limit errors clear.

## Priority 2: Cursor Agent CLI

### Why It Should Be Second

Cursor Agent CLI appears to be the fastest path to another high-capability coding-agent backend because its documented programmatic surface looks very similar to Claude CLI: `--print`, `--output-format`, JSON, and stream-JSON are documented for programmatic use. Cursor also has paid individual/team plans and a pricing policy that contemplates subscription fees, usage fees, and model-based pricing. That is compatible with Bullpen's model of launching a local CLI under the user's own subscription.

Cursor may be the easiest adapter to implement after Claude because `stream-json` can map directly to `format_stream_line()` and `parse_output()`.

### Terms And Usage Fit

This is a good fit if Bullpen requires the user to install Cursor Agent CLI and authenticate with their own Cursor account. Bullpen should not imply that Cursor editor-only features are available unless the CLI supports them, and should surface Cursor plan/usage exhaustion as provider errors.

### Implementation Architecture

Add `server/agents/cursor_adapter.py` as a process-backed adapter.

Responsibilities:

- Discover `cursor-agent`, `cursor`, or the documented agent binary name. Support `BULLPEN_CURSOR_PATH`.
- Launch in print/headless mode, not interactive TTY mode.
- Use `--output-format stream-json` by default.
- Pass model selection if the CLI supports a `--model` flag; otherwise treat the model dropdown as a "mode/default" selector or disable custom model selection for Cursor.
- Optionally configure MCP if Cursor Agent CLI can consume MCP servers in headless sessions.
- Parse JSON result events and stream tool/file/command events into Bullpen output.

Recommended adapter sketch:

```python
class CursorAdapter(AgentAdapter):
    @property
    def name(self):
        return "cursor"

    def available(self):
        return _find_cursor_agent() is not None

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        argv = [
            _find_cursor_agent() or "cursor-agent",
            "--print",
            "--output-format", "stream-json",
        ]
        if model:
            argv.extend(["--model", model])
        if bp_dir:
            argv.extend(self._mcp_args_or_config(bp_dir))
        return argv
```

Expected code changes:

- Add `cursor` to adapter registry, validation, worker config, chat tab, colors, and model metadata.
- Extend tests with sample `stream-json` result, tool, file edit, and failure events based on Cursor's documented schema.
- Add a provider capability flag: `supports_mcp`, `supports_model_selection`, `supports_structured_stream`, `supports_auto_edit`.
- Move provider/model options from static JS into a backend endpoint before this integration if possible; Cursor's model list may depend on account/plan.

Risks:

- Cursor's CLI may assume a Cursor project/index or editor-adjacent state. A spike should test a clean repo, non-interactive stdin, and concurrent runs.
- Cursor model usage may be metered differently by plan, so Bullpen should avoid presenting token accounting as exact unless Cursor emits usage.
- If Cursor's default mode asks for approvals, Bullpen needs either a documented auto-accept flag or a PTY/approval bridge.

## Priority 3: GitHub Copilot CLI / Coding Agent

### Why It Should Be Third

GitHub Copilot is broadly adopted, subscription-backed, and tightly integrated with developer accounts. GitHub's current coding-agent direction also includes agent sessions, VS Code integration, and access to multiple coding agents under Copilot plans. For Bullpen users who already pay for Copilot, this would be a compelling backend.

It ranks below Gemini and Cursor because Bullpen needs to verify the exact local CLI/headless contract. If the integration surface is a conversational CLI or Agent Client Protocol server rather than a simple "prompt in, stream JSON out" executable, it may require a larger runner abstraction.

### Terms And Usage Fit

This should be modeled as bring-your-own GitHub account/Copilot subscription. Bullpen should not automate account creation, bypass premium-request limits, or pool usage across users. Public-preview agent sessions and premium request accounting may change, so the integration should keep billing/limits text out of hard-coded UX and link users to GitHub's current docs.

### Implementation Architecture

Start with a spike, then choose one of two paths.

Path A: process-backed CLI adapter:

- Discover `gh` plus the Copilot extension or the documented Copilot CLI binary.
- Verify auth via `gh auth status` and Copilot subscription availability through the official command.
- Launch a non-interactive command that accepts prompt text and workspace context.
- Stream stdout/stderr into Bullpen.
- Parse terminal output or JSON if available.

Path B: protocol-backed adapter:

- Add a new `ProtocolAgentAdapter` interface for agents exposed through Agent Client Protocol or a local daemon.
- Keep Bullpen's worker state machine, but replace direct `Popen(argv)` with adapter-owned lifecycle methods:
  - `start(request) -> run_handle`
  - `stop(run_handle)`
  - `stream_events(run_handle)`
  - `finalize(run_handle) -> AgentResult`
- Map protocol events to Bullpen's existing `worker:output`, usage, success/failure, and cancellation flow.

Recommended near-term architecture:

```python
class AgentAdapter(ABC):
    def available(self): ...
    def kind(self): return "process"

class ProcessAgentAdapter(AgentAdapter):
    def build_argv(self, prompt, model, workspace, bp_dir=None): ...
    def parse_output(self, stdout, stderr, exit_code): ...

class ManagedAgentAdapter(AgentAdapter):
    def run(self, request, events): ...
    def stop(self, run_id): ...
```

Expected code changes:

- Refactor `server/workers.py` and chat execution around a common runner before adding Copilot if the spike shows a protocol/daemon shape.
- Add a `copilot` provider with capability metadata.
- Treat MCP as optional; Copilot may have native GitHub/repository tools rather than Bullpen MCP.
- Add explicit setup diagnostics, since GitHub auth/subscription failures are common and should block without retries.

Risks:

- The public-preview agent feature may not expose a stable local headless CLI suitable for Bullpen.
- GitHub agent sessions may be oriented around issues/PRs rather than arbitrary local tickets.
- Usage accounting may be premium-request based rather than token-based.

## Providers Considered But Not Top Three

### OpenRouter

OpenRouter is useful but should not be next if the goal is "another Claude/Codex-like worker." It is an OpenAI-compatible model router, not a coding-agent CLI. Bullpen could call OpenRouter directly or use it through Aider/Qwen Code, but direct integration means Bullpen must build or adopt a coding-agent loop: file discovery, read/write tools, shell execution, approvals, patching, retry semantics, prompt-injection controls, and MCP/ticket tools.

Best fit:

- Later "model router" backend after Bullpen has `ManagedAgentAdapter` or tool-loop support.
- Pair with Aider or Qwen Code if Bullpen wants a process-backed coding agent that uses OpenRouter underneath.

Architecture if pursued:

- Add an `openai_compatible` HTTP adapter with configurable `base_url`, `api_key_env`, model list, and provider headers.
- Initially expose it as text/chat/planning only, not an autonomous code-editing worker.
- Later add a Bullpen-owned tool loop with constrained `read_file`, `search_files`, `propose_patch`, and ticket MCP tools.

### ChatGPT / OpenAI Beyond Current Codex

Bullpen already has the correct OpenAI-shaped coding integration: Codex CLI. ChatGPT itself is not the right backend unless OpenAI exposes a supported headless ChatGPT/Codex agent CLI surface distinct from `codex`. Direct OpenAI API integration would be powerful, especially with Responses API and Agents SDK, but it falls into the same "Bullpen owns the coding-agent loop" category as OpenRouter.

Best fit:

- Keep investing in the existing `codex` adapter.
- Add a provider health/setup page for Codex auth and available models.
- Consider OpenAI API/Agents SDK later for a Bullpen-native managed agent, not as the next process adapter.

### Windsurf

Windsurf/Cascade is a capable coding product, but the public docs are primarily editor-centric. The docs describe editor commands, Cascade, prompt credits, and IDE workflows rather than a stable headless coding-agent CLI. Without a documented non-interactive CLI, Bullpen should not automate Windsurf by scripting the editor or relying on private internals.

Best fit:

- Watchlist only.
- Reconsider if Windsurf documents a local agent CLI with headless mode, structured output, and subscription-compliant automation.

### Aider

Aider is a mature CLI coding assistant and can use many model providers, including OpenRouter, OpenAI, Anthropic, Gemini, and local models. It is relevant because it can turn API-only providers into a process-backed coding agent. It is not a provider itself, and subscription friendliness depends on the underlying model/API account.

Best fit:

- Add as an "agent runtime" after provider metadata exists.
- Consider as the OpenRouter bridge if Bullpen wants broad model choice without building a native tool loop.

### Amazon Q Developer / Kiro

Amazon's developer-agent story is worth watching, especially if a stable Kiro CLI or Amazon Q CLI exposes local headless coding-agent execution under a developer subscription. It is not in the top three here because Gemini, Cursor, and Copilot are clearer fits to Bullpen's immediate adapter path.

### Qwen Code

Qwen Code is an interesting open-source coding CLI, especially for Qwen Coder models and OpenAI-compatible gateways. It may become a useful provider-agnostic runtime, similar to Aider. It is lower priority because subscription/account and enterprise data-handling fit depend on the gateway or model backend a user chooses.

## Cross-Cutting Architecture Recommendation

Before adding more than one new backend, Bullpen should split "provider metadata" and "agent execution kind" out of the current hard-coded UI and process-only adapter interface.

### Provider Metadata

Add a backend endpoint or Socket.IO event:

```json
{
  "providers": [
    {
      "id": "claude",
      "label": "Claude",
      "models": ["claude-sonnet-4-6"],
      "capabilities": {
        "process": true,
        "structured_stream": true,
        "mcp": true,
        "workspace_edit": true,
        "usage": true
      }
    }
  ]
}
```

Use this in:

- Worker config provider/model dropdowns.
- Live chat provider/model dropdowns.
- Validation.
- Provider badges/colors.
- Capability warnings for text-only or non-editing providers.

### Adapter Interface

Introduce two adapter families:

- `ProcessAgentAdapter`: current Claude/Codex/Gemini/Cursor path.
- `ManagedAgentAdapter`: future API/protocol agents such as OpenRouter-native, OpenAI Agents SDK, Copilot protocol integration, or native Ollama tool loop.

The worker and chat runners should consume a normalized stream of events:

```python
{"type": "text", "text": "..."}
{"type": "tool", "name": "Bash", "summary": "..."}
{"type": "file_change", "path": "...", "action": "modified"}
{"type": "usage", "usage": {...}}
{"type": "result", "success": True, "output": "..."}
```

That lets Bullpen keep the same UI and task state machine while adding providers with different execution models.

### Setup And Safety

For every new provider:

- Add an explicit `unavailable_message()` with setup commands and auth checks.
- Block startup failures without retrying, as Bullpen already does for missing Claude/Codex binaries.
- Keep auto-commit/auto-PR enabled only for providers with `workspace_edit=true`.
- Track provider/model in usage entries even when token counts are unavailable.
- Add per-provider concurrency notes; subscription CLIs may rate-limit parallel workers.
- Avoid editor automation or unofficial private APIs.

## Recommended Sequence

1. Add backend provider metadata and remove hard-coded frontend provider lists.
2. Implement Gemini CLI as the first new process adapter.
3. Implement Cursor Agent CLI using its stream-JSON mode.
4. Spike GitHub Copilot CLI/agent headless behavior; implement either a process adapter or the first managed/protocol adapter.
5. Revisit OpenRouter and OpenAI API as native managed agents only after Bullpen has an explicit tool-loop architecture.

## Source Notes

- Bullpen current code: `server/agents/base.py`, `server/agents/claude_adapter.py`, `server/agents/codex_adapter.py`, `server/workers.py`, `server/events.py`, `server/validation.py`, `static/utils.js`, `static/components/WorkerConfigModal.js`, `static/components/LiveAgentChatTab.js`.
- Gemini CLI: <https://github.com/google-gemini/gemini-cli>, <https://blog.google/technology/developers/introducing-gemini-cli-open-source-ai-agent/>
- Cursor Agent CLI docs: <https://docs.cursor.com/cli>, <https://docs.cursor.com/cli/reference/output-format>
- Cursor pricing/terms: <https://cursor.com/terms/pricing/>
- GitHub Copilot docs: <https://docs.github.com/en/copilot/how-tos/copilot-cli>, <https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically>
- OpenRouter docs/privacy: <https://openrouter.ai/docs>, <https://openrouter.ai/privacy>
- OpenAI service terms: <https://openai.com/api/policies/service-terms/>
- Windsurf docs/usage: <https://docs.windsurf.com/>, <https://docs.windsurf.com/windsurf/accounts/usage>
- Aider docs: <https://aider.chat/docs/>
