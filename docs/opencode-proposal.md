# Integrate opencode as a Bullpen Provider

## Overview

Add `opencode` as a first-class AI provider in Bullpen, alongside the existing
`claude`, `codex`, and `gemini` providers. opencode is a CLI agent that wraps
multiple model backends (Anthropic, Google, OpenAI, etc.) behind a single
`opencode run` interface, supports `--format json` for structured output, and
is installed via `npm install -g @opencode-ai/cli`.

## Functional Proposal

### User Experience

A new `opencode` option appears in the provider dropdown when creating or
editing an AI worker slot. The user selects an opencode worker just like they
select a Claude or Codex worker today.

What changes for the user:

- **Provider selection**: "opencode" is a new choice in the worker provider
  picker, with an associated color (`#63b3ed` — light blue) and icon.
- **Model selection**: Model names follow the `provider/model` convention
  accepted by opencode's `--model` flag (e.g., `anthropic/claude-sonnet-4-6`,
  `google/gemini-2.5-flash`, `openai/gpt-5.4`). Model aliases map shorthand
  names (`opus`, `sonnet`, `flash`, `gpt-5`) to fully-qualified IDs.
- **Profiles**: Existing Bullpen profile JSONs (which contain system prompts)
  are passed to opencode as the prompt, same as for other providers.
- **Focus view streaming**: The opencode adapter produces structured JSON
  output via `--format json` that the focus view parses for real-time
  streaming of assistant text, tool calls, and tool results.
- **Usage tracking**: Token usage emitted in opencode's JSON result line is
  captured and surfaced in the ticket stats panel.

### Provider Auth Compared to Existing Providers

| Provider   | Auth Model                              | Sandbox Setup                    |
|------------|-----------------------------------------|----------------------------------|
| claude     | OAuth via `claude auth login`           | Interactive `claude auth login`  |
| codex      | OAuth via `codex auth login`            | Interactive `codex auth login`   |
| gemini     | API key via `GOOGLE_API_KEY` env var    | Set env var, no interactive step |
| **opencode** | Provider-native auth (API keys or OAuth per provider) | Install + provider config |

opencode delegates auth to its underlying model provider. The user configures
opencode's provider settings (e.g., `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, etc.) via environment variables or opencode's own config
file (`opencode.json`). Bullpen injects these into the subprocess environment
via the adapter's `prepare_env()` hook, similar to how the Gemini adapter
injects `GOOGLE_API_KEY`.

### Trust Model Compatibility

Bullpen's trust model applies equally to opencode workers. When trust mode is
"untrusted," Bullpen wraps the prompt with trust-boundary instructions and may
inject restrictions into the opencode argv (via `harden_agent_argv()`). The
`--dangerously-skip-permissions` flag is forwarded only when trust mode allows
it.

## Design

### Adapter Implementation

A new file `server/agents/opencode_adapter.py` implements `AgentAdapter`:

```
server/agents/
  __init__.py            # register OpenCodeAdapter
  base.py                # AgentAdapter ABC (unchanged)
  claude_adapter.py      # existing
  codex_adapter.py       # existing
  gemini_adapter.py      # existing
  opencode_adapter.py    # NEW
```

**`OpenCodeAdapter` key methods:**

| Method                  | Behavior |
|-------------------------|----------|
| `name`                  | `"opencode"` |
| `available()`           | `shutil.which("opencode") is not None` |
| `build_argv(prompt, model, workspace, bp_dir)` | Builds `["opencode", "run", "--format", "json", "--dangerously-skip-permissions", "--model", model]`. Prompt via stdin. If `bp_dir` provided, generates a temp opencode MCP config so the agent can use Bullpen's MCP tools. |
| `format_stream_line(line)` | Parses JSON lines from `--format json`. Routes event types to focus view display text (assistant text, tool calls, tool results, errors). |
| `parse_output(stdout, stderr, exit_code)` | Extracts the final result from the last JSON event. Returns `{success, output, error, usage}`. |
| `prompt_via_stdin()`  | `True` — prompt is written to subprocess stdin. |
| `prepare_env(workspace, bp_dir, task_id)` | Injects provider auth env vars (API keys) from Bullpen's runtime env. Creates isolated temp dir for opencode's working state. |

The adapter follows the same pattern as `ClaudeAdapter` for:
- Isolated temp directory per run (cleanup handled by the worker runner).
- MCP config file generation so opencode can call Bullpen's ticket tools.
- OAuth refresh coordination (if applicable — opencode itself does not do
  OAuth, but its underlying provider config may need similar mirroring).

### Execution Flow

