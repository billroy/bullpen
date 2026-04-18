# Event Sounds — Worker-Driven Audio Feedback

## Motivation

Bullpen users keep the UI running alongside other windows. State changes
(worker finishes, task gets created, error surfaces) are easy to miss.
Short synthesized sounds give the user "ambient awareness" of workspace
state without requiring focus on the window.

The goal is **information, not decoration**: every sound should map to a
distinct, meaningful state transition that the user would otherwise only
notice by looking at the screen.

## Prior Art in the Codebase

A full Web Audio engine already exists at [static/audio.js](../static/audio.js)
and is globally exposed as `window.ambientAudio`. Relevant surface:

| Method | What it does |
|---|---|
| `_tone(f1, f2, dur, type, vol)` | single oscillator, optional frequency sweep |
| `_noise(dur, vol)` | white noise burst |
| `playToast()` | two-note chime, C6 → E6 |
| `playSpawn()` | ascending chirp (400→800 Hz) |
| `playDespawn()` | descending chirp (800→300 Hz) |
| `playClientJoin()` / `playClientLeave()` | currently unused |
| `playActivitySound(type)` | 20+ per-widget effects |
| `unlock()` / `mute()` / `unmute()` / `setVolume(0..1)` | engine controls |

All six `play*` event methods are **implemented but never called** — the
engine is wired only for ambient loops today
([static/app.js:138-148](../static/app.js)). The first user interaction
calls `ambientAudio.unlock()` ([static/app.js:1133](../static/app.js)),
so the AudioContext is ready by the time any worker event arrives.

**This spec adds the wiring only** — no new synthesis primitives are
required for the first cut. New tones can be composed from `_tone` and
`_noise` where existing `play*` methods don't fit the event.

## Source Events

All candidate events are already emitted by the server. No backend
changes are required for Phase 1.

### Task lifecycle — [server/events.py](../server/events.py)

| Event | Payload | Fires when |
|---|---|---|
| `task:created` | full task | MCP or UI creates a ticket ([events.py:281](../server/events.py)) |
| `task:updated` | full task | any field changes, including status ([events.py:312](../server/events.py)) |
| `task:deleted` | `{id}` | ticket deleted ([events.py:326](../server/events.py)) |

`task:updated` is the richest signal. The task model has a `status`
field with values `inbox | assigned | in_progress | review | done | blocked`
([server/init.py:18](../server/init.py)). We can diff the prior
status (the frontend already holds the task list in memory) to
distinguish meaningful transitions.

### Worker lifecycle — [server/workers.py](../server/workers.py), [server/events.py](../server/events.py)

| Event | Payload | Fires when |
|---|---|---|
| `layout:updated` | full layout | slot state flips (idle ↔ running), slot reconfigured ([workers.py:200](../server/workers.py)) |
| `worker:output` | `{slot, lines}` | streaming output — **too chatty for sound, skip** ([workers.py:752](../server/workers.py)) |
| `worker:output:done` | `{slot, lines}` | worker finishes processing a task ([workers.py:885](../server/workers.py)) |

`layout:updated` is the best-quality "worker started" signal when
diffed against the previous layout (look for slots that transitioned
`idle → working`). `worker:output:done` is emitted on both success
and failure but its payload (`{slot, lines}`) does not carry an exit
code, so the "worker error" sound keys off the `status → blocked`
transition instead (agent failures move the task to `blocked`).

### Errors & notifications

| Event | Payload | Fires when |
|---|---|---|
| `error` | `{message, code?}` | server-side exception surfaces to client ([events.py:254](../server/events.py)) |
| `toast` | `{message, type}` | server-driven toast ([workers.py:207](../server/workers.py)) |

### Connection — already has code paths

Client join/leave is not currently emitted as distinct socket events
in a form the frontend receives, but `playClientJoin/Leave` methods
exist — tracked under Phase 2.

## Event → Sound Mapping (Phase 1)

The mapping is opinionated but small. Each sound must be distinct
enough to identify by ear without looking, and short enough
(< 250 ms) to not intrude on other audio.

| Trigger | Sound | Rationale |
|---|---|---|
| `task:created` | `playSpawn()` (ascending chirp) | "something new appeared" — matches existing spawn semantic |
| status → `in_progress` (from `task:updated`) | new: `playStart()` — two-note rising, E5→B5, triangle | worker picked up the task |
| status → `done` (from `task:updated`) | new: `playDone()` — three-note major triad arpeggio, C5→E5→G5 | clearest "success" signal; worth the extra length |
| status → `blocked` (from `task:updated`) | new: `playError()` — buzz: `_noise(0.08)` + low `_tone(180, 120, 0.15, 'sawtooth')` | worker failed — authoritative negative signal |
| status → `inbox` (reverting, from `task:updated`) | new: `playRevert()` — descending minor third, A4→F4 | a task was kicked back; subtle but audible |
| `task:deleted` | `playDespawn()` (descending chirp) | matches existing despawn semantic |
| `layout:updated` where slot went `idle → working` | reuse `playStart()` | same meaning as task starting |
| `worker:output:done` | *no sound* — covered by status transitions (`done`/`blocked`) | payload lacks exit code; avoid double-firing |
| `error` event | `playError()` | server-reported problem |
| `toast` event, `level: 'error'` (or `type: 'error'`) | `playError()` | server uses `level`, client accepts either |
| `toast` event, other levels | `playToast()` (existing) | |

