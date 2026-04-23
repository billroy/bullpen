# LazyClaude Review — Ideas for Bullpen

Source: https://github.com/cmblir/LazyClaude (v2.27.0 at time of review, 2026-04-23)

LazyClaude is a local-first dashboard for the whole `~/.claude/` directory
(agents, skills, hooks, plugins, MCP, sessions, projects) with an n8n-style
workflow engine on top. Python stdlib backend, single-file HTML SPA frontend,
flat-file + SQLite storage. Very different product shape from Bullpen (no
per-task worktrees, no parallel worker fleet), but several of its mechanics are
directly transferable.

Below are the ideas I think are worth stealing, grouped by how much they'd
actually move the needle for Bullpen.

---

## High-leverage ideas

### 1. Sessions index with quality scoring

LazyClaude indexes every `~/.claude/projects/*/*.jsonl` into a SQLite DB
incrementally (only files newer than last-indexed mtime), and scores each
session 0–100 across five transparent dimensions:

| Dimension    | Max | Signal                          |
|--------------|-----|---------------------------------|
| Engagement   | 25  | message count                   |
| Productivity | 25  | tool-use frequency              |
| Delegation   | 15  | agent call count                |
| Diversity    | 15  | variety of tools                |
| Reliability  | 20  | error penalties                 |

Why this matters for Bullpen: we already run workers that produce
`~/.claude/projects/*.jsonl` transcripts per run. We have no retrospective view
on *which runs went well*. A scored, filterable index would let the user:

- Find the best run of a task across retries.
- See which worker types/prompts produce the highest-quality sessions.
- Spot regressions after prompt or harness changes.

Storage fits cleanly next to the existing `.bullpen/` flat files — add a
`sessions.db` (WAL mode) keyed by run/worker/task. The scoring function should
live somewhere like [server/session_index.py] and rebuild on startup, then
incrementally as runs complete.

### 2. Agent-delegation graph

LazyClaude tracks an `agent_edges` table: every time a session spawns a
subagent, it's an edge with weight = call count. Rendered as a directed graph
with Claude at the center and subagents on the rim.

For Bullpen this maps naturally onto **workers launching subagents during a
run**. A per-task graph would be a much more informative artifact than the raw
transcript — the user can see where the work actually happened. It also helps
debug workers that over-delegate or get stuck bouncing between agents.

### 3. Per-run cost / token delta timeline

LazyClaude v2.20+ built a *unified* cost timeline across every playground and
workflow run — stacked daily chart, per-node token deltas. Bullpen currently
tracks usage ([server/usage.py](server/usage.py)) but, from what I can see,
doesn't expose a visual timeline that spans workers + tasks + workspaces.

A stacked daily/hourly chart, filterable by workspace/worker, would make cost
regressions obvious. Per-tool-call deltas inside a single run (v2.25) is the
stretch version — useful for finding the one `Read` that blew up context.

### 4. Workflow engine as "task templates"

LazyClaude's DAG engine is overkill for Bullpen as a first-class feature, but
the **node-level primitives** are worth borrowing for a simpler concept:
**chained / templated tasks**. The interesting bits:

- **Level-based parallelism** via Kahn's algorithm + `ThreadPoolExecutor`.
  Nodes on the same level run concurrently, levels execute sequentially. This
  is exactly the shape you'd want if a task said "spawn 3 workers in parallel,
  then one aggregator worker when they all finish."
- **`repeat` config**: `{enabled, maxIterations, intervalSeconds}` with
  *feedback injection* (iteration N receives iteration N-1's output prefixed
  to its prompt). This is essentially "retry with context" — much better than
  naive retry and relevant to the retrying-worker backoff path already in
  Bullpen ([d0fec90]).
- **`policy.tokenBudgetTotal` + `onBudgetExceeded: stop|warn`**: hard budget
  caps at the run level. Bullpen needs this — today a runaway worker has no
  ceiling.
