# Worktree Lifetime

## Problem

Bullpen currently creates worktrees as if they are temporary, but behaves as if
they might need to live on indefinitely.

That mismatch caused the failure seen in
`/Users/bill/aistuff/pr-workflow-test`:

- a worker created a worktree for a ticket
- committed and pushed a PR from that worktree
- a downstream worker picked up the same ticket
- Bullpen tried to create the same worktree and branch again
- Git rejected the duplicate branch creation
- the ticket ended in `blocked`

The recent fixes in ticket and worker lifecycle improved failure handling around
this path, but they did not solve the underlying product ambiguity:

- what is a worktree for?
- how long does it live?
- what survives after the run finishes?

This spec answers those questions simply and decisively.

## Principle

A worktree is an ephemeral execution sandbox for one worker run.

It is not:

- a durable ticket artifact
- a handoff medium between workers
- something Bullpen should try to preserve for possible future reuse

The durable outputs of a run are:

- ticket updates
- commit hashes
- branch name, if a branch was created
- PR URL, if a PR was opened
- agent output written back to the ticket

The worktree itself is disposable.

## Policy

Bullpen should treat worktrees with one simple lifecycle:

1. Create the worktree when a worker run starts, if that worker is configured to
   use one.
2. Use it only for that run.
3. When the run finishes, complete any configured Git actions for that run.
4. Persist any durable Git metadata to the ticket.
5. Delete the worktree.

There is no reuse of worktrees.
There is no downstream adoption of worktrees.
There is no worktree afterlife.

If later work is needed, that later work gets its own run and, if needed, its
own fresh worktree.

## Why This Solves The Real Problem

The bug happened because Bullpen derived worktree identity from `task_id` and
then treated the resulting branch/path as if they might still be the right local
execution environment for later workers.

That is the wrong model.

The right model is:

- ticket state persists
- branch and PR metadata may persist
- worktree state does not persist beyond the run

Once that boundary is enforced, the original failure disappears conceptually:

- `PR Merge` workers should not expect a previous coding worktree to exist
- coding workers should not expect to reuse a previous coding worktree
- any leftover worktree directory is stale runtime debris, not valid state

## Run Lifecycle

### 1. Start

When a worker run begins:

- if `use_worktree` is false, run in the workspace as Bullpen does today
- if `use_worktree` is true:
  - verify the workspace is a Git repository
  - create a fresh worktree for this run
  - use that worktree as the worker's cwd

The worktree belongs only to this run.

### 2. Execute

The worker performs its task inside the worktree.

If `auto_commit` is enabled, Bullpen may create a commit from the worktree.

If `auto_pr` is enabled, Bullpen may push the branch and open a PR from the
worktree.

### 3. Persist Durable Results

Before cleanup, Bullpen writes durable Git outputs back to the ticket.

For the first implementation, the ticket metadata is:

- `branch_name`
- `commit_hash`
- `pr_url`

These are ticket facts, not worktree facts.

### 4. Finish

After the run finishes and any configured Git actions complete, Bullpen removes
the worktree.

This is the default behavior for all successful worktree-backed runs, including
runs that commit locally but do not open a PR.

If worktree removal fails, that is a run failure, not a warning to ignore.

Per the desired product rule, any exception in this area should block the ticket
and append the failure cause to the ticket body/output.

## Cleanup Trigger

The cleanup trigger should be defined by Bullpen's own success path, not by UI
guesswork and not by ambiguous external observation.

Bullpen already knows whether it:

- created a commit
- pushed a branch
- created a PR

because Bullpen itself performs those subprocess calls.

So the rule should be:

- clean up the worktree after the run's configured Git actions and metadata
  persistence succeed
- if any required step fails, the run fails and the ticket moves to `blocked`

This removes the ambiguity around "after push?" vs "after PR creation?" by
making cleanup part of one server-side run-finalization transaction.

For implementation purposes, the finalization order should be:

1. append worker output to the ticket
2. perform configured Git actions for the run
3. persist `branch_name`, `commit_hash`, and `pr_url` to the ticket
4. remove the worktree
5. apply the run's final disposition

The run is only successful if all five steps that apply to that run succeed.

## Why The Worktree Should Be Deleted After PR Push

Because at that point the worktree has done its job.

If the worker's parcel of work has been:

- completed
- committed or PR'd
- written back to the ticket

then the only things worth keeping are the durable artifacts of that work.

The local checkout directory is not one of those artifacts.

If someone wants the changes, they get them from:

- the commit
- the branch
- the PR

not from a leftover directory under `.bullpen/worktrees`.

## Why Bullpen Cannot Overwrite An Existing Worktree

Bullpen currently uses:

```text
git worktree add .bullpen/worktrees/<task_id> -b bullpen/<task_id>
```

