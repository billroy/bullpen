## 6. Worker Disposition: Hand Off to Another Worker's Queue

Status: Ready for implementation planning

---

### Summary
Extend the Disposition field in the worker config modal to support routing completed tasks to another worker's queue, in addition to kanban columns. This enables worker pipelines (e.g., spec writer → implementer → reviewer).

### Current State
Disposition is a dropdown with two options: "Review" and "Done" (`WorkerConfigModal.js:119-125`). These map to kanban column keys. When a worker finishes a task, the server sets `task.status = disposition` and clears `assigned_to` (`workers.py:390-394`). Validation enforces disposition ∈ `{"review", "done"}` (`validation.py:19, 171`).

### Design Decision: Weak Binding by Worker Name

Rather than introducing stable worker IDs (which would touch every layer of the system), worker handoff targets are identified by **worker name** — a "weak binding" that trades strict referential integrity for simplicity.

**Tradeoffs accepted:**
- If the target worker is renamed or deleted, the binding breaks. This is detected at runtime and handled gracefully (task moves to BLOCKED, user is notified via toast).
- If multiple workers share the same name, the first match (lowest slot index) is used. This is a user error, not something we need to prevent.
- Workers can be freely reordered, moved, duplicated without breaking handoff bindings (since names travel with the worker, unlike slot indices).

**Value encoding:**
- Worker targets: `worker:<name>` (e.g., `worker:Code Reviewer`)
- Column targets: bare column key, same as today (e.g., `review`, `done`)
- No `column:` prefix — bare strings are always column keys. This means zero migration of existing configs.

### Circular Handoff Detection (Runtime)

Circular handoffs (A → B → A, or longer chains) must be detected at runtime because:
- The chain structure can change at any time (user reconfigures disposition mid-flight)
- Name-based binding means the target worker's own disposition can change between configuration and execution

**Approach: handoff depth counter on the task.**

- Add a `handoff_depth` field to task metadata (frontmatter), default 0.
- Each time a worker's disposition routes a task to another worker (not a column), increment `handoff_depth`.
- If `handoff_depth` exceeds a max (default: **10**), break the chain: move task to `blocked` status with a note appended to the body explaining the cycle was detected.
- When a task moves to a **column** (either by worker disposition or human action), reset `handoff_depth` to 0.

**Why depth counter, not visited-set:**
A visited-set (track which workers have seen this task) would catch exact cycles earlier but adds complexity (serializing/deserializing a set in frontmatter, deciding when to clear it). A depth counter is one integer, trivial to store, and catches both direct cycles and accidentally-long chains. Max depth of 10 accommodates long pipelines while still catching runaways quickly. Each chain step requires a full agent run to complete before the next handoff, so even a runaway cycle is bounded in cost.

### Server Changes

#### `workers.py` — disposition routing (~line 389-394)

Replace the current block:
```python
disposition = worker.get("disposition", "review")
task_mod.update_task(bp_dir, task_id, {
    "status": disposition,
    "assigned_to": "",
})
```

With:
```python
disposition = worker.get("disposition", "review")
if disposition.startswith("worker:"):
    target_name = disposition[len("worker:"):]
    _handoff_to_worker(bp_dir, task_id, target_name, layout, socketio, ws_id)
else:
    task_mod.update_task(bp_dir, task_id, {
        "status": disposition,
        "assigned_to": "",
        "handoff_depth": 0,  # reset on column placement
    })
```

New helper `_handoff_to_worker(bp_dir, task_id, target_name, layout, socketio, ws_id)`:
1. Read current task, get `handoff_depth` (default 0).
2. If `handoff_depth >= 10`: move task to `blocked`, append cycle warning to body, emit toast. Return.
3. Scan `layout["slots"]` for first worker where `worker["name"] == target_name`.
4. If not found: move task to `blocked`, append "handoff target not found" note, emit toast. Return.
5. Increment `handoff_depth` on the task, then call `assign_task(bp_dir, target_slot, task_id, socketio, ws_id)`.

#### `validation.py` — disposition validation (~line 19, 171)

The `VALID_DISPOSITIONS` enum check must be relaxed. Replace the strict `_enum()` call with:
```python
if "disposition" in fields:
    d = fields["disposition"]
    if isinstance(d, str) and (d in VALID_COLUMNS or d.startswith("worker:")):
        sanitized["disposition"] = d[:200]  # length cap
    else:
        raise ValidationError("Invalid disposition")
```

