# Patent Analysis — Bullpen

Date: 2026-04-22

This is a preliminary product-and-prior-art screen, not a legal opinion. The goal is to identify where Bullpen appears most defensible, where the novelty is weak, and what claim shape would likely be required to have a serious patent story.

## Executive view

Bullpen's strongest patent candidate is not "multi-agent orchestration" in the abstract. That field is already crowded. The strongest candidate is the **Worker Grid as the workflow authoring and runtime surface**, especially the combination of:

- a spatial worker grid rather than a boxes-and-lines flow editor,
- task routing derived from worker placement and adjacency,
- direct manipulation of worker cards to create handoff behavior,
- ticket-backed execution state that humans and agents both mutate,
- and operational actions such as scheduling, watch-columns, worktrees, auto-commit/PR, and MCP ticket updates occurring inside that same surface.

My bottom line:

- **Most promising filing theme:** grid-native workflow orchestration for AI workers without a separate node-edge editor.
- **Good dependent-claim material:** adjacency handles, sparse infinite canvas, ghost-cell interactions, synthetic tickets for autonomous runs, handoff-depth protection, watch-column refill, and git/MCP integration.
- **Weak area:** any broad claim that sounds like "visual multi-agent workflow builder," "agent team manager," or "workflow canvas with debugging." Public prior art is already dense there.

## What Bullpen actually does

The codebase shows a fairly specific operating model:

- The product explicitly positions a **worker grid** as a primary surface for assigning tickets to AI workers, alongside ticket Kanban/list views and live execution surfaces. See [README.md](/Users/bill/aistuff/bullpen/README.md:72), [README.md](/Users/bill/aistuff/bullpen/README.md:74), [README.md](/Users/bill/aistuff/bullpen/README.md:77), [README.md](/Users/bill/aistuff/bullpen/README.md:83), [README.md](/Users/bill/aistuff/bullpen/README.md:84), [README.md](/Users/bill/aistuff/bullpen/README.md:85), [README.md](/Users/bill/aistuff/bullpen/README.md:86), [README.md](/Users/bill/aistuff/bullpen/README.md:87), [README.md](/Users/bill/aistuff/bullpen/README.md:100).
- The frontend implements a **sparse coordinate worker plane** with a viewport, headers, ghost cells, minimap, pan controls, and spreadsheet-like "Go to" cell addressing rather than a fixed node canvas. See [static/components/BullpenTab.js](/Users/bill/aistuff/bullpen/static/components/BullpenTab.js:48), [static/components/BullpenTab.js](/Users/bill/aistuff/bullpen/static/components/BullpenTab.js:96), [static/components/BullpenTab.js](/Users/bill/aistuff/bullpen/static/components/BullpenTab.js:139), [static/components/BullpenTab.js](/Users/bill/aistuff/bullpen/static/components/BullpenTab.js:165), [static/components/BullpenTab.js](/Users/bill/aistuff/bullpen/static/components/BullpenTab.js:191), [static/gridGeometry.js](/Users/bill/aistuff/bullpen/static/gridGeometry.js:25), [static/gridGeometry.js](/Users/bill/aistuff/bullpen/static/gridGeometry.js:49), [static/gridGeometry.js](/Users/bill/aistuff/bullpen/static/gridGeometry.js:81), [static/gridGeometry.js](/Users/bill/aistuff/bullpen/static/gridGeometry.js:109).
- Worker cards expose **directional connection handles** only when a neighbor exists, and dropping a handle onto the intended neighbor writes a `pass:<direction>` disposition. That is a workflow-authoring gesture embedded directly in runtime worker cards, not a separate edge editor. See [static/components/WorkerCard.js](/Users/bill/aistuff/bullpen/static/components/WorkerCard.js:21), [static/components/WorkerCard.js](/Users/bill/aistuff/bullpen/static/components/WorkerCard.js:33), [static/components/WorkerCard.js](/Users/bill/aistuff/bullpen/static/components/WorkerCard.js:135), [static/components/WorkerCard.js](/Users/bill/aistuff/bullpen/static/components/WorkerCard.js:455), [static/components/WorkerCard.js](/Users/bill/aistuff/bullpen/static/components/WorkerCard.js:473), [static/components/WorkerCard.js](/Users/bill/aistuff/bullpen/static/components/WorkerCard.js:516).
- The backend turns those dispositions into real execution routing: handoff by worker name, pass to adjacent worker by direction, random worker selection, or plain column routing; it also increments or resets `handoff_depth` to control loops. See [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:1823), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:1953), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:2038), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:2093), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:2145).
- Bullpen creates **synthetic tickets** for manual or scheduled worker runs, so autonomous/background work still appears as normal ticket state and can travel through the same routing pipeline. See [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:232), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:255), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:263), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:358).
- Execution can branch into **watch-column claiming, worktree setup, auto-commit, auto-PR, and MCP-backed ticket operations**, which strengthens the "integrated workflow surface" story. See [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:142), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:202), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:463), [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:2020), [server/mcp_tools.py](/Users/bill/aistuff/bullpen/server/mcp_tools.py:38), [server/mcp_tools.py](/Users/bill/aistuff/bullpen/server/mcp_tools.py:47).
- Worker definitions are portable across workspaces, but Bullpen knows some workflow references are workspace-local and warns accordingly. See [server/transfer.py](/Users/bill/aistuff/bullpen/server/transfer.py:127).

