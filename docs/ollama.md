# Ollama Local Model Backend Analysis

## Executive Summary

Bullpen currently treats an "agent" as a local CLI program that can be launched as a subprocess, receive a fully assembled prompt on stdin, stream stdout/stderr, and optionally use Bullpen's MCP ticket tools. Claude and Codex fit that shape because their CLIs are agentic execution environments. Ollama is different: it is primarily a local model server with an HTTP API. It can generate text, but it does not natively provide file-editing tools, shell access, MCP tool use, or agent planning loops.

Adding Ollama as a backend is still valuable, but it should be framed as a local model provider, not an equivalent replacement for Claude/Codex agent CLIs. The right first version is an Ollama adapter for task analysis, chat, drafting, review, summarization, and constrained text output. Direct code editing, repository manipulation, and MCP ticket operations require an agent loop owned by Bullpen or by another coding-agent runtime.

That agent path is real, not hypothetical. Ollama supports function/tool calling and documents single-shot calls, parallel calls, streaming tool calls, and a multi-turn "agent loop" where the host application executes approved tools and feeds results back into the model. The consequence for Bullpen is subtle but important: Ollama can be the reasoning/model component in a local agent, but Bullpen must still provide the loop, tool schemas, validation, permissions, cancellation, and audit trail.

The recommended design is to evolve the adapter layer from "build argv and parse subprocess output" into an execution interface that supports both subprocess-backed agents and HTTP-streaming model providers. A compatibility wrapper process is possible, but it would preserve the current abstraction at the cost of hiding cancellation, streaming, configuration, and error handling behind an unnecessary subprocess.

## Current Agent Shape

The existing backend is in `server/agents/` and `server/workers.py`.

| Area | Current behavior | Ollama implication |
| --- | --- | --- |
| Adapter contract | `AgentAdapter.build_argv(prompt, model, workspace, bp_dir)` returns a command list. `parse_output(stdout, stderr, exit_code)` converts process output into `{success, output, error}`. | Ollama has no argv. The adapter contract needs an HTTP execution path or a local wrapper process. |
| Worker execution | `start_worker()` assembles one prompt, creates optional git worktree, builds argv, then `_run_agent()` starts a subprocess and drains stdout/stderr. | HTTP streaming should be cancellable and emit the same `worker:output` events. |
| Chat execution | Live chat uses `_run_chat()`, also subprocess-based. It handles Claude-specific MCP startup states and streams formatted lines into `chat:output`. | Chat can map naturally to Ollama `/api/chat`, but history should be sent as messages instead of one concatenated prompt. |
| Tool access | Claude/Codex get Bullpen MCP configuration so agents can create/list/update tickets. | Ollama does not automatically speak MCP. Tool use requires a Bullpen-managed loop or must be disabled. |
| Workspace/file access | Claude/Codex CLIs can inspect/edit files under the workspace, subject to their own tooling and permissions. | Ollama only sees prompt text unless Bullpen supplies file content or executes tools on its behalf. |
| Model selection | UI hard-codes Claude/Codex provider and model options; custom model is possible in worker config. Validation only allows `claude` and `codex`. | Add `ollama` provider, local model discovery, and longer model string limits if needed. |
| Availability | CLI adapters use `shutil.which()`. | Ollama availability is an HTTP health/version/model-list check, usually against `http://127.0.0.1:11434`. |

## Product Positioning

Ollama should be introduced with explicit capability boundaries.

Good first-fit uses:

- Local/private task discussion.
- Ticket drafting and decomposition.
- Code review suggestions when relevant files are included in prompt context.
- Summarization of agent output or long ticket bodies.
- Architecture notes, implementation plans, release notes, and documentation drafts.
- Low-cost background workers that move tickets to review with written analysis.

Poor first-fit uses without a tool loop:

- Autonomous code edits.
- Running tests.
- Creating commits or PRs.
- Inspecting arbitrary repository files beyond what Bullpen injects into the prompt.
- Using Bullpen MCP tools directly.
- Reliable multi-step remediation on large codebases.

This distinction matters because Bullpen's worker UX currently implies "agent execution" rather than "model response." An Ollama worker can be useful, but a local model that only writes text should not be presented as having the same powers as Claude/Codex.

## Agent-Based Contexts For Local Models

There are several legitimate agent contexts for local/Ollama-hosted models. They vary in how much of the agent loop they provide.

