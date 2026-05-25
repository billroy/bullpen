# Tokens-per-Second Header Readouts

Small **input tok/s** and **output tok/s** counters in the page header, aggregated across all active workers in the current project.

---

## Goal

Give the user a live sense of how hard the fleet is working — a glanceable throughput signal that goes to zero when workers are idle and spikes when many tasks are in flight.

---

## UX Design

Two read-only chips in `TopToolbar`, placed to the right of the project name and to the left of the connection-status dot:

```
Bullpen / my-project   in 1.4k/s  out 0.8k/s   ●
```

- **Format**: compact decimal with `k` suffix for values ≥ 1000 (e.g. `1.4k/s`), plain integer below that (e.g. `42/s`).
- **Idle state**: display `—` (en-dash) rather than `0/s` when no tokens have moved in the last measurement window.
- **Tooltip** on hover: `"Input tokens/sec (all workers)"` / `"Output tokens/sec (all workers)"`.
- No click target; purely informational.

### Visual sketch

```
[ ≡ ]  Bullpen / my-project   ↓ 1.4k/s  ↑ 832/s   ● connected
```

Arrow glyphs (`↓` input, `↑` output) keep the label short and visually distinct.

---

## Technical Approach

### Principle: pure-frontend rolling window, no new backend events

`task:updated` events already deliver cumulative `input_tokens` / `output_tokens` on every change.  The frontend can derive a rate by tracking deltas over time in a fixed-length circular buffer.  No new backend code is required to ship a first version.

### Data flow

```
server: workers.py                frontend: app.js → computed → TopToolbar
   │                                  │
   │  task:updated  {id, input_tokens, output_tokens, …}
   ├─────────────────────────────────>│
   │                                  │  record (now, Δin, Δout) in ring buffer
   │                                  │
   │  task:updated  (next update)      │
   ├─────────────────────────────────>│
   │                                  │  evict samples older than window (10 s)
   │                                  │  rate = Σ deltas / window
   │                                  │  → tokenRateIn / tokenRateOut (computed)
```

### Ring-buffer accounting

Keep a module-level (app.js) mutable object:

```js
// keyed by taskId; value is { inputTokens, outputTokens, lastSeen }
const _taskTokenBaseline = new Map();

// flat array of { ts, dIn, dOut } samples across all tasks
const _tokenSamples = [];
const TOKEN_RATE_WINDOW_MS = 10_000;
```

On every `task:updated` event:

```js
socket.on('task:updated', (data) => {
  // … existing slot/task update logic …

  const prev = _taskTokenBaseline.get(data.id) ?? { inputTokens: 0, outputTokens: 0 };
  const dIn  = Math.max(0, (data.input_tokens  ?? 0) - prev.inputTokens);
  const dOut = Math.max(0, (data.output_tokens ?? 0) - prev.outputTokens);
  _taskTokenBaseline.set(data.id, { inputTokens: data.input_tokens ?? 0, outputTokens: data.output_tokens ?? 0 });

  if (dIn > 0 || dOut > 0) {
    _tokenSamples.push({ ts: Date.now(), dIn, dOut });
  }
});
```

On `task:deleted`, remove the baseline entry so a future task reuse doesn't produce a negative delta.

### Computed rate (app.js or a small composable)

```js
const tokenRateIn  = computed(() => {
  const now = Date.now();
  const cutoff = now - TOKEN_RATE_WINDOW_MS;
  // evict stale samples (mutate in place to avoid allocation churn)
  while (_tokenSamples.length && _tokenSamples[0].ts < cutoff) _tokenSamples.shift();
  const total = _tokenSamples.reduce((s, x) => s + x.dIn, 0);
  return total === 0 ? null : Math.round(total / (TOKEN_RATE_WINDOW_MS / 1000));
});

const tokenRateOut = computed(() => { /* same with dOut */ });
```

`null` → display `—`; number → format with `k` suffix.

> **Reactivity note**: `_tokenSamples` must be a Vue `reactive([])` (or a `ref` wrapping the array) so that appending to it invalidates the computed.  A plain module-level array would not trigger recomputation.

### TopToolbar changes

Pass the two rates as props:

```js
// app.js template
<TopToolbar
  ...
  :token-rate-in="tokenRateIn"
  :token-rate-out="tokenRateOut"
/>
```

Inside `TopToolbar.js`, add a small display section:

```js
// props
tokenRateIn:  { type: Number, default: null },
tokenRateOut: { type: Number, default: null },

// helper
function fmtRate(n) {
  if (n === null) return '—';
  return n >= 1000 ? (n / 1000).toFixed(1) + 'k/s' : n + '/s';
}
```

Template fragment:

```html
<span class="token-rate" title="Input tokens/sec (all workers)">↓ {{ fmtRate(tokenRateIn) }}</span>
<span class="token-rate" title="Output tokens/sec (all workers)">↑ {{ fmtRate(tokenRateOut) }}</span>
```

---

## Files to Change

| File | Change |
|------|--------|
| `static/app.js` | Add `_taskTokenBaseline` map, `_tokenSamples` reactive array, delta recording in `task:updated` handler, baseline cleanup in `task:deleted` handler, `tokenRateIn`/`tokenRateOut` computed refs, pass as props to `TopToolbar` |
| `static/components/TopToolbar.js` | Accept two new props, add `fmtRate` helper, render the two chips with tooltip titles |
| `static/app.css` (or scoped styles) | Style `.token-rate` chips — monospace font, muted color, small right margin |

No backend changes are needed for a first version.

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Worker finishes; tokens stop arriving | Window drains to zero within 10 s → display `—` |
| Task is re-queued on same task ID | `_taskTokenBaseline` keeps the last seen value; delta will be 0 or positive, never negative |
| Task deleted mid-run (rare) | Remove entry from baseline map on `task:deleted`; pending samples in the window are still valid |
| Multiple browser tabs open | Each tab maintains its own buffer; this is fine — the readout is per-session |
| Page load / reconnect with existing tasks | `task:list` delivers current cumulative counts; set baselines from those, emit no samples — rates start from zero and build as new updates arrive |
| Cached input tokens | `cached_input_tokens` is a subset of `input_tokens` in the existing schema; no special handling needed for the rate |
| Very bursty updates (100+ tasks) | `_tokenSamples` is bounded by the eviction window; at worst a few thousand entries during a large spike, well within JS memory limits |

---

## Future Extensions (out of scope for v1)

- **Per-worker breakdown** on hover (tooltip table).
- **Backend heartbeat**: emit a server-side `metrics:token_rate` event every 2 s, computed from actual wall-clock streaming deltas, for more accurate sub-second rates.
- **Sparkline mini-chart** in the header (last 60 s).
- **Peak indicator**: dim badge showing the session high-water mark.
