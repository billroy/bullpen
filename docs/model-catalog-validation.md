# Model Catalog Validation

Bullpen provider dropdowns are intentionally conservative, but provider model
slugs and CLI aliases still drift. Before changing a default catalog, run the
host-side validator through the same adapter path Bullpen uses for workers and
Agent Chat.

## Command

```bash
python3 bullpen.py model-catalog --workspace /path/to/project validate --provider gemini --output text
```

The validator sends a tiny prompt, `Reply with exactly: OK`, to each candidate
model and records whether the adapter was available, whether the subprocess
started, whether it responded, the return code, latency, and a coarse error
class such as `not_found`, `auth`, `quota`, or `timeout`.

Use JSON when you want an artifact to compare across releases:

```bash
python3 bullpen.py model-catalog --workspace /path/to/project validate --provider gemini > model-catalog-report.json
```

To compare adapter behavior with provider API catalogs, add `--api-catalog`.
This only works when the matching API credential is present:

- Gemini: `GEMINI_API_KEY`
- Codex/OpenAI: `OPENAI_API_KEY`
- Claude/Anthropic: `ANTHROPIC_API_KEY`

```bash
python3 bullpen.py model-catalog --workspace /path/to/project validate --provider gemini --api-catalog --output text
```

The API catalog is advisory. Bullpen may call a CLI surface with different
auth, routing, and aliases than the raw provider API. Treat a successful adapter
probe as the stronger signal for Bullpen defaults.

The adapter probe is still only a smoke test. It proves that Bullpen can invoke
the provider/model and receive a trivial response; it does not prove the model
will successfully complete Bullpen workflows such as reading a ticket,
mutating it through MCP tools, or handing it to the right worker.

## Interpreting Results

- Bullpen's Gemini defaults should stay on CLI-safe choices:
  `flash`, `flash-lite`, and `gemini-3-flash-preview`. Concrete 2.5 Flash
  slugs are accepted as saved-layout aliases, but should not be default UI
  choices because the CLI aliases have routed more reliably in headless runs.
- `success=true`: safe candidate for the current machine, auth state, and CLI
  version.
- `listed=true` and `success=false`: the raw API may know the slug, but the
  CLI/auth surface Bullpen uses did not accept it.
- `listed=false` and `success=true`: likely a CLI alias or provider-specific
  shortcut; keep it only if that CLI surface is the intended integration.
- `not_found`: remove from defaults or alias to a known-good fallback.
- `auth`: do not treat the model as bad; fix host credentials first.
- `quota`: do not treat the model as bad; retry later or validate with a
  cheaper candidate.

## Release Checklist

1. Run the validator for the provider you are changing.
2. Remove or demote failing default dropdown entries.
3. Add model aliases for stale saved layouts when there is a clear replacement.
4. Keep at least one smoke-tested fallback model per provider.
5. Save the JSON report with the investigation or release notes when practical.