| Context | What it provides | Bullpen relevance |
| --- | --- | --- |
| Native Ollama tool loop | Ollama's `/api/chat` can return tool calls. The host app executes tools, appends `tool` messages, and repeats until no tool calls remain. Ollama documents this as an agent loop, including streaming tool-call accumulation. | Best long-term fit if Bullpen wants tight control over ticket/file tools, permissions, and UI state. |
| LangChain / LangGraph | `ChatOllama` supports streaming, tool calling, structured output, and can be embedded in framework-managed agent/graph workflows. | Useful if Bullpen wants a mature orchestration layer, but it adds a dependency and another abstraction around tools. |
| LlamaIndex | Ollama integration supports chat/streaming/structured prediction patterns and can sit inside RAG/query-agent workflows. | Useful for retrieval-heavy local agents that need indexed workspace context before answering. |
| CrewAI | Role/task-oriented multi-agent orchestration can use local Ollama models through LLM configuration. | Conceptually close to Bullpen's worker/team metaphor, but it may overlap with Bullpen's own scheduler and worker model. |
| AutoGen-style multi-agent loops | Local models can be used through OpenAI-compatible bridges or custom model clients. | More relevant if Bullpen wants conversational multi-agent debate/coordination rather than direct ticket workers. |
| Aider with Ollama | Aider is a coding-agent CLI that can use Ollama models and edit a repository. Its docs recommend `ollama_chat/<model>` and call out context-window pitfalls. | The closest off-the-shelf local coding-agent option. Bullpen could integrate Aider as another process-backed adapter instead of building a full code-editing loop itself. |

Useful references:

- Ollama tool calling and agent loop: <https://docs.ollama.com/capabilities/tool-calling>
- LangChain ChatOllama: <https://docs.langchain.com/oss/python/integrations/chat/ollama/>
- LangChain model capability table: <https://docs.langchain.com/oss/python/integrations/chat/>
- LlamaIndex Ollama integration: <https://docs.llamaindex.ai/en/stable/api_reference/llms/ollama/>
- Aider with Ollama: <https://aider.chat/docs/llms/ollama.html>

The design lesson is that Bullpen has two plausible local-model tracks:

- Native Bullpen tool loop: Ollama is the model; Bullpen owns tools, safety, state, and ticket updates.
- External coding-agent adapter: Aider or a similar runtime is the agent; Bullpen launches it like Claude/Codex and treats it as a process-backed worker.

The first track offers better product integration and safety control. The second track may reach practical code-editing sooner, but Bullpen must accept the external agent's behavior and output format.

## Recommended Architecture

### Split Agent Execution From Process Execution

Introduce an execution abstraction that can stream output from either a subprocess or an HTTP API. For example:

```python
class AgentAdapter(ABC):
    name: str

    def available(self) -> bool: ...

    def execute(self, request: AgentRequest) -> AgentResult:
        """Run the agent/model and yield stream events or callbacks."""
```

Or, less invasively:

- Keep `build_argv()` for `ProcessAgentAdapter`.
- Add `run()` or `stream()` for adapters that implement direct execution.
- Update `workers.py` and chat code to call a common runner that can dispatch to process or HTTP adapters.

Recommended request shape:

```python
@dataclass
class AgentRequest:
    prompt: str
    model: str
    workspace: str
    bp_dir: str | None
    timeout_seconds: int
    context: dict
    emit_line: Callable[[str], None]
    should_cancel: Callable[[], bool]
```

Recommended result shape:

```python
@dataclass
class AgentResult:
    success: bool
    output: str
    error: str | None = None
    usage: dict | None = None
```

This keeps worker success/failure, retries, output appending, auto-commit hooks, and socket emits in the existing worker state machine, while letting adapters differ in how they produce text.

### Ollama Adapter

Add `server/agents/ollama_adapter.py`.

Core responsibilities:

- Read base URL from config, defaulting to `http://127.0.0.1:11434`.
- Check availability through a lightweight HTTP request.
- List local models, ideally from Ollama's model listing endpoint.
- Stream generation responses and pass text chunks to Bullpen's existing `worker:output` / `chat:output` flow.
- Convert Ollama errors into ordinary agent errors so the existing retry/block logic works.
- Track usage when available; otherwise return an empty usage dict.
- Respect `agent_timeout_seconds`.
- Support cancellation when a worker/chat is stopped.

Use the standard library `urllib.request` if avoiding dependencies is important. If the project accepts a new dependency, `requests` or `httpx` makes streaming and timeouts cleaner. Since `requirements.txt` is currently very small, dependency cost should be considered explicitly.

