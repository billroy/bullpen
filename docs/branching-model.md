# Bullpen Branching Model

Bullpen already has the beginning of a workflow graph in its worker disposition
grammar. A worker can send a ticket to a column, a named worker, an adjacent
grid neighbor, or a random worker pool:

```text
review
done
blocked
custom-column
worker:NAME
pass:LEFT
pass:RIGHT
pass:UP
pass:DOWN
pass:RANDOM
random:PATTERN
```

A branching model should build on this grammar rather than replace it. The
branching layer decides which disposition to use for the current ticket; the
existing routing layer performs the actual move.

## Core Model

A worker can end a run with a structured branch decision:

```json
{
  "route": "positive",
  "disposition": "worker:Positive",
  "reason": "The computed score was greater than zero."
}
```

The `route` is a stable human-facing branch label. The `disposition` is the
runtime Bullpen routing target. The `reason` is recorded for auditability and
operator debugging.

For example, a prompt direction such as:

```text
If x > 0 then dispatch the ticket to positive else send it to done.
```

can compile to:

```text
positive -> worker:Positive
done     -> done
```

The worker prompt can reason naturally, but its final answer should choose one
declared branch. Bullpen then validates that the branch is allowed and applies
the mapped disposition.

## Interaction With Existing Routing

### Pass Directives

`pass:*` is the physical grid routing language.

`pass:right` means "send this ticket to the ticket-accepting worker in the
adjacent grid cell to my right." This is ideal for visual workflows where the
grid itself is the program:

```text
intake -> classify -> implement -> review -> done
```

Branching can target pass directives directly:

```yaml
allowed_routes:
  continue: pass:right
  retry: pass:left
  escalate: pass:down
  done: done
```

This keeps the operator's mental model spatial. Moving workers changes the
route, which is useful when the board is being used as visible wiring. It is
less appropriate when the branch means "send to security review" regardless of
where that worker sits.

`pass:RANDOM` chooses a random adjacent occupied ticket worker. It is best for
local mesh or cellular flows where all adjacent targets are equivalent. It
should be used carefully for business-critical branches because the route is
less explicit than a named target.

### Loose-Bound Worker Names

`worker:NAME` is the semantic routing language.

The current handoff behavior resolves a worker by normalized name. This is a
loose binding: it survives grid rearrangement, but it depends on clear naming.
That makes it a strong fit for prompt-level branch labels:

```yaml
allowed_routes:
  positive: worker:Positive
  needs_human: worker:Human Review
  security: worker:Security Reviewer
  done: done
```

This lets the workflow say what it means instead of where the target happens to
be. Operators can move the `Security Reviewer` card without breaking the branch.

The main risk is ambiguity. Bullpen should treat duplicate or missing target
names as validation problems or route failures, not make a best-effort guess.

### Random Dispatch Over The Grid

`random:PATTERN` is pool routing.

Blank `random:` means "choose any other available ticket worker." A nonblank
pattern currently means an exact normalized worker-name match, not a glob or
regular expression. The existing behavior prefers idle workers with empty queues
when possible, then falls back to the full matching candidate set.

This is useful when several workers are interchangeable:

```yaml
allowed_routes:
  routine_backend: random:Backend Developer
  routine_review: random:Reviewer
  specialist_review: worker:Senior Architect
```

This differs from `pass:RANDOM`: `random:PATTERN` searches the worker grid for a
matching pool, while `pass:RANDOM` only considers adjacent neighbors.

## Prompt Contract

Worker prompts should be allowed to describe branch logic in ordinary language,
but the final output should be constrained.

Example:

```text
When finished, choose exactly one route:

- positive: use when the score is greater than 0
- done: use when the score is 0 or less

Return:
ROUTE: <positive|done>
REASON: <short explanation>
```

Bullpen maps `ROUTE` through the configured route table. The worker does not
need to know whether `positive` means `worker:Positive`, `pass:right`, or
`random:Positive Handler`.

For more advanced workers, Bullpen can allow a full disposition override:

```json
{
  "disposition": "random:Reviewer",
  "reason": "Any reviewer in the pool can handle this ticket."
}
```

That override should still pass the same validation as configured worker
dispositions.

## Precedence

The current backend distinguishes a final status request from a worker
disposition. `worker_requested_status` is column-oriented: it resolves to a
final task status such as `done`, `review`, `blocked`, or a configured custom
column.

Branching should avoid overloading that field. A clean implementation would use
a separate full-disposition request:

```text
worker_requested_status       -> final column only
worker_requested_disposition  -> column, worker:NAME, pass:*, or random:*
```

Recommended precedence:

1. An explicit validated branch disposition for this run.
2. A validated worker-requested final status, when no branch disposition exists.
3. The worker's configured default disposition.

This preserves existing behavior while making dynamic routing explicit.

## Runtime Validation

Bullpen should fail closed when routing is invalid.

- A branch route must be declared for that worker or flow node.
- The mapped disposition must pass the existing disposition validator.
- `worker:NAME` must resolve to a ticket-accepting worker.
- `pass:*` must resolve to an adjacent ticket-accepting worker.
- `random:PATTERN` must find at least one ticket-accepting candidate.
- Terminal columns clear assignment and reset handoff depth.
- Worker handoffs increment handoff depth and obey the configured depth limit.

Invalid routing should move the ticket to a visible fallback such as `blocked`
and append a clear explanation to the ticket body. It should not silently drop,
hide, or guess a destination.

## Columns, Workers, And Nodes

The simplest version does not need a separate workflow graph object. Each worker
has a default disposition and, optionally, a branch route table:

```yaml
name: Classifier
disposition: blocked
branches:
  positive: worker:Positive
  negative: done
  uncertain: worker:Human Review
```

Over time, Bullpen could introduce named flow nodes:

```yaml
nodes:
  classify:
    worker: Classifier
    routes:
      bug: worker:Bug Worker
      feature: worker:Feature Worker
      unclear: worker:Human Review

  review:
    worker: Reviewer
    routes:
      approved: done
      changes_requested: worker:Implementation
```

In that richer model, columns remain visual/task states and workers remain the
execution agents. Nodes are the workflow layer that maps branch labels to
Bullpen dispositions.

## Recommended First Step

Implement branching as a thin decision layer that compiles to the existing
disposition grammar.

That gives Bullpen useful conditional routing without creating a second routing
system:

- prompts choose branch labels;
- branch labels map to dispositions;
- dispositions use the existing column, `worker:NAME`, `pass:*`, and
  `random:*` machinery;
- every transition remains validated, visible, and explainable.