## Prior-art landscape

As of 2026-04-22, public product docs strongly suggest that broad claims on visual agent orchestration are crowded:

- CrewAI markets **Crew Studio** as an AI-assisted workspace with a **visual workflow editor** whose canvas shows connected nodes and edges: [CrewAI Crew Studio](https://docs.crewai.com/en/enterprise/features/crew-studio).
- LangChain's **LangSmith Studio** emphasizes graph visualization, interaction, and debugging, including "Visualize your graph architecture": [LangSmith Studio](https://docs.langchain.com/langsmith/studio).
- Microsoft's **AutoGen Studio** includes a **Team Builder** with drag-and-drop and a visual representation of message flow through a control transition graph: [AutoGen Studio](https://microsoft.github.io/autogen/0.4.0/user-guide/autogenstudio-user-guide/index.html).
- n8n documents workflow creation on a **canvas** where users add and connect nodes to compose workflows: [n8n Create a Workflow](https://docs.n8n.io/workflows/create/) and [n8n Editor UI](https://docs.n8n.io/courses/level-one/chapter-1/).
- Flowise's **Agentflow V2** says visual connections on the canvas define the workflow path and relies on a node-dependency and execution queue system: [Flowise Agentflow V2](https://docs.flowiseai.com/using-flowise/agentflowv2).

Those references matter because they make the following broad ideas look weak:

- "visual workflow builder for AI agents"
- "multi-agent orchestration with debugging"
- "drag-and-drop agent team design"
- "canvas-based workflow execution"

I did **not** find a close public reference in this quick screen that combines all of Bullpen's specific elements:

- task/ticket board plus worker grid,
- workflow encoded by worker occupancy and adjacency,
- direct runtime card gestures that define routing,
- and no separate boxes-and-lines authoring layer.

That last sentence is an inference from the reviewed materials, not a patentability conclusion. A real search by counsel should test it much harder.

## Best patent candidates

### 1. Grid-native workflow authoring and execution without a node-edge editor

This is the strongest theme.

Why it may be patent-relevant:

- The workflow is not authored as an explicit graph of boxes and lines.
- Workers occupy coordinates in a shared grid and the grid itself is the workflow surface.
- Routing semantics are partly **spatial**, not just symbolic.
- The same surface is used for placement, execution monitoring, assignment, and handoff.

The most promising claim framing is not "a grid UI." It is a narrower **computer-implemented workflow system** in which:

1. tickets are assigned from a ticket board to workers placed in grid coordinates,
2. the interface exposes routing affordances based on neighboring occupied cells,
3. a user defines handoff by interacting with worker cards rather than editing explicit graph edges,
4. task completion triggers automatic reassignment according to those spatial rules,
5. and the ticket remains the durable state object throughout the flow.

That is a much better story than a generic UX claim.

### 2. Spatial adjacency as executable workflow semantics

This is likely best as a dependent or co-equal narrower claim set.

Potentially valuable details:

- connection handles only appear when a qualifying adjacent worker exists;
- dropping a handle sets a pass direction;
- completion resolves the direction into a target worker at the adjacent coordinate;
- failure states are defined for missing neighbor, out-of-bounds coordinate, or excessive handoff depth;
- moving workers changes the effective workflow topology without editing any separate graph object.

This "placement changes execution semantics" point is important. It is more specific than ordinary drag-and-drop UI.

### 3. Ticket-backed autonomous execution ledger

This is moderately interesting, but weaker standing alone.

Bullpen unifies manual, scheduled, and queue-triggered work by converting autonomous runs into normal tickets, including synthetic tickets for self-directed runs. That creates one state model for:

- assignment,
- audit trail,
- agent output logging,
- status transitions,
- downstream routing,
- and agent/human co-management.

Useful as dependent claim material. On its own, it may be vulnerable to "workflow job record" prior art.

### 4. Sparse spreadsheet-style worker plane for live agent orchestration

This is real product differentiation, but probably weaker utility-claim territory unless tied to execution semantics.

Interesting details:

- sparse coordinate storage,
- virtualized rendering,
- ghost-cell interaction instead of full empty-cell DOM,
- cell-address navigation,
- minimap,
- row/column headers,
- and keyboard navigation over occupied worker coordinates.

That may still be worth preserving as support material, especially if a design patent or narrower UI claim is contemplated.

### 5. Cross-workspace worker portability with workflow-reference awareness

This feels more like a helpful feature than a likely centerpiece patent claim. I would not lead with it.

## What is likely not patentable in broad form

These elements appear too close to known practice to support broad claims by themselves:

- running Claude/Codex/Gemini from a manager UI,
- showing live logs or output panes,
- scheduling workers,
- queueing tasks to workers,
- graph/canvas workflow editing,
- agent debugging and observability,
- MCP-based ticket CRUD,
- worktrees, auto-commit, and auto-PR as generic automation steps.

They may still be useful as narrowing elements inside a combination claim.

## Recommended claim shape

If Bullpen is going to pursue this seriously, I would start from one narrow independent claim family and then layer dependents.

### Candidate independent claim direction

A computer-implemented system that:

- displays a ticket-management interface and a worker grid interface;
- stores workers at grid coordinates;
- receives assignment of a ticket to a source worker;
- presents, on the source worker card, routing affordances based on adjacent occupied grid coordinates, without requiring a separate graph-edge editor;
- stores routing instructions derived from that interaction;
- executes the ticket at the source worker;
- and upon completion automatically routes the ticket to a target worker or column according to the stored routing instruction and current grid occupancy.

### Good dependent claim material

- route handles only render when an adjacent occupied coordinate exists;
- moving a worker changes subsequent route resolution;
- random adjacent-worker selection;
- named-worker handoff fallback;
- handoff-depth counter and blocking logic;
- synthetic ticket generation for manual or scheduled runs;
- watch-column claim/refill behavior;
- sparse virtualized grid with ghost-cell targeting;
- spreadsheet-style cell addressing and minimap navigation;
- worktree creation and git action chaining after completion;
- MCP-mediated ticket mutation path.

## Practical recommendation

If the goal is actual patent filing, the filing story should center on:

1. **grid as workflow substrate**,
2. **adjacency-derived routing semantics**,
3. **no separate boxes-and-lines authoring requirement**,
4. **ticket-backed runtime continuity**.

I would avoid leading with:

- "AI agent manager",
- "visual workflow builder",
- or "multi-agent orchestration platform."

Those are product categories, not strong novelty anchors.

## Immediate next steps if you want to pursue this

- Have counsel run a focused prior-art search around:
  - spatially encoded workflow authoring,
  - adjacency-based task routing,
  - grid-based execution surfaces,
  - kanban-plus-agent orchestration,
  - and spreadsheet-like workflow control planes.
- Preserve invention evidence: screenshots, commit history, design docs, and feature dates for the Worker Grid and pass/handoff mechanics.
- Draft claims around the **specific operational combination**, not around general visual orchestration.
- Review public disclosures carefully. Bullpen's repository, docs, screenshots, and shipped behavior are already detailed enough that filing strategy should be coordinated with counsel, not handled casually.

## Sources

### Internal Bullpen sources

- [README.md](/Users/bill/aistuff/bullpen/README.md:72)
- [static/components/BullpenTab.js](/Users/bill/aistuff/bullpen/static/components/BullpenTab.js:48)
- [static/components/WorkerCard.js](/Users/bill/aistuff/bullpen/static/components/WorkerCard.js:21)
- [static/gridGeometry.js](/Users/bill/aistuff/bullpen/static/gridGeometry.js:25)
- [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:232)
- [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:1823)
- [server/workers.py](/Users/bill/aistuff/bullpen/server/workers.py:2038)
- [server/mcp_tools.py](/Users/bill/aistuff/bullpen/server/mcp_tools.py:38)
- [server/transfer.py](/Users/bill/aistuff/bullpen/server/transfer.py:127)

### External references reviewed on 2026-04-22

- [CrewAI Crew Studio](https://docs.crewai.com/en/enterprise/features/crew-studio)
- [LangSmith Studio](https://docs.langchain.com/langsmith/studio)
- [AutoGen Studio](https://microsoft.github.io/autogen/0.4.0/user-guide/autogenstudio-user-guide/index.html)
- [n8n Create a Workflow](https://docs.n8n.io/workflows/create/)
- [n8n Editor UI](https://docs.n8n.io/courses/level-one/chapter-1/)
- [Flowise Agentflow V2](https://docs.flowiseai.com/using-flowise/agentflowv2)