```
User clicks "Run" on an opencode worker slot
  │
  ▼
worker_types.py → get_worker_type("ai")       (unchanged)
  │
  ▼
workers.py → _run_agent()                     (unchanged)
  │
  ▼
get_adapter("opencode")
  │
  ▼
OpenCodeAdapter.prepare_env()
  → injects OPENCODE_CONFIG / env vars
  → creates isolated temp dir
  │
  ▼
OpenCodeAdapter.build_argv()
  → ["opencode", "run", "--format", "json",
     "--dangerously-skip-permissions",
     "--model", "anthropic/claude-sonnet-4-6"]
  │
  ▼
SubprocessRunner executes argv in workspace cwd
  → writes prompt to subprocess stdin
  → streams stdout line-by-line
  → each line → format_stream_line() → focus view
  │
  ▼
On exit → parse_output() → {success, output, error, usage}
  │
  ▼
_on_agent_success() or _on_agent_error()       (unchanged)
```

### Streaming Output Format

opencode's `--format json` produces one JSON object per line. The adapter
maps event types to focus view display:

| opencode JSON event type | Focus View Display |
|--------------------------|---------------------|
| `"message"` with text blocks | Rendered markdown text |
| `"message"` with tool_use blocks | Compact tool summaries (e.g., `$ git log`, `[Edit] path`) |
| `"tool_result"` | Tool output text (truncated at 2000 chars) |
| `"result"` | Consumed by `parse_output`; not displayed |
| `"error"` | Error text, marked as error |
| Non-JSON or unknown | Passed through raw |

### Model Aliases

opencode accepts model strings in `provider/model` format (e.g.,
`anthropic/claude-sonnet-4-6`, `google/gemini-2.5-flash`), so unlike the
existing providers there is **no need for alias resolution** — the model
string is passed through as-is to `opencode run --model`.

Add a `"opencode"` section to `server/model_aliases.py` for any future
shorthand names, but the initial adapter sends the raw model string to the
CLI without transformation.

### Model List Management (360+ Models)

opencode exposes 350+ models from multiple backends (Anthropic, Google,
OpenAI, OpenRouter, etc.), and the list changes frequently as models are
added, deprecated, and user auth at OpenRouter changes. The existing Bullpen
model selector — a hardcoded `MODEL_OPTIONS` constant feeding a plain
`<select>` — is not designed for dynamic lists of this scale.

**Design decision: curated subset + free-text custom input.**

| Layer | Approach |
|-------|----------|
| **Frontend dropdown** | A curated subset of ~6 popular model slugs (e.g., `anthropic/claude-sonnet-4-6`, `google/gemini-2.5-flash`, `openai/gpt-5.4`). This is comparable to the current 6 Claude / 5 Codex / 3 Gemini entries. |
| **Custom input** | The existing `__custom__` option in the `<select>` reveals a free-text `<input>` for any arbitrary `provider/model` string. This handles the long tail of 350+ models without any UI changes — the server accepts any string. |
| **Backend validation** | `normalize_model()` passes unknown slugs through unchanged; the adapter passes the raw model string to `--model`. No server-side model catalog validation is required. |
| **Future enrichment** | If needed, a backend endpoint (`/api/models?provider=opencode`) can run a cached `opencode models list` and return results. The frontend `<select>` could then be replaced with a searchable/typeahead component. This is deferred — not required for initial integration. |

The curated subset lives in `MODEL_OPTIONS` in `static/utils.js` alongside
the existing providers. Example entry:

```javascript
opencode: [
  'anthropic/claude-sonnet-4-6',
  'anthropic/claude-opus-4-7',
  'google/gemini-2.5-flash',
  'google/gemini-2.5-pro',
  'openai/gpt-5.4',
  'openai/gpt-5.5',
],
```

**Why this works:** opencode is a multi-provider CLI. Users who want
`openrouter/anthropic/claude-sonnet-4` or `google/gemini-3-flash-preview`
type it in the custom field — the same mechanism that already exists for
every provider today. The curated set covers the 90% use case; the custom
input covers the rest. No new UI components, no backend endpoints, no model
catalog synchronization.

### Provider Color & UI

Three frontend files need updating alongside the server-side color default.

**1. `server/init.py`** — Add the default color so new workspaces pick it up:

```python
DEFAULT_PROVIDER_COLORS = {
    ...
    "opencode": "#63b3ed",
}
```

**2. `static/utils.js`** — Add to the hardcoded `DEFAULT_AGENT_COLORS` map
that the frontend uses as the single source of truth for provider-to-color
lookup:

```javascript
const DEFAULT_AGENT_COLORS = {
  claude: '#da7756',
  codex: '#5b6fd6',
  gemini: '#3c7bf4',
  opencode: '#63b3ed',    // NEW
  shell: '#64748b',
  service: '#0f766e',
  marker: '#c8b38c',
};
```

Without this, the frontend never sees the opencode color and falls back
to gray `#6B7280` on every card, swatch, and minimap dot.

**3. `static/components/WorkerConfigModal.js`** — Add the option to the
provider `<select>` so it appears in the worker-creation dropdown:

```html
<select class="form-select" v-model="form.agent" @change="onAgentChange">
  <option value="claude">Claude</option>
  <option value="codex">Codex</option>
  <option value="gemini">Gemini</option>
  <option value="opencode">OpenCode</option>     <!-- NEW -->
</select>
```

**4. `static/components/TopToolbar.js`** — Add to the hardcoded iteration
array that renders the color-picker menu rows:

```javascript
<div class="provider-colors-row"
     v-for="agent in ['claude','codex','gemini','opencode','shell','service','marker']"
     :key="agent">
```

All four locations must be updated together — the backend default, the
JS color map, the provider dropdown, and the toolbar color menu.

## Technical Specification

### File Changes

```
NEW  server/agents/opencode_adapter.py        ~180 lines
EDIT server/agents/__init__.py                 +3 lines
EDIT server/model_aliases.py                   +~6 lines (optional shorthands)
EDIT server/init.py                            +1 line
EDIT Dockerfile                                +1 line (npm install)
EDIT deploy-sandbox.py                         +~15 lines (auth + first-light)
EDIT docker-compose.yml                        +2 lines (optional auth mount)
EDIT static/utils.js                           +8 lines (curated model subset)
EDIT static/components/WorkerConfigModal.js    +1 line
EDIT static/components/TopToolbar.js           +1 line
```

### `server/agents/opencode_adapter.py` — Detailed Structure

```python
"""openCode CLI adapter."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from server.agents.base import AgentAdapter


def _find_opencode():
    configured = os.environ.get("BULLPEN_OPENCODE_PATH")
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return configured
    return shutil.which("opencode")


# Env vars opencode reads for provider auth. Bullpen can inject these
# from the host environment or from a .env file.
OPENCODE_AUTH_ENV_VARS = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENCODE_CONFIG",
}


class OpenCodeAdapter(AgentAdapter):

    @property
    def name(self):
        return "opencode"

    def available(self):
        return _find_opencode() is not None

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        opencode_bin = _find_opencode() or "opencode"
        argv = [
            opencode_bin,
            "run",
            "--format", "json",
            "--dangerously-skip-permissions",
            "--model", model,
        ]
        if bp_dir:
            config = self._mcp_config(bp_dir)
            if config:
                # Pass config via env var (opencode reads OPENCODE_CONFIG)
                pass  # handled in prepare_env
        return argv

    def prompt_via_stdin(self):
        return True

    def prepare_env(self, workspace, bp_dir=None, task_id=None):
        env = os.environ.copy()
        # Isolate temp space for opencode's working files
        run_tmp = tempfile.mkdtemp(prefix="bullpen-opencode-")
        env["TMPDIR"] = run_tmp
        env["TMP"] = run_tmp
        env["TEMP"] = run_tmp

        # Inject provider auth env vars from the parent environment
        # (these may come from .env, Bullpen config, or the host shell).
        for key in OPENCODE_AUTH_ENV_VARS:
            value = os.environ.get(key)
            if value:
                env[key] = value

        # If a Bullpen MCP config was generated, expose it via OPENCODE_CONFIG
        if bp_dir:
            mcp_cfg = self._make_mcp_config(bp_dir)
            if mcp_cfg:
                env["OPENCODE_CONFIG"] = mcp_cfg

        return env, run_tmp

    def format_stream_line(self, raw_line):
        line = raw_line.strip()
        if not line:
            return None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return line

        event_type = obj.get("type")

        if event_type == "message":
            parts = []
            for block in obj.get("content", []):
                if block.get("type") == "text":
                    parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    inp = block.get("input", {})
                    if name == "Bash":
                        parts.append(f"$ {inp.get('command', '')}")
                    elif name == "Edit":
                        parts.append(f"[Edit] {inp.get('file_path', '')}")
                    elif name == "Write":
                        parts.append(f"[Write] {inp.get('file_path', '')}")
                    elif name == "Read":
                        parts.append(f"[Read] {inp.get('file_path', '')}")
                    elif name in ("Glob", "Grep"):
                        parts.append(f"[{name}] {inp.get('pattern', '')}")
                    else:
                        parts.append(f"[{name}]")
            return "\n".join(parts) if parts else None

        if event_type == "tool_result":
            content = obj.get("content", "")
            if isinstance(content, list):
                texts = [i.get("text", "") for i in content if isinstance(i, dict)]
                text = "\n".join(texts)
            else:
                text = str(content)
            if len(text) > 2000:
                text = text[:2000] + "\n[output truncated]"
            return text if text else None

        if event_type == "result":
            return None  # handled by parse_output

        if event_type == "error":
            return f"[opencode error] {obj.get('error', '')}"

        return None

    def parse_output(self, stdout, stderr, exit_code):
        result_text = ""
        is_error = False
        error_msg = None
        usage = {}

        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") == "result":
                result_text = obj.get("result", "")
                is_error = obj.get("is_error", False)
                usage = obj.get("usage", {})
                if is_error:
                    error_msg = result_text
                break

        if exit_code != 0 and not is_error:
            return {
                "success": False,
                "output": result_text,
                "error": error_msg or stderr.strip() or f"Exit code {exit_code}",
                "usage": usage,
            }

        if is_error:
            return {
                "success": False,
                "output": "",
                "error": error_msg or "Unknown error",
                "usage": usage,
            }

        return {
            "success": True,
            "output": result_text.strip(),
            "error": None,
            "usage": usage,
        }

    def _make_mcp_config(self, bp_dir):
        """Generate a temporary opencode MCP config pointing to Bullpen tools.
        
        Returns a JSON string suitable for OPENCODE_CONFIG, or None.
        """
        # Same approach as ClaudeAdapter._mcp_config()
        ...
```