### API Mode

Prefer Ollama's chat-style API for live chat because Bullpen already has role-based history. For workers, either chat or generate style can work:

- Worker prompt as a single user message is simplest.
- A system message can hold Bullpen's role/expertise context if the prompt assembly is later split into structured pieces.
- Chat history is not needed for one-shot worker tasks.

The adapter should set `stream: true` for responsive UI output. It should also expose configurable options such as:

- `temperature`
- `top_p`
- `num_ctx`
- `num_predict`
- `keep_alive`

Do not expose all Ollama options in the first UI. Store advanced options as loose JSON config if needed.

### Prompt Strategy

Current `_assemble_prompt()` produces one large prompt:

- Workspace prompt.
- Bullpen prompt.
- Expertise prompt.
- Task title/type/priority/tags/body.

That is acceptable for the first Ollama worker version. However, local models have practical context limits and weaker repository awareness, so the prompt should be more explicit about output expectations:

- "You do not have direct filesystem access unless file contents are included below."
- "Return an implementation plan or patch-style guidance; do not claim to have edited files."
- "If code changes are needed, identify exact files and snippets."

Without this, an Ollama worker may hallucinate completed work and Bullpen may move the ticket to review as if execution occurred.

### Tool Use, MCP, and Agent Loops

Ollama does not automatically use Bullpen MCP tools the way Claude/Codex CLIs do, but it does support model-emitted tool calls. There are four possible levels:

1. No tools: Ollama returns text only. This is the right first version.
2. Native Ollama tool loop: Bullpen sends JSON-schema tools to Ollama, validates returned tool calls, executes approved local functions, appends tool results, and iterates.
3. Framework-owned loop: LangChain, LlamaIndex, CrewAI, or AutoGen owns part of the agent loop and calls Bullpen-provided tools.
4. External coding-agent adapter: Bullpen launches a local coding agent such as Aider configured to use Ollama.

Level 2 is the most controllable long-term design. It maps directly to Ollama's documented agent-loop pattern, but it is still a separate feature from basic generation. It requires schemas, validation, loop limits, prompt-injection safeguards, workspace path controls, cancellation, output caps, and a clear UI story for what tools a local model can run.

Until then, Ollama workers should not be able to use MCP tools directly and should not be advertised as autonomous coding workers.

Recommended first Bullpen-owned tools, in order:

- `list_tickets` / `read_ticket` / `update_ticket`, because these stay inside Bullpen's existing domain.
- `read_file` with strict workspace path validation and size limits.
- `search_files` backed by `rg`-style bounded search.
- `propose_patch` that returns a patch for human or Bullpen validation, rather than directly writing files.
- `apply_patch` only after the model can reliably produce bounded patch proposals and the UI can expose approvals/audit.

Keep shell execution out of the first local-model tool loop. Running arbitrary commands is the major boundary between "local model assistant" and "autonomous coding agent."

## Required Code Changes

### Adapter Registry

Update `server/agents/__init__.py`:

- Import and register `OllamaAdapter`.
- Add model discovery helper if the frontend will ask the backend for provider/model options.
- Preserve `register_adapter()` for tests.

### Agent Interface and Worker Runner

`server/workers.py` currently assumes every adapter returns argv. It needs one of these changes:

- Best: introduce a common `run_agent_request()` function that can call either `adapter.execute()` or the existing subprocess path.
- Conservative: make `OllamaAdapter.build_argv()` point to a small `server/agents/ollama_runner.py` script that reads stdin and streams HTTP output to stdout.

The conservative wrapper reduces refactor size, but it is a compromise. A direct HTTP adapter gives cleaner stop/cancel behavior and avoids starting an extra Python process for every local model call.

Recommended direct changes:

- Add `adapter.kind` or capability method such as `supports_direct_execution`.
- Refactor `_run_agent()` into process-specific `_run_process_agent()` plus generic completion handling.
- Add `_run_direct_agent()` for HTTP adapters.
- Store active cancel handles for direct agents in `_processes` or a renamed `_active_runs` map, so `stop_worker()` and `chat:stop` can cancel both process and HTTP runs.

### Live Chat

`server/events.py` has a second subprocess runner for chat. It should share the same generic execution path as workers or get a parallel direct HTTP path.

Changes:

- Add `ollama` to `LiveAgentChatTab.providerOptions`.
- Add model options or dynamic model loading.
- For Ollama, send role messages to the adapter rather than flattening all history into one prompt if the adapter supports chat messages.
- Disable Claude-specific MCP startup handling for Ollama.
- Track active Ollama chat request cancellation separately from `_chat_processes`, or generalize `_chat_processes` to `_chat_runs`.

### Validation

Update `server/validation.py`:

- Add `ollama` to `VALID_AGENTS`.
- Consider increasing model length beyond 50. Local model identifiers can include tags and custom names; 50 may be enough for common names, but 100 is safer.
- Consider adding validation for Ollama base URL in config.

### Config

Add durable config keys:

```json
{
  "ollama": {
    "base_url": "http://127.0.0.1:11434",
    "default_model": "llama3.1:8b",
    "request_timeout_seconds": 600,
    "options": {
      "temperature": 0.2,
      "num_ctx": 8192
    }
  }
}
```

Because `validate_config_update()` currently only accepts a small set of top-level keys, it must allow either `ollama` or specific `ollama_*` keys.

Avoid binding to `0.0.0.0` by default. Ollama should remain loopback-only unless the user explicitly configures a remote server.

### Frontend

Update static frontend code:

- `static/components/WorkerConfigModal.js`: add Ollama provider option and common local model presets, plus custom model support.
- `static/components/LiveAgentChatTab.js`: add Ollama provider and model options.
- `static/utils.js`: add an Ollama color.
- Consider a provider capability hint: "text only" versus "workspace agent" so users understand what an Ollama worker can do.
- Longer term: fetch provider/model lists from the backend instead of hard-coding model names in multiple components.

Dynamic model discovery would be much nicer for Ollama because available models are local and user-specific. A small endpoint or Socket.IO event can return:

```json
{
  "providers": [
    {"id": "claude", "models": [...]},
    {"id": "codex", "models": [...]},
    {"id": "ollama", "models": ["llama3.1:8b", "qwen2.5-coder:7b"]}
  ]
}
```

### Profiles

Built-in profiles currently default to Claude. Do not mass-convert them. Instead:

- Allow users to save Ollama-backed custom profiles through the existing "Save as Profile" path.
- Optionally add a few explicit local profiles later, such as "Local Reviewer" or "Local Planner".
- Keep `default_agent`/`default_model` fields; they are already provider-neutral enough.

### Auto-Commit, Auto-PR, and Worktrees

Auto-commit and worktree options should be treated carefully.

For a text-only Ollama backend:

- `use_worktree` does not add much value unless the model can edit files through a tool loop.
- `auto_commit` should usually be disabled or no-op because no file changes are expected.
- `auto_pr` should be disabled unless a future tool loop can actually modify files.

The existing code will attempt auto-commit after a successful worker run regardless of provider. That is safe if there are no changes, but it may be confusing. The UI should either disable these controls for text-only providers or show a capability warning.

For an external coding-agent adapter such as Aider-with-Ollama, worktrees and auto-commit become useful again because the process can actually modify files. That should be represented as a different capability profile from raw Ollama chat/generate.

## Security and Safety Considerations

Local models feel private, but adding them as workers still changes the risk profile.

- Prompt injection: if file contents or ticket text ask the model to invoke tools, Bullpen must not execute those instructions unless a tool loop explicitly validates them.
- Network exposure: default Ollama URL should be loopback. Remote URLs should be opt-in and clearly visible.
- Data leakage: if a user points Bullpen at a remote Ollama-compatible endpoint, workspace prompts and task bodies may leave the machine.
- Tool execution: any future tool loop must whitelist tools, validate paths with `ensure_within()`, enforce payload limits, and avoid arbitrary shell execution by default.
- Tool-call trust boundary: model-emitted tool calls are requests, not commands. Bullpen must validate every name and argument before execution, even when using native Ollama tool calling or a framework agent.
- Resource exhaustion: local model calls can consume CPU/GPU/RAM for long periods. Timeouts, cancellation, and queue visibility are important.
- Concurrent model runs: multiple Bullpen workers can start at once. Local hardware may not handle parallel generations well. Add a configurable Ollama concurrency limit, likely defaulting to 1.

## Testing Changes

Add tests at several layers:

- `OllamaAdapter.available()` handles server available/unavailable.
- Streaming parser converts newline-delimited JSON chunks into display lines.
- Final output aggregation preserves streamed text.
- HTTP errors, malformed JSON, timeout, and cancellation become ordinary agent errors.
- Worker success path appends Ollama output to task body.
- Worker stop cancels an active Ollama request and returns task to assigned or blocked consistently.
- Validation accepts `ollama` and rejects invalid provider names.
- UI source tests include Ollama provider/model entries.
- Live chat can send an Ollama request without Claude-specific MCP startup logic.
- Native tool-loop tests cover invalid tool names, invalid arguments, loop limit exhaustion, tool output caps, and cancellation between tool calls.
- External-agent adapter tests, if adding Aider or similar, treat it as a separate process-backed adapter rather than as the raw Ollama adapter.

Use a fake local HTTP server or monkeypatched adapter transport for tests. Do not require a real Ollama installation in CI.

## Open Questions

- Should Ollama be labeled as an "AI Provider" beside Claude/Codex, or as a separate "Local Model" mode with explicit reduced capabilities?
- Should workers with text-only providers be allowed to route tickets to `done`, or should they default to `review` to avoid implying code was changed?
- Should the first version support only chat/generate, or also a Bullpen-managed tool loop for file reads?
- Should Bullpen build its own Ollama tool loop first, or add Aider/Ollama as a process-backed local coding-agent adapter first?
- Should model discovery happen eagerly on app load, lazily when a provider dropdown opens, or through a manual refresh button?
- Should Bullpen support any OpenAI-compatible local endpoint under the same adapter, or keep this specifically Ollama until the abstractions settle?
- Should local model concurrency be global across workspaces or per workspace?

## Prioritized Work Plan

### Tranche 1: Provider Plumbing and Capability Model

- Add `ollama` as a recognized provider in validation and frontend dropdowns.
- Add provider capability metadata: process-backed agent vs text-only local model.
- Add Ollama config defaults for base URL, default model, timeout, and basic options.
- Add tests for validation and UI/provider registration.

### Tranche 2: Ollama Adapter MVP

- Implement `server/agents/ollama_adapter.py` with availability check and streaming generation.
- Refactor worker execution enough to support direct HTTP adapters, or add a temporary local runner script if minimizing refactor.
- Emit the same `worker:output`, `worker:output:done`, `task:updated`, and error flows as existing agents.
- Ensure `stop_worker()` can cancel active Ollama runs.

### Tranche 3: Live Chat Support

- Add Ollama to `LiveAgentChatTab`.
- Send chat history as structured messages when using Ollama.
- Share cancellation and streaming code with worker execution where practical.
- Log chat transcripts to tickets as today.

### Tranche 4: Model Discovery and Settings UI

- Add backend provider/model metadata endpoint or Socket.IO event.
- List installed Ollama models dynamically.
- Add a small settings path for Ollama base URL and default options.
- Handle server unavailable states cleanly in the UI.

### Tranche 5: Safer Worker UX

- Mark Ollama workers as text-only unless a tool loop is enabled.
- Disable or warn on worktree/auto-commit/auto-PR for text-only providers.
- Adjust prompts so Ollama does not claim to have edited files.
- Add optional local-model-specific profiles.

### Tranche 6: Optional Tool Loop

- Define a strict native Ollama tool schema for ticket operations, file read/search, and maybe patch proposal.
- Add loop limits, tool allowlists, path validation, output caps, and audit logging.
- Support streaming tool calls by accumulating partial content/tool-call fields before executing a tool.
- Keep shell execution out of scope initially.
- Revisit whether Ollama workers can become autonomous coding workers after this is reliable.

### Tranche 7: External Local Coding Agents

- Evaluate Aider with Ollama as a separate process-backed adapter.
- Decide whether Bullpen should support Aider's model naming/config conventions directly, such as `ollama_chat/<model>`.
- Preserve Bullpen's existing worktree, stop, output, retry, auto-commit, and auto-PR flows around the external process.
- Compare the result against the native Bullpen tool loop before making it the recommended local coding path.

## Recommended First Implementation Choice

Implement Ollama first as a text-only local model provider with direct HTTP streaming, not as a fake Claude/Codex equivalent. Refactor the adapter layer just enough to support non-subprocess execution, add provider capability metadata, and keep the worker/chat socket payloads unchanged.

That gives Bullpen a genuinely useful local/offline/private backend quickly while avoiding the trap of implying that a raw local model can safely edit a repository or use MCP tools. Once that baseline is stable, the next decision is between a native Bullpen-owned Ollama tool loop and an external coding-agent adapter such as Aider. Both are valid agent-based contexts; they should be modeled explicitly so users understand what each worker can actually do.