That is a create operation, not an overwrite operation.

It fails if:

- the branch already exists
- the target path already exists

Git is right to reject that situation. A pre-existing worktree path should be
treated as stale state to clean up, not as something to overwrite in place.

Under this spec, the desired behavior becomes simpler:

- Bullpen should not expect a prior run's worktree to still exist
- if it does exist, Bullpen should treat it as stale runtime debris
- stale worktrees should be cleaned up explicitly, not reused and not
  overwritten

## Worker Responsibilities

This model sharpens the boundary between worker types:

- coding workers may use worktrees as temporary isolated sandboxes
- merge workers should operate on durable ticket metadata such as `pr_url`
  rather than on a previous worker's local checkout
- downstream workers must not assume a local worktree exists unless they create
  one for their own run

In practical terms:

- `PR Merge`-style workers should default to `use_worktree: false`
- `use_worktree` should mean "this run needs an isolated checkout now"
- it should not imply "preserve a checkout for later"

## Persistence

The ticket should carry the durable Git facts produced by the run.

This spec chooses the simpler home for that metadata:

- store it directly in ticket frontmatter

That keeps the model small and matches the product reality: the ticket is the
thing that survives and tells the story of the work.

For the first implementation, the fields are:

- `branch_name`
- `commit_hash`
- `pr_url`

No additional Git lifecycle fields are required for the first pass. If later
work needs more metadata, that can be added in a separate change.

## Failure Semantics

Worktree setup, Git actions, metadata persistence, and worktree cleanup are all
part of one run lifecycle.

If any of them fails, the run fails.

The ticket should:

- move to `blocked`
- include the exception cause in ticket output/body

This is intentionally strict. It keeps the model easy to understand and avoids
inventing a separate half-broken "cleanup warning but maybe success" state.

## Reconcile

Because worktrees are ephemeral, reconcile should treat any leftover worktree as
runtime debris, not as durable state to reconstruct around.

Bullpen should add a limited Git reconcile pass that:

- inspects `.bullpen/worktrees`
- reconciles against `git worktree list`
- removes orphaned or stale worktrees when safe
- reports mismatches clearly

This is cleanup of abandoned runtime artifacts, not recovery of a supported
long-lived worktree lifecycle.

For the first implementation, reconcile should stay narrow:

- it should clean up stale worktree directories and stale Git worktree registry
  entries when they are clearly abandoned
- it should not attempt to infer or repair higher-level branch or PR lifecycle

## Scope Boundaries

This spec intentionally does not try to solve every Git lifecycle question.

It defines only the worktree boundary:

- worktrees are per-run
- worktrees are ephemeral
- worktrees are deleted when the run finishes successfully
- failures in this path block the ticket

Branch retention, PR merge strategy, and any later follow-up work are separate
concerns. They may rely on durable metadata from the ticket, but they do not
justify keeping the old worktree alive.

## Implementation Decisions

This section locks the remaining decisions needed to proceed to an
implementation plan.

### 1. Ticket Metadata Shape

Use ticket frontmatter as the durable store for worktree-run Git outputs.

For the first implementation, the exact fields are:

- `branch_name`
- `commit_hash`
- `pr_url`

### 2. Finalization Order

The worker success path must follow this order:

1. append worker output
2. run configured Git actions
3. persist Git metadata to the ticket
4. remove the worktree
5. apply the final disposition

Disposition happens last so Bullpen does not report the run as successfully
landed if cleanup has not actually succeeded.

### 3. Non-PR Worktree Runs

Successful worktree-backed runs that do not open a PR still delete their
worktree immediately.

This is an unusual configuration, but it is not a different lifecycle. A
worktree-backed run is always ephemeral.

### 4. Failure Rule

Any exception in:

- worktree setup
- Git actions
- metadata persistence
- worktree cleanup

causes the run to fail.

The ticket must:

- move to `blocked`
- include the failure cause in ticket output/body

### 5. Branch Policy

Automatic branch deletion is out of scope for the first implementation.

The first implementation should:

- persist branch metadata
- leave branches alone after the run

Branch cleanup can be specified later as a separate concern.

### 6. Reconcile Scope

The first Git reconcile pass should stay narrow.

It should:

- detect stale worktree directories
- reconcile against `git worktree list`
- remove clearly stale worktree artifacts when safe
- report mismatches clearly

It should not:

- manage branch lifecycle
- infer PR lifecycle
- reconstruct durable state from leftover worktrees

### 7. UI Scope

No new UI is required for the first implementation unless implementation proves
that some failure or metadata state is unreadable without it.

The default assumption is:

- no new worktree-lifecycle UI
- no new retention toggle
- no new branch cleanup UI