### Registration (`server/agents/__init__.py`)

```python
from server.agents.opencode_adapter import OpenCodeAdapter

_adapters = {
    "claude": ClaudeAdapter(),
    "codex": CodexAdapter(),
    "gemini": GeminiAdapter(),
    "opencode": OpenCodeAdapter(),
}
```

### Model Aliases (`server/model_aliases.py`)

Add `"opencode"` to the `NORMALIZERS` dict — no changes needed to the
`normalize_model()` function itself since it already dispatches on the
provider key.

### Usage Tracking (`server/usage.py`)

The `extract_stream_usage_event()` function already dispatches by
`adapter_name`. Add an `"opencode"` branch that extracts
`input_tokens` / `output_tokens` from the JSON `usage` block in result
lines. The structure mirrors the existing Codex adapter's usage extraction.

## Deployment Changes

### Dockerfile

Add `opencode` to the `npm install -g` line:

```dockerfile
RUN npm install -g \
      @anthropic-ai/claude-code \
      @openai/codex \
      @google/gemini-cli \
      @opencode-ai/cli
```

This installs the `opencode` binary globally, making it available in PATH
inside both Docker and Microsandbox deployments.

### docker-compose.yml

Add an optional auth mount for opencode's config directory:

```yaml
volumes:
  - ${WORKSPACE_PATH:-./workspace}:/workspace
  # Optional provider auth mounts.
  # - ${HOME}/.claude:/home/bullpen/.claude:ro
  # ...
  # - ${HOME}/.config/opencode:/home/bullpen/.config/opencode:ro
```

### Microsandbox Deploy (`deploy-sandbox.py`)

#### Base Snapshot (prepare-base)

The microsandbox base snapshot installs npm packages at build time. Adding
`@opencode-ai/cli` to the npm install list means every sandbox launched from
that base will have opencode available out of the box.

The base is built from `node:22-bookworm` with the full npm install list.
After rebuild, new sandboxes include opencode at no additional deploy-time
cost.

#### Runtime Environment

Add opencode's auth env vars to the microsandbox runtime env injection:

```python
# In build_runtime_env():
OPENCODE_AUTH_ENV_VARS = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENCODE_CONFIG",
}
config.runtime_env.update({
    ...
    # opencode's env vars are inherited from the parent shell at deploy time;
    # SECRET_ENV_NAMES already includes ANTHROPIC_API_KEY, GOOGLE_API_KEY,
    # OPENAI_API_KEY — they are automatically forwarded.
    "BULLPEN_OPENCODE_PATH": "/usr/local/bin/opencode",
})
```

