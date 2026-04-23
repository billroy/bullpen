# Worker Approvals Summary

Last reviewed: 2026-04-23

## Executive Summary

Bullpen can become meaningfully less dangerous without immediately building a full live-approval system.

The simplest and most practical near-term path is:

1. Stop defaulting workers to full bypass / yolo-style execution.
2. Run workers in narrower sandbox and approval modes by default.
3. Treat approval-requiring actions as a first-class blocked state.
4. Let the user explicitly re-run a worker with broader permissions when needed.

That approach fits Bullpen's current architecture. A true "worker asks the user for approval mid-run and then continues" design is possible, but it is a larger architectural change because Bullpen's current worker runtime is non-interactive and pipe-based.

## Current State

Bullpen's AI workers are designed as one-shot subprocess runs:

- `server/workers.py` assembles a prompt, launches an agent CLI, streams stdout/stderr, and waits for completion.
- `SubprocessRunner` uses `subprocess.Popen(..., stdin=PIPE, stdout=PIPE, stderr=PIPE)` and writes the prompt once, then closes stdin.
- The worker UI receives streamed output, but the process is not treated as an interactive terminal session.

Current provider defaults are intentionally permissive:

- Claude workers use `--dangerously-skip-permissions`.
- Gemini workers use `--approval-mode yolo`.
- Codex workers use `--full-auto` by default, or `--dangerously-bypass-approvals-and-sandbox` when `BULLPEN_CODEX_SANDBOX` disables sandboxing.

Bullpen already has some useful hardening:

- Worker `trust_mode` defaults new AI workers to `untrusted`.
- Untrusted workers disable `auto_commit` and `auto_pr`.
- Prompt hardening marks ticket/chat/repo content as lower-priority untrusted input.
- Claude gets some additional argv hardening in untrusted/chat contexts.

That is helpful, but it is not the same thing as a real approval flow.

## Why Live Approvals Do Not Fall Out Of The Current Design

The key issue is not just provider flags. It is the worker execution model.

Today, a Bullpen worker run is:

- launch subprocess
- send prompt
- close stdin
- stream output
- parse final result

That model works well for autonomous background jobs, but it does not naturally support:

- the agent pausing for approval
- Bullpen presenting the approval request to the user
- the user answering approve / reject / edit scope
- the same agent session resuming afterward

In other words, Bullpen currently has a logging/streaming relationship with the worker process, not a conversational session relationship.

## Codex-Specific Constraint

Codex's official docs are fairly clear that approvals are designed for interactive sessions. In non-interactive flows, or when a run cannot surface a fresh approval, actions that need approval fail rather than pausing indefinitely for later user input.

Relevant docs:

- https://developers.openai.com/codex/agent-approvals-security#sandbox-and-approvals
- https://developers.openai.com/codex/cli/features#approval-modes
- https://developers.openai.com/codex/config-reference#configtoml
- https://developers.openai.com/codex/subagents#approvals-and-sandbox-controls

That does not make safer worker execution impossible. It does mean Bullpen should not assume it can simply intercept approval prompts from `codex exec` and broker them to the browser without changing the execution model.

## Less Dangerous Path That Fits The Current Architecture

The cleanest near-term direction is a blocked-and-rerun model rather than a live in-band approval model.

### What That Looks Like

- Add an explicit worker execution policy separate from `trust_mode`.
- Default new AI workers to a narrower policy such as:
  - `read_only`
  - `workspace_auto`
  - `workspace_requires_escalation`
- Run the provider in the safest practical mode that still allows useful work.
- If the provider needs broader access than the current policy allows, let the run fail into a structured blocked state.
- Surface that state in Bullpen as something like `needs approval` or `needs escalation`.
- Let the user explicitly choose to retry with expanded scope.

### Why This Is Attractive

- It preserves Bullpen's existing one-shot worker model.
- It gives users a clear safety boundary.
- It creates a meaningful improvement over today's always-autonomous defaults.
- It avoids building a half-working approval broker around provider-specific behavior.

### What Bullpen Would Need

- A persisted execution-policy field on AI workers.
- Better provider-specific argv mapping from policy to runtime flags.
- A structured worker failure category for approval/sandbox/escalation-needed outcomes.
- UI affordances to show:
  - what access the worker had
  - what action appears to have needed more access
  - what the user can do next
- A retry path that relaunches the worker with a broader policy only after explicit user action.

## What A True Live Approval System Would Require

If Bullpen wants workers to pause and ask the user for approval in the middle of a run, that is a different class of system.

At minimum it would need:

- PTY-backed or session-backed workers instead of one-shot pipe subprocesses.
- A bidirectional protocol between Bullpen and the running agent session.
- Provider-specific handling for approval prompts and resume semantics.
- Durable paused-session state so refreshes and reconnects do not lose the run.
- Approval UI with explicit action metadata.
- Timeout, cancel, and conflict behavior.
- Audit history of who approved what and when.
- A security model for which browser session or human is allowed to approve.

This is feasible, but it is much closer to "interactive remote agent sessions" than "background workers with a small extra feature."

## Architectural Design Issues To Consider

Even before designing a full solution, a few product and architecture questions matter:

### 1. Worker Identity And Approval Authority

Who is allowed to approve a worker action?

- Any connected user?
- Only the user who launched the run?
- Only an authenticated admin?

Bullpen is currently single-user and localhost-first, but approval semantics become much more important if that changes.

### 2. What The Approval Is Actually For

"Approval" can mean several different things:

- leave workspace sandbox
- enable network
- use a destructive MCP/app tool
- write outside allowed roots
- switch from read-only to writable

A useful UI likely needs to distinguish these rather than showing a generic "allow?" dialog.

### 3. Replay vs Resume

If a run fails because it needed broader permissions, should Bullpen:

- resume the paused session, or
- rerun the task from scratch with broader access?

Resume is better UX, but often much harder to implement reliably across providers. Replay is simpler, but may duplicate work or produce different results.

### 4. Provider Differences

Claude, Codex, and Gemini do not expose identical approval and sandbox semantics. Bullpen likely cannot treat them as a single abstract approval protocol without some provider-specific adaptation.

### 5. Auditability

If Bullpen adds user approvals, users will reasonably expect:

- a record of what was requested
- a record of what was approved or denied
- enough context to understand what changed after approval

That suggests approval events should become first-class worker/task history entries.

## Recommended Direction

For now, the most sensible path is:

1. Keep workers non-interactive.
2. Introduce an explicit execution policy on AI workers.
3. Default new workers to a narrower policy.
4. Convert approval-needed situations into a structured blocked state.
5. Add explicit user-triggered rerun/escalation controls.

This would make Bullpen materially safer without requiring a full redesign of worker execution.

If the product later proves that live approvals are important, Bullpen can revisit that as a separate project built around interactive worker sessions rather than trying to layer it awkwardly onto the existing subprocess runner.

## Open Questions

- How restrictive should the default AI worker policy be for new workers?
- Should `trust_mode` stay purely prompt/runtime-hardening, or evolve into the user-facing policy control?
- Should Bullpen expose one common policy vocabulary across providers, or provider-native controls?
- How much detail should Bullpen capture when a run is blocked on missing approval?
- Is replay-with-broader-scope acceptable UX, or is true session resume a product requirement?
