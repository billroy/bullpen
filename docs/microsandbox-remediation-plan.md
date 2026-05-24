# Microsandbox Architecture Review Remediation Plan

Updated: 2026-05-23

## Current Architecture

Microsandbox deploy now has one primary entrypoint:

```bash
python3 deploy-sandbox.py --workspace-root /path/to/projects
```

`deploy-sandbox.py` owns both phases:

- base preparation from an OCI source image into a local Microsandbox snapshot;
- per-project sandbox creation, Bullpen startup, provider setup, verification,
  detach, and success output.

Older entrypoints such as `deploy/microsandbox/prepare.sh` should remain out
of the user-facing path. New Microsandbox deployment logic belongs in
`deploy-sandbox.py`.

## Simplifications Completed

- Removed the shell-plus-embedded-Python prepare implementation.
- Centralized Microsandbox SDK use in `deploy-sandbox.py`.
- Added base controls: `--prepare-base`, `--rebuild-base`,
  `--no-prepare-base`, `--base`, `--source-image`, and `--source-dir`.
- Made deploy auto-prepare a missing base by default.
- Delayed base preparation until the user has confirmed sandbox replacement.
- Recorded prepared CLI versions in
  `/opt/bullpen-microsandbox-base-versions.txt`.
- Switched success URLs to `127.0.0.1` to avoid localhost IPv6 fallback delays.
- Added a bounded Codex wrapper lock timeout.

## Remaining Remediation

1. Provider setup summary semantics.
   Current output still collapses already-verified providers and newly
   configured providers into `Configured during install`. Split this into
   `already_verified`, `configured`, and `skipped`, then update success output
   and tests.

2. Provider interface diagnostics.
   Persist setup-time diagnostics under `/home/bullpen/logs`, including CLI
   paths, versions, auth probe result, and classified failure reason. Avoid
   token values.

3. Claude verification source of truth.
   Keep the real `claude --print` probe authoritative. Treat
   `.credentials.json` checks as diagnostics only, especially in `first-light`.

4. IPv6 mitigation policy.
   Decide whether disabling guest IPv6 should remain the explicit deploy policy
   or become a narrower Claude-only workaround if Microsandbox exposes a
   reversible/provider-local fix.

5. Provider CLI version policy.
   Keep latest-by-default for now, but add emergency override variables for
   pinning Claude, Codex, and Gemini versions. Define a small validation
   checklist for provider CLI upgrades.

6. Script decomposition.
   `deploy-sandbox.py` is intentionally unified but now large. Once behavior settles,
   split internal sections into small local modules under `deploy/microsandbox/`
   while keeping `deploy-sandbox.py` as the single user entrypoint.

## Test Themes

- Base preparation is skipped when replacement is declined.
- Missing base auto-prepares unless `--no-prepare-base` is set.
- Compatibility wrappers delegate only; they do not duplicate implementation.
- Provider setup summaries distinguish already verified, configured, skipped,
  and failed.
- Provider diagnostics are written without secrets.
- Codex wrapper lock timeout exits with a clear message.