The existing `SECRET_ENV_NAMES` set in `deploy-sandbox.py` already includes
`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, and `OPENAI_API_KEY`. These are
automatically forwarded into the sandbox environment during deploy, so
opencode inherits working auth for the same providers the user has already
configured.

#### Provider Auth Setup

Extend the `auth` subparser to include `"opencode"`:

```python
auth_parser.add_argument("target", choices=("claude", "codex", "git", "opencode"))
```

For opencode, the "auth" step is a no-op when provider API keys are already
set via env var. If the user wants to use opencode's own config file, the
auth command copies `~/.config/opencode/opencode.json` (if it exists) into
the sandbox home:

```python
async def auth_opencode(sandbox, config):
    """Ensure opencode has provider auth available inside the sandbox."""
    # When API keys are injected via env vars, no interactive auth is needed.
    # Optionally copy ~/.config/opencode/opencode.json into the sandbox.
    local_config = Path.home() / ".config" / "opencode" / "opencode.json"
    if local_config.is_file():
        await run_sandbox_shell(sandbox,
            f"mkdir -p /home/bullpen/.config/opencode && "
            f"cp /app/{local_config.relative_to(config.bullpen_source).as_posix()} "
            f"/home/bullpen/.config/opencode/opencode.json"
            if local_config.is_relative_to(config.bullpen_source) else
            # Otherwise, read and write as text
            ...
        )
```

#### First Light Validation

Add `"opencode"` as a target for `first-light`:

```python
first_light_parser.add_argument("target", choices=("claude", "opencode"))
```

The first-light command runs `opencode run --format json --model
anthropic/claude-sonnet-4-6 "echo hello"` and validates that it produces a
well-formed JSON result line, confirming both the binary and provider auth
work.

#### FD Limits

opencode may open multiple connections to its underlying provider APIs and
manage tool subprocesses. The existing microsandbox `RLIMIT_NOFILE` bump
(65536) is sufficient; no changes needed.

### Security Considerations

1. **API keys**: opencode delegates to provider-specific API keys
   (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`). These are
   already handled by Bullpen's secret injection and redaction patterns.

2. **`--dangerously-skip-permissions`**: This flag is required for headless
   operation (same as Claude and Codex adapters). The trust model and
   `harden_agent_argv()` control whether this flag is forwarded.

3. **MCP access**: When opencode runs with Bullpen's MCP config, it can
   create/update tickets. This is same access that Claude and Codex workers
   get today, and is scoped to the Bullpen server's own permissions.

4. **Temp directory isolation**: Each opencode run gets a private temp
   directory that is cleaned up after exit, preventing cross-run
   contamination.

## Implementation Plan

### Phase 1 — Core Adapter + Frontend (1-2 days)

1. Create `server/agents/opencode_adapter.py` implementing `AgentAdapter`.
2. Register in `server/agents/__init__.py`.
3. Add curated model subset to `MODEL_OPTIONS` in `static/utils.js`.
4. Add `opencode` option to the provider `<select>` in `WorkerConfigModal.js`.
5. Add `opencode` to the color-picker iteration in `TopToolbar.js`.
6. Add `opencode` entry to `DEFAULT_AGENT_COLORS` in `static/utils.js`.
7. Add `opencode` entry to `DEFAULT_PROVIDER_COLORS` in `server/init.py`.
8. Manual testing: run an opencode worker slot locally.

### Phase 2 — Streaming & Focus View (1 day)

1. Verify `format_stream_line()` coverage of opencode's JSON event types.
2. Add usage extraction to `server/usage.py` for opencode's token format.
3. Test focus view streaming during a long-running opencode task.

### Phase 3 — Docker Deployment (0.5 day)

1. Add `@opencode-ai/cli` to Dockerfile npm install.
2. Rebuild Docker image and verify `opencode` is on PATH inside container.
3. Test running an opencode worker inside Docker deployment.

### Phase 4 — Microsandbox Deployment (1 day)

1. Rebuild microsandbox base snapshot with updated npm packages.
2. Add `"opencode"` to auth subparser choices.
3. Add `"opencode"` to first-light validation targets.
4. Deploy a microsandbox and run an end-to-end opencode worker.

### Phase 5 — Polish & Docs (0.5 day)

1. Documentation in `docs/opencode.md` covering setup, auth, model config.
2. Add example worker slot definitions in layout comments or example
   profiles.
3. Update `AGENTS.md` or Bullpen's own prompts to mention opencode support.

## Open Questions

1. **opencode config precedence**: When both env vars and
   `OPENCODE_CONFIG`/`opencode.json` are present, which takes precedence?
   Should Bullpen generate an inline config or rely on env vars only?

2. **Model catalog**: Should Bullpen discover available models from opencode
   (e.g. via `opencode models list`), or maintain a static list in
   `model_aliases.py` as Codex and Gemini do?

3. **Streaming format stability**: Is opencode's `--format json` output
   shape stable across versions? The adapter pins the event type schema; a
   breaking upstream change would require an adapter update.

4. **Multi-workspace**: opencode's own `opencode.json` can configure
   project-scoped MCP servers. Should Bullpen expose the current workspace
   path to opencode's config generation?