### Moved / reassigned tickets

"Moved" is a `task:updated` where `assigned_to` or column position
changes but status does not. Options:

- **Option A (recommended for Phase 1):** no sound — movement is usually
  user-driven drag-and-drop, and the user already knows they did it.
- **Option B (Phase 2):** quiet "tick" sound only for moves initiated
  by other clients (distinguishable by presence of a `_moved_by` field
  the server would need to add). Gated behind an explicit setting.

## Framework: Event Sound Dispatcher

A thin module `static/event-sounds.js` owns the event→sound mapping
and the policy layer. It subscribes to socket events in the existing
socket handlers ([static/app.js:386-569](../static/app.js)).

### Shape

```js
// static/event-sounds.js
const EventSounds = {
  enabled: true,                 // master on/off (separate from ambient)
  perEvent: { /* see below */ }, // per-event enable flags
  _ready: false,                 // set true after state:init replay completes
  _recent: new Map(),            // key → timestamp, for debouncing
  _taskStatus: new Map(),        // taskId → last-known status, for diffs

  init(socket) { /* attach listeners */ },
  primeTaskState(tasks) { /* after state:init, seed _taskStatus */ },
  _fire(key, playFn) { /* debounce + policy, then call playFn */ },
};
```

### Policy rules

1. **Suppress during initial load.** After `state:init`, seed
   `_taskStatus` from the payload and set `_ready = true` on the next
   tick. Events that arrive before `_ready` produce no sound. This
   prevents a flood on reconnect.
2. **Debounce per event key.** Any sound fires at most once per
   `DEBOUNCE_MS` (default 120 ms) per `(eventType, entityId)` key. A
   user dragging a ticket that triggers three updates should beep
   once, not three times.
3. **Global rate limit.** At most one event sound per 250 ms overall.
   If a burst arrives, collapse to a single sound picked by severity
   (error > done > start > create > delete > move).
4. **Ambient ducking.** When an event sound fires, temporarily
   reduce `_ambientGain` by −6 dB for 300 ms so the event is audible
   over the ambient bed. Add a helper to `AudioEngine`:
   `_duckAmbient(depth, durationMs)`.
5. **Ignore own actions (optional, Phase 2).** If the client has a
   `socket.id`, the server can echo it in event payloads as
   `_originator`. The dispatcher drops sounds for its own events.
   Phase 1 accepts the user hearing their own actions.

### Per-event enable flags

Surfaced in the existing settings UI alongside ambient controls.
Stored in `localStorage` under `bullpen.eventSounds`:

```json
{
  "enabled": true,
  "taskCreated": true,
  "taskStarted": true,
  "taskDone":    true,
  "taskDeleted": true,
  "taskReverted": false,
  "workerError": true,
  "serverError": true,
  "toast":       true
}
```

Default: everything on except `taskReverted` (reverts are usually
self-initiated cleanup and the sound becomes noise).

### New AudioEngine methods

Add to [static/audio.js](../static/audio.js):

```js
playStart()    // E5(659) → B5(988), 0.09s triangle, vol 0.25
playDone()     // C5(523), E5(659), G5(784); three notes, 60ms apart, sine
playRevert()   // A4(440) → F4(349), 0.12s sine, vol 0.18
playError()    // _noise(0.08, 0.10) + _tone(180, 120, 0.15, 'sawtooth', 0.2)
_duckAmbient(dBDepth, durationMs)
```

Each reuses existing `_tone` and `_noise`; no new synthesis code.

## Phasing

**Phase 1 (this spec) — implemented.** Frontend-only. No server
changes. One new file ([static/event-sounds.js](../static/event-sounds.js)),
four new methods + `_duckAmbient()` in [static/audio.js](../static/audio.js),
a bell-icon dropdown in [static/components/TopToolbar.js](../static/components/TopToolbar.js)
for per-event toggles (stored in `localStorage` under `bullpen.eventSounds`),
and `EventSounds.init(socket)` wired in [static/app.js](../static/app.js)
— the dispatcher attaches its own `socket.on` listeners alongside the
existing ones rather than editing each handler.

**Phase 2 (follow-up).**
- Server echoes `_originator` (connecting `socket.id`) in `task:*`
  and `layout:updated` so clients can suppress sounds for their own
  actions.
- Emit `client:joined` / `client:left` socket events and wire the
  existing `playClientJoin/Leave` methods.
- "Move" sound for cross-client drag events.
- Per-workspace defaults in `config:updated`.

## Out of Scope

- Configurable sound packs (custom WAVs, user-uploaded sounds). The
  synthesis-only constraint keeps the bundle small and the UX
  consistent.
- Spatial / stereo cues. Mono is enough for six distinct event types.
- Sound for `worker:output` streaming lines. The existing
  `playActivitySound(type)` machinery is for ambient panels, not for
  per-line feedback — per-line sounds would be unbearable.

## Open Questions

1. Should `task:created` fire when the *user on this client* is the one
   who created it? Phase 1 says yes (simpler, and the sound provides
   confirmation). Reconsider if it feels noisy in practice.
2. Should `playDone()` be louder than other sounds? Success is the most
   important signal for unattended runs. Recommendation: same volume,
   but give it a distinctive three-note pattern so it's unmistakable.
3. Does ambient ducking belong in Phase 1 or Phase 2? Included in
   Phase 1 because without it, event sounds get buried when
   `ambient_active` is on — which is common.
