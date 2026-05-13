# Architecture Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Principal software architect evaluating for acquisition

---

## Executive Summary

Bullpen's architecture is coherent and well-suited to its current target: a single-host, single-team AI agent orchestration platform. The layered design — Flask REST + Socket.IO real-time events, flat-file persistence, Vue 3 CDN frontend — is deliberate and appropriately minimalist. Separation of concerns is good across the backend modules, and the agent adapter abstraction is a genuine strength. The most significant architectural risks are: a 2,975-line god module in the most critical execution path (`workers.py`), global mutable state in the frontend (`window.app`), a single-host deployment model with no horizontal scale path, and a concurrency model (eventlet green-threading) that is not aligned with the modern Python async ecosystem. None of these block the current use case, but they constrain the product's evolution trajectory.

---

## Findings

### HIGH — `workers.py` is the single point of highest structural risk

**Detail:** The worker execution pipeline — the core value-generating path in the product — is concentrated in a single 2,975-line module. This module conflates subprocess lifecycle management, state machine transitions, retry/backoff logic, Socket.IO event emission, grid persistence, and background thread management. The architectural implication is severe: any refactor, extension, or bug fix in this path requires a contributor to hold the entire execution model in their head simultaneously. There is no interface boundary that allows, for example, the persistence layer to be swapped without touching the subprocess management code.

From a buyer's perspective, this is the highest-priority architectural risk in the codebase — it is also the highest-value code, which makes the coupling doubly concerning.

**Recommendation:** Decompose `workers.py` into three focused modules:
- `worker_state_machine.py` — state transitions and retry/backoff policy
- `worker_process.py` — subprocess spawning, stream capture, kill escalation
- `worker_persistence.py` — grid state reads/writes, layout hydration

This refactor does not change behavior; it imposes explicit interface boundaries that reduce cognitive load and enable targeted testing.

---

### HIGH — Frontend architecture couples all components to a global mutable object

**Location:** `static/app.js` — root Vue app state exposed as `window.app`

**Detail:** All Vue components access shared state through `window.app`. This pattern bypasses Vue 3's reactivity and dependency injection system. The architectural consequences are:

1. Components cannot be instantiated outside the full application context — they have an implicit, undeclared dependency on `window.app`.
2. State ownership is undeclared: any component can mutate `window.app.workers`, `window.app.tasks`, etc., without a defined update protocol.
3. The component tree cannot be incrementally split into micro-frontends or independently deployable units.
4. Server-side rendering is impossible without `window` shims.

Vue 3 provides `provide`/`inject` and composables (`reactive()`, `computed()`) that solve this correctly. The refactor can be incremental — introduce a `useWorkspace()` composable that reads and writes the same underlying reactive state as `window.app`, and migrate components to use it without a big-bang rewrite.

**Recommendation:** Introduce a composable layer (`static/composables/`) for the major state domains (tasks, workers, layout, config). Migrate `window.app` property access to composable calls incrementally. Each migrated component becomes independently testable.

---

### MEDIUM — Single-host deployment model; no horizontal scale path designed

**Detail:** The architecture assumes a single server process per deployment. Multiple design decisions make horizontal scaling non-trivial:

1. `write_lock` is a process-level `threading.RLock` — it does not protect against concurrent writes from a second server process.
2. Layout and task state are held in memory (hydrated at startup), with flat-file writes on mutation — a second process would have a stale in-memory copy.
3. Socket.IO rooms scope events per workspace per process — there is no shared pub/sub backend (e.g., Redis) to fan out events across processes.
4. Agent subprocess management is tied to the process that started the agent; a second process cannot monitor or kill agents started by the first.

For the current single-team, single-host use case, this is not a defect. But it is the most significant architectural constraint on the product's commercial scale trajectory.

**Recommendation:** No immediate action for the current use case. For future SaaS or multi-host plans: scope a Redis-backed Socket.IO adapter and SQLite/PostgreSQL persistence migration. Document the single-host boundary explicitly in `docs/architecture.md` so that future contributors understand it is a deliberate design choice, not an oversight.

---

### MEDIUM — eventlet green-threading is architectural technical debt

**Location:** `requirements.txt` (eventlet 0.41.0), `server/app.py`