Where `VALID_COLUMNS` is the set of known column keys. However, columns are configurable per-workspace, so the validator either:
- **(Option A)** Accepts any bare string as a column key and lets the server handle unknown columns at runtime (simpler, consistent with how `watch_column` is validated today — it's not enum-checked).
- **(Option B)** Receives the column list and validates against it.

**Recommendation: Option A.** `watch_column` already accepts any string (`validation.py:173`). Disposition should follow the same pattern. The server already handles unknown statuses gracefully (task just gets an unrecognized status, which the kanban board ignores).

Updated validation:
```python
if "disposition" in fields:
    d = _str(fields["disposition"], 200, "disposition")
    sanitized["disposition"] = d
```

#### `server/init.py` — default column config

No change needed. The "blocked" column already exists in the default column set.

### Frontend Changes

#### `WorkerConfigModal.js` — grouped disposition dropdown

Replace the current simple `<select>` (lines 119-125) with an optgroup dropdown:

```html
<select class="form-select" v-model="form.disposition">
  <optgroup label="Columns">
    <option v-for="col in columns" :key="col.key" :value="col.key">{{ col.label }}</option>
  </optgroup>
  <optgroup label="Workers" v-if="otherWorkers.length">
    <option v-for="w in otherWorkers" :key="'worker:' + w.name" :value="'worker:' + w.name">
      → {{ w.name }}
    </option>
  </optgroup>
</select>
```

New computed `otherWorkers`:
```javascript
otherWorkers() {
  if (!this.workers) return [];
  return this.workers
    .filter((w, i) => w && i !== this.slotIndex)
    .map((w, i) => ({ name: w.name, slot: i }));
}
```

**New prop needed:** `workers` (the full `layout.slots` array). Parent (`app.js`) already has `state.layout.slots` available; pass it as `:workers="state.layout.slots"` on the `<WorkerConfigModal>` tag.

#### `app.js` — pass workers prop

Add `:workers="state.layout.slots"` to the `<WorkerConfigModal>` component usage (~line 398).

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Target worker renamed | Next handoff fails, task → BLOCKED with "target not found" note |
| Target worker deleted | Same as above |
| Circular chain (A→B→A) | After 5 total handoffs, task → BLOCKED with cycle warning |
| Legitimate pipeline (up to 10 stages) | Works fine (depth < max 10) |
| Self-handoff configured | UI excludes self from dropdown, but if manually set, depth counter catches it after 10 iterations |
| Multiple workers with same name | First match (lowest slot index) wins |
| Bare "review"/"done" in existing configs | Works unchanged — no migration needed |

### Test Plan

**Unit tests (`test_workers.py`):**
- Worker finishes task with `disposition: "worker:Target"` → task assigned to Target's queue
- Worker finishes task with `disposition: "worker:Deleted Worker"` → task moves to BLOCKED
- Handoff depth increments across worker chain
- Handoff depth >= 10 → task moves to BLOCKED with cycle message
- Handoff depth resets to 0 when task moves to a column
- Bare disposition values ("review", "done") continue to work unchanged

**Integration tests (`test_events.py`):**
- Configure worker with worker disposition via `worker:configure` event, verify it persists
- Two-worker pipeline: Worker A (disposition: "worker:B") completes → task appears in Worker B's queue

### Issues Resolved

- ~~**Worker identification stability**~~: Resolved via weak binding by name. No stable IDs needed.
- ~~**Circular handoff detection**~~: Resolved via runtime `handoff_depth` counter, max 5.
- ~~**Props for worker list**~~: Pass `layout.slots` as new `workers` prop to `WorkerConfigModal`.

### Remaining Issues

None blocking. This feature is ready for implementation planning.

### Complexity Assessment

- **Server:** ~30 lines new code in `workers.py` (handoff helper + disposition routing change), ~5 lines in `validation.py`.
- **Frontend:** ~15 lines in `WorkerConfigModal.js` (new dropdown + computed), ~1 line in `app.js` (new prop).
- **Tests:** ~6 new test cases.
- **Risk:** Low. The change is isolated to the post-completion disposition path. All existing behavior (bare column values) is preserved with zero migration. The weak binding failure mode (→ BLOCKED) is safe and visible.