- **Webhook triggers with HMAC `X-Webhook-Secret`** (timing-safe
  `hmac.compare_digest`). A clean way to let external systems (CI, Linear,
  GitHub) enqueue Bullpen tasks without copy/pasting MCP creds.

I'd *not* port the full 16-node DAG. I'd port the execution primitives
(levels, budgets, feedback-loop retries, webhook triggers) and expose them as
task config rather than a canvas.

### 5. SSRF / path-whitelist hardening pattern

LazyClaude takes a serious stance on two classes of risk that Bullpen is
exposed to once any worker does HTTP or file export:

- **HTTP SSRF guard**: block `10.0.0.0/8`, `169.254.169.254`, metadata
  endpoints unless `allowInternal: true` is explicitly set.
- **Output path whitelist**: exports only allowed under `~/Downloads`,
  `~/Documents`, `~/Desktop`, validated via `realpath()` to defeat symlink
  traversal.

Bullpen workers inherit the host's full network and FS surface. When we add a
"let this worker push results somewhere" feature, we should lift these two
patterns wholesale rather than inventing from scratch.

---

## Medium-leverage ideas

### 6. "Briefing" landing view

Overview cards: project count, active sessions, today's commands, pending
approvals, top projects by last activity. Data sources are cheap reads over
`~/.claude/history.jsonl` + task dirs. Bullpen's current landing is
workspace-centric; a device/activity briefing would be useful when the user
has multiple workspaces running overnight.

The one signal I'd definitely steal: **"sessions awaiting user approval on
tool calls."** Bullpen already has approval UI per-worker, but a
cross-workspace "what's waiting on me" surface would reduce the user having
to check each tile.

### 7. Run diff / rerun

v2.19 shipped node-by-node diff between two runs. For Bullpen this is
"diff two runs of the same task" — compare outputs, tool calls, tokens
side-by-side. Huge for iterating on worker prompts: change a prompt, re-run,
diff.

### 8. Model hint routing (`fast` / `deep` / `auto`)

Sessions/subagents accept `ModelHint` where `fast` → haiku, `deep` → opus,
`auto` uses a heuristic (length + keywords). Cleaner than hardcoding the model
per worker type. Bullpen's `model_aliases.py` is the natural home.

### 9. Session replay

Playback of a session's tool calls with timing. Cheap to build on top of the
existing JSONL transcripts, valuable for debugging a worker that "did
something weird." Pairs well with idea #1 above.

### 10. RTK token compression

LazyClaude ships an RTK optimizer claiming 60–90% token reduction on command
output. Not something to adopt blindly — numbers deserve skepticism — but
worth benchmarking against the shell output Bullpen workers already pipe
through. If even 30% holds, it's free savings per-run.

---

## Low-leverage / avoid

- **52 tabs across 6 groups.** LazyClaude's surface is enormous; that's its
  product. Bullpen is task-first and should stay focused.
- **8 built-in AI providers.** Bullpen is Claude-first. Adding provider
  pluralism dilutes the product without strong user pull.
- **Single 13,500-line HTML SPA.** Don't copy this architecture. Bullpen's
  Vue 3 + Socket.IO split is already better suited to real-time updates.
- **Per-release i18n (3,234 keys × 3 langs).** Only invest here if there's a
  user demand signal.

---

## Concrete next steps I'd propose

1. **Session index + quality score** (idea 1): smallest self-contained unit,
   immediately useful, no UI risk. Add `server/session_index.py` + a
   `sessions.db`, expose a "recent runs, sorted by score" list.
2. **Token budget policy on worker runs** (from idea 4): add
   `policy.tokenBudgetTotal` to worker config; stop-or-warn on exceed. Fits
   cleanly into existing [server/usage.py](server/usage.py).
3. **Cross-workspace "awaiting approval" surface** (from idea 6): a single
   query over workers in the approval state, pinned to the top nav.

Each is self-contained, doesn't touch the worktree/worker lifecycle, and
gives the user a visible win.