**Detail:** Flask-SocketIO with eventlet uses cooperative multitasking via monkey-patching of the Python standard library. This approach:

1. Silently changes the semantics of `time.sleep`, `socket`, `threading`, and other standard library modules for all code in the process.
2. Can cause incompatibilities when new libraries assume standard threading semantics (Python's asyncio, newer httpx-based clients, etc.).
3. Is not the direction the Python ecosystem is moving — asyncio/ASGI (uvicorn) is the modern model for I/O-concurrency in Python web servers.

The risk is low today but compounds over time as new dependencies are added. Flask-SocketIO supports asyncio mode via `async_mode='asgi'`, which would allow migration to uvicorn without changing application code.

**Recommendation:** Log this as a known technical debt item. Scope an asyncio/uvicorn migration as a future initiative. In the meantime, test each new dependency for eventlet compatibility before adding it.

---

### MEDIUM — MCP stdio server uses an out-of-process, self-connecting architecture

**Location:** `server/mcp_tools.py`

**Detail:** The MCP server runs as a child process (spawned by `bullpen.py`) that connects back to the main Flask/Socket.IO server via websocket using an auth token. This design works but creates architectural coupling:

1. The MCP server must know the host:port of the parent Bullpen server — this is passed via environment variable or config file.
2. If the parent server restarts, the MCP child must reconnect — there is retry logic, but it is a coordination surface.
3. Stdout redirection in the child process (`sys.stdout → sys.stderr`) is a pragmatic protocol workaround that adds invisible global side effects.

The design is justified by the MCP stdio protocol requirement (no stdout corruption), but it should be formally documented as an architectural decision.

**Recommendation:** Add an Architecture Decision Record (ADR) at `docs/adr/001-mcp-stdio-out-of-process.md` explaining why MCP runs as a child that self-connects, what alternatives were considered, and what the operational implications are. Add a comment at the `sys.stdout` redirect site that references the ADR.

---

### LOW — No formal API contract for Socket.IO event schemas

**Detail:** The Socket.IO event names and payload schemas are the product's core internal API. They are defined implicitly by the handler code in `server/events.py` and the emitter calls in `static/commands.js`. There is no schema file, no versioning, and no documentation of the contract.

As the product evolves, schema drift between server handlers and client emitters is detectable only at runtime (typically via silent failures or unexpected undefined values in JavaScript). For a team product, this is a latent source of subtle bugs.

**Recommendation:** Generate a `docs/SOCKET_EVENTS.md` documenting all event names, direction (server→client or client→server), and payload shapes. Even a manually-maintained document reduces schema drift. Future work: add a schema validation layer to Socket.IO handlers using Pydantic or marshmallow.

---

### LOW — No Architecture Decision Records (ADRs)

**Detail:** The codebase reflects several deliberate, non-obvious architectural choices: no database (flat files), no build step (CDN Vue), eventlet over asyncio, custom frontmatter parser over PyYAML, out-of-process MCP server. These decisions are correct and well-considered, but they are not documented as decisions. A new contributor or acquirer reading the code sees the outcomes without the reasoning, which leads to either cargo-culting the pattern or breaking it unknowingly.

**Recommendation:** Create `docs/adr/` and write brief ADRs (1–2 pages each) for the three or four most architecturally significant decisions: (1) flat-file persistence, (2) no build step / CDN Vue, (3) eventlet concurrency model, (4) out-of-process MCP server.

---

## Architectural Strengths (No Action Required)

| Strength | Evidence |
|---|---|
| Agent adapter abstraction | `server/agents/` — clean base class with CLI-specific subclasses |
| Atomic file I/O | `persistence.py` — tempfile + rename prevents corruption |
| Per-workspace Socket.IO room scoping | Events scoped to workspace ID; no cross-workspace leakage |
| Path traversal prevention at persistence layer | `ensure_within()` applied consistently |
| Minimal dependency footprint | 7 Python dependencies; zero npm build dependencies |
| Explicit module separation | One file per concern in `server/`; clear responsibilities |
| Scheduler isolation | Per-workspace background thread; clean shutdown path |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 3 |
| LOW | 2 |
