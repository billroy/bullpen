# OpenCode integration contract

Captured against OpenCode `1.17.3` at `/Users/bill/.opencode/bin/opencode`.

## Prompt transport

Both message-argument and stdin prompt transport work with:

```bash
opencode run --format json --model opencode/north-mini-code-free "Reply OK only."
printf 'Reply OK only.' | opencode run --format json --model opencode/north-mini-code-free
```

Both produced the same event shape: `step_start`, one or more `text` events,
and `step_finish`. Bullpen should use the existing shared stdin prompt path for
the first adapter.

## JSON events

Observed successful text run:

- `step_start` with `part.type` set to `step-start`
- `text` with assistant text at `part.text`
- `step_finish` with `part.type` set to `step-finish`, `part.reason`, and
  token usage at `part.tokens`

Observed provider/model routing failure:

- `error` with `error.name`, `error.data.message`, `error.data.statusCode`,
  and `error.data.isRetryable`

Fixtures:

- `tests/fixtures/opencode/run_success_text.jsonl`
- `tests/fixtures/opencode/run_provider_error.jsonl`

## Usage mapping

Map `step_finish.part.tokens` to Bullpen usage fields:

- `tokens.input` -> `input_tokens`
- `tokens.output` -> `output_tokens`
- `tokens.reasoning` -> `reasoning_output_tokens`
- `tokens.total` -> `total_tokens`
- `tokens.cache.read` -> `cached_input_tokens`

`tokens.cache.write` is not currently represented in Bullpen's canonical usage
fields.

## Model catalog

`opencode models` emits one model id per line. `opencode models <provider>`
filters by provider. `opencode models --verbose <provider>` emits each model id
line followed by a JSON metadata object.

Fixtures:

- `tests/fixtures/opencode/models_opencode.txt`
- `tests/fixtures/opencode/models_opencode_verbose.txt`

First implementation should parse the plain non-verbose output for the picker.
Verbose metadata can be treated as a later enhancement because it uses mixed
plain-text and JSON blocks.

## MCP config

Use a per-run OpenCode config file passed via `OPENCODE_CONFIG`. The config
should define a local MCP server named `bullpen` under the `mcp` key and launch
`server/mcp_tools.py` directly with `sys.executable`, not through a shell.

## Trust-mode strategy

Add an explicit `opencode` branch to `harden_agent_argv()` rather than extending
the adapter interface to accept trust mode. Trusted mode may append
`--dangerously-skip-permissions` if headless tool use requires it. Untrusted
mode must not append that flag; if OpenCode cannot operate safely without it,
the run should fail with a clear message.

## Agent Chat strategy

Use fresh `opencode run` turns with Bullpen's existing assembled chat prompt for
the first implementation. Defer OpenCode-native session continuation or
`opencode serve` attachment until after worker and chat parity are working.

## Remaining unknowns

- Tool-call and tool-result JSON event shape. The automated probe using
  `--dangerously-skip-permissions` was rejected as too risky because it would
  allow an external model to run local shell commands outside the workspace
  sandbox. Capture this manually only with explicit human approval.
- Exact auth failure shape for missing/expired OpenCode credentials. The dev
  environment has working OpenCode auth, so this should be covered with a fake
  executable fixture unless a safe real-auth failure can be produced later.
