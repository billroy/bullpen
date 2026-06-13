# Notification Workers

Notification workers are pass-through worker-grid cards that give the human
operator explicit feedback when a ticket reaches a workflow stage. They do not
call an agent, run a shell command, or supervise a service. Their work is to
emit one or more local UI/audio/visual notification effects, then route the
ticket onward through the normal Bullpen disposition pipeline.

The intended use is workflow awareness:

```text
Implementation -> Notification: "Ready for review" -> Review
Deploy -> Notification: chime + flash -> Smoke test
Agent error lane -> Notification: spoken warning -> Human triage
```

V1 is an in-browser/local feature. It does not send push notifications,
emails, Slack messages, or operating-system notifications, and it does not
guarantee that an operator heard or saw the notification.

---

## Goals

- Add `type: "notification"` as a first-class worker type.
- Let a notification worker fire any combination of:
  - toast message,
  - synthesized speech,
  - short sound effect,
  - screen flash.
- Make notification text templatable from ticket, worker, and workspace data.
- Reuse the existing worker-grid mental model: notification workers accept
  dropped, queued, manual, and scheduled tickets like other worker types.
- Reuse the existing disposition grammar so a notification worker can be a
  visible workflow waypoint.
- Keep notification delivery bounded, rate-limited, dismissible, and respectful
  of accessibility preferences.
- Make the implementation small enough to land incrementally without disturbing
  AI, Shell, Service, or Marker worker behavior.

## Non-goals

- No remote delivery channels in v1: email, SMS, Slack, webhook, APNs, FCM,
  desktop push, or browser Notification API.
- No acknowledgement/blocking workflow in v1. A ticket should not wait for a
  user to click "heard it" or "seen it."
- No arbitrary JavaScript in templates.
- No user-uploaded sound packs in v1.
- No per-ticket modification by default beyond normal status/assignment
  transitions.
- No server-side TTS service in v1. Browser-native speech and Kokoro.js cover
  the first implementation.

---

## User Stories

### Review handoff

The operator routes all completed implementation tickets through a notification
worker configured to show a distinct toast and speak:

```text
"{ticket.title} is ready for review."
```

The worker then routes the ticket to `review`.

### Long-running automation

A scheduled worker creates reports overnight. When a report reaches the final
stage, a notification worker plays a quiet completion sound and flashes the
screen once so the operator notices it when returning to the browser.

### Error escalation

A worker chain routes blocked deployment tickets to a notification worker that
uses a warning toast, error sound, and spoken text. The notification worker then
routes the ticket to `blocked`.

### Visual waypoint

The operator uses a notification worker as a labeled waypoint in the grid:

```text
Build -> Notify QA -> QA worker
```

The card makes the workflow stage visible even when all notification channels
are disabled by the client.

---

## Worker Type Model

Reserve this worker type:

```text
type: "notification"
```

Notification workers are runnable, but they do not spawn subprocesses. Their
runtime is closest to Marker workers: they receive a ticket, perform a bounded
server-side action, and immediately apply disposition.

### Slot Fields

| Field | Type | Default | Notes |
|---|---|---:|---|
| `type` | string | `"notification"` | Worker type id |
| `name` | string | `"Notification worker"` | Visible card label |
| `activation` | string | `"on_drop"` | Same trigger modes as runnable workers |
| `disposition` | string | `"review"` | Same disposition grammar as other workers |
| `watch_column` | string/null | `null` | Used when activation is `on_queue` |
| `max_retries` | number | `0` | Notification dispatch is non-retryable in v1 |
| `trigger_time` | string/null | `null` | Scheduler field |
| `trigger_interval_minutes` | number/null | `null` | Scheduler field |
| `trigger_every_day` | boolean | `false` | Scheduler field |
| `last_trigger_time` | number/null | `null` | Runtime field |
| `paused` | boolean | `false` | Same automation pause behavior |
| `task_queue` | list | `[]` | Runtime queue |
| `state` | string | `"idle"` | Runtime state |
| `notification` | object | see below | Type-specific channel config |
| `icon` | string | `"bell-ring"` | UI default |
| `color` | string | `"notification"` | UI color token |

### Notification Config Shape

Store channel configuration under a single type-specific `notification` object:

```json
{
  "toast": {
    "enabled": true,
    "template": "{ticket.title} reached {worker.name}.",
    "variant": "stage",
    "duration_ms": 6000
  },
  "speech": {
    "enabled": false,
    "template": "{ticket.title} is ready.",
    "voice": "",
    "engine": "default",
    "rate": 1.0,
    "volume": 1.0
  },
  "sound": {
    "enabled": false,
    "effect": "done",
    "repeat_count": 1,
    "gap_ms": 250,
    "volume": 1.0
  },
  "flash": {
    "enabled": false,
    "sequence": [
      { "color": "#facc15", "duration_ms": 180 }
    ],
    "opacity": 0.35
  },
  "policy": {
    "cooldown_ms": 1000,
    "dedupe_window_ms": 3000
  }
}
```

Normalization should fill missing nested objects while preserving unknown
future fields. Client serialization does not need redaction because these
fields are operator-visible workflow configuration, not secrets.

### Validation Rules

- `name` is required and follows existing worker-name constraints.
- At least one channel must be enabled for a notification worker to be useful,
  but all channels disabled is allowed. This lets the card act as a silent
  pass-through while preserving user/client accessibility settings.
- `toast.template` and `speech.template` max length: 2,000 chars before
  rendering.
- Rendered toast text max length: 500 chars.
- Rendered speech text max length: 800 chars.
- `toast.duration_ms`: 1,000-30,000.
- `speech.rate`: 0.5-2.0.
- `speech.volume`: 0.0-1.0.
- `sound.repeat_count`: 1-5.
- `sound.gap_ms`: 100-2,000.
- `sound.volume`: 0.0-1.0.
- `flash.sequence`: 1-6 color/duration steps.
- Each flash `duration_ms`: 50-1,000.
- Flash color must be a hex color.
- Flash sequences must not exceed three flashes per second and must respect
  `prefers-reduced-motion`.
- `policy.cooldown_ms`: 0-60,000.
- `policy.dedupe_window_ms`: 0-300,000.
- Invalid disposition values block the ticket using the same deterministic
  failure behavior as Marker workers.

---

## Runtime Semantics

### Assignment

When a ticket reaches a Notification worker:

1. Bullpen begins the normal shared worker lifecycle.
2. The worker renders its configured templates against the current ticket,
   worker, and workspace context.
3. The server marks the worker `working`, marks the ticket `in_progress`, and
   emits one Socket.IO `notification:fire` event to connected clients in the
   same workspace room.
4. A browser client starts every enabled notification channel. Toast, sound, and
   flash effects do not gate routing. Spoken notification text gates routing
   until model load, generation, and playback finish.
5. The browser emits `notification:complete` with the delivery id, slot, and
   ticket id.
6. The server verifies the pending delivery still matches the worker and ticket,
   then applies the worker's configured disposition.
7. The worker returns to `idle` and drains any runnable queue behind it.

The ticket waits for spoken notification delivery completion when speech is
enabled. V1 delivery means "the browser started the configured local effects,
and any spoken message has completed or failed according to policy," not merely
"the server published intent."

If automation is paused or the worker is stopped before completion, the ticket
remains assigned at the notification worker and does not advance to the next
worker. Late completion acknowledgements from cancelled deliveries are ignored.

If no browser client is connected, the worker must not silently route the ticket
onward as though a notification was delivered. The server keeps the delivery
pending for 120 seconds, then blocks the ticket with a notification delivery
timeout.

### Trigger Model

Notification workers support the same activation modes as other pass-through
worker types:

- `on_drop`: a dropped ticket triggers notification immediately.
- `on_queue`: the worker watches a column, claims tickets, and notifies.
- `manual`: Run notifies the head queued ticket. If the queue is empty, create
  the same synthetic manual worker-run ticket used by other runnable workers,
  notify against that ticket, and apply the configured disposition.
- `at_time` / `on_interval`: scheduler triggers work the same way as other
  workers. Empty scheduled runs use the shared synthetic-ticket behavior.

### Failure Policy

Notification dispatch is best effort and client-side effects can fail for many
legitimate reasons: browser audio lock, muted tab, unsupported WebGPU, reduced
motion, hidden tab throttling, or a disconnected browser.

V1 treats these as delivery outcomes, not invisible background details. A
notification worker must not advance a ticket until the client either completes
delivery or reports failure. The server-side failures that block the ticket are:

- invalid notification config that should have been caught at save time,
- invalid disposition,
- missing ticket at queue head,
- notification delivery failure or the 120 second delivery timeout,
- unexpected server exception while rendering the notification payload.

### Ticket Audit

V1 does not append notification output to the ticket body by default. The
browser already receives the live feedback, and appending a body block on every
notification would make workflow-stage workers noisy.

For debugging, the server may log compact notification records under
`.bullpen/logs/notifications/` with a retention cap, but this is not required
for the first user-facing release.

---

## Template Rendering

Notification templates use a safe, non-evaluating placeholder renderer.
Recommended syntax:

```text
{ticket.title}
{ticket.id}
{ticket.status}
{ticket.priority}
{ticket.type}
{ticket.assigned_to}
{worker.name}
{worker.type}
{workspace.name}
{workspace.path}
```

Rules:

- Placeholder syntax is single-brace `{root.property}` interpolation to match
  the rest of Bullpen's product docs and value-worker direction.
- Unknown placeholders render as an empty string.
- Placeholders are plain property lookups only. No filters, function calls,
  loops, conditionals, arithmetic, or dotted access outside the approved root
  objects.
- Rendered text is stripped of control characters except newline and tab.
- Toast text collapses whitespace to a single line.
- Speech text may preserve punctuation, but should collapse repeated
  whitespace.
- HTML is never interpreted; client rendering uses text nodes.

Implementation location:

- Add a small server helper, for example `server/templates.py`, or place the
  helper beside existing worker text assembly if there is a stronger local
  pattern at implementation time.
- Unit-test the helper independently from worker execution.

---

## Socket.IO Contract

Add a workspace-scoped server event:

```text
notification:fire
```

Payload:

```json
{
  "id": "notif_20260613_153012_abc123",
  "workspaceId": "default",
  "slot": 4,
  "worker": {
    "name": "Notify review",
    "type": "notification"
  },
  "ticket": {
    "id": "ticket-123",
    "title": "Fix deploy preview"
  },
  "channels": {
    "toast": {
      "enabled": true,
      "text": "Fix deploy preview is ready for review.",
      "variant": "stage",
      "duration_ms": 6000
    },
    "speech": {
      "enabled": false,
      "text": "",
      "voice": "",
      "engine": "default",
      "rate": 1.0,
      "volume": 1.0
    },
    "sound": {
      "enabled": true,
      "effect": "done",
      "repeat_count": 1,
      "gap_ms": 250,
      "volume": 1.0
    },
    "flash": {
      "enabled": false,
      "sequence": [],
      "opacity": 0.35
    }
  },
  "policy": {
    "cooldown_ms": 1000,
    "dedupe_window_ms": 3000
  },
  "created_at": "2026-06-13T15:30:12Z"
}
```

Do not send full ticket bodies in this event. The server should render the
template before emitting and send only the small text actually needed for
client notification.

The event is intentionally separate from the existing generic `toast` event so
notification-worker toasts can be styled, rate-limited, and muted separately
from system errors.

---

## Client Notification Runtime

Add a small frontend module, for example `static/notification-worker.js`, that
subscribes to `notification:fire` and owns all client-side delivery policy.

Responsibilities:

- Apply local mute/settings gates.
- Apply per-worker cooldown and dedupe.
- Queue or collapse bursts.
- Render notification toasts using a distinct visual style.
- Play selected sound effects through the existing `window.ambientAudio`
  engine where possible.
- Speak text through the selected TTS engine.
- Show screen flash overlays with accessibility limits.
- Surface nonfatal client delivery errors in the console or audio menu, not as
  recursive notification toasts.

### Client Policy

Defaults:

- Maximum visible notification-worker toasts: 3.
- Maximum queued notification toasts: 20.
- Collapse identical `(worker, ticket, rendered text)` notifications inside
  `dedupe_window_ms`.
- At most one sound/speech/flash notification starts per 250 ms globally.
- If a burst arrives, preserve the newest notification and the highest-severity
  effect.
- Respect the app-wide audio mute and event-sound settings.
- Provide a separate "Notification workers" mute toggle in the audio menu.

This should reuse the spirit of `static/event-sounds.js`: suppress floods,
collapse bursts, and keep operator feedback informative rather than frantic.

### Toast UI

Notification-worker toasts must be visually distinct from system toasts.

Requirements:

- Use a `toast-notification` class or a dedicated notification toast container.
- Include the worker name when space permits.
- Use a bell icon or equivalent visual marker.
- Default variant `stage` should not look like `error`, `success`, or system
  connection warnings.
- Toast text must fit and wrap cleanly on mobile.
- Close buttons and auto-dismiss behavior match existing toasts.

### Screen Flash UI

Screen flash is a full-viewport overlay above the app chrome but below modal
dialogs where practical. It should never capture pointer events.

Requirements:

- Disabled automatically when `prefers-reduced-motion: reduce` is active unless
  the user explicitly re-enables it.
- Hard cap at three flashes per second.
- Hard cap total sequence duration at 3 seconds.
- Opacity cap of 0.5.
- No alternating red/blue default patterns.
- Global "disable flashes" setting in the audio/notification menu.

---

## Speech

Speech is optional and client-side in v1.

### Engines

Supported engines:

1. `default`: use Web Speech API when available.
2. `web-speech`: explicit Web Speech API.
3. `kokoro`: use Kokoro.js when available and loaded.

The default should be Web Speech API because it requires no model download and
works well enough for short operator feedback. Kokoro is the higher-quality
local model path.

### Kokoro.js

Kokoro.js behavior:

- Lazy-load on first use or when the user clicks "Load Kokoro" in the audio
  control panel.
- Show first-time download state clearly in the audio menu, including rough
  size and progress when available.
- Cache model assets using the browser's normal cache/IndexedDB behavior used
  by the library.
- Expose available voices in the audio control panel.
- Let a worker choose "global default voice" or an explicit Kokoro voice.
- If Kokoro is not supported or fails to load, fall back to Web Speech API when
  the worker's engine is `default`; otherwise skip speech and mark the engine
  status as unavailable in the audio menu.

Initial Kokoro voice list can mirror `static/tts-playground.html`:

```text
af_heart, af_bella, af_nicole, am_michael, am_fenrir, bf_emma, bm_george
```

Do not auto-download Kokoro on page load. The first-time model download is too
large to surprise the user.

### Speech Queueing

- Only one utterance plays at a time by default.
- New speech notifications interrupt older speech from the same worker.
- Different workers queue up to three utterances total.
- A global Stop speech control cancels the queue.
- Speech is disabled until the browser audio context / speech system has been
  unlocked by a user gesture, consistent with browser autoplay rules.

---

## Sound Effects

V1 should use the existing synthesized audio engine instead of adding a file
asset pipeline.

Add a named sound-effect registry that maps stable effect ids to existing or
new `AudioEngine` methods:

| Effect id | Initial implementation |
|---|---|
| `toast` | `playToast()` |
| `start` | `playStart()` |
| `done` | `playDone()` |
| `move` | `playMove()` |
| `warning` | new short warning tone or reuse `playError()` at lower volume |
| `error` | `playError()` |
| `spawn` | `playSpawn()` |
| `despawn` | `playDespawn()` |

The worker config modal should present effect ids as labels in a dropdown.
Repeat count is bounded and should replay the same named effect with `gap_ms`.

Custom sound packs, Howler.js, and downloaded WAV/MP3 assets remain deferred.

---

## Configuration UI

The worker create/configure flow should include Notification in the worker type
library.

Recommended card defaults:

- icon: `bell-ring`
- color token: `notification`
- label: `Notification`
- default name: `Notification worker`

### Theme Integration

The real dialog must follow the active Bullpen page theme. The mockup's dark
colors are illustrative only; implementation should use the existing modal,
form, menu, toast, and worker-card CSS variables/classes wherever possible.

Requirements:

- Do not introduce a hard-coded Notification dialog palette.
- Use the active theme's background, border, text, muted-text, input, focus,
  button, and modal tokens.
- Treat the notification color as an accent only, equivalent to provider or
  worker color accents.
- Verify the form in dark, light, and at least one high-contrast/colorful theme.
- Notification toasts should also adapt to the active theme while remaining
  distinguishable from system toasts.

The config modal should show:

- Name
- Input Trigger / activation
- Watch column and schedule fields when relevant
- Output / Pass tickets to
- Toast channel toggle, template, variant, duration
- Speech channel toggle, template, engine, voice, rate, volume
- Sound channel toggle, effect, repeat count, volume
- Flash channel toggle, color sequence editor, opacity
- Notification policy: cooldown and dedupe window

Fields to hide:

- agent/model/profile
- expertise prompt
- trust mode
- worktree / auto-commit / auto-pr
- shell command/cwd/env
- service command/pre-start/health/process controls
- Marker note

Add lightweight template help near the text fields, but avoid turning the modal
into a documentation page. A small "Insert variable" menu is preferable to a
long list of visible helper text.

A static visual mockup lives at
[docs/notification-worker-config-mockup.html](notification-worker-config-mockup.html).
There is also a rendered PNG snapshot at
[docs/notification-worker-config-mockup.png](notification-worker-config-mockup.png).
It is intentionally not wired to application state; its job is to settle field
grouping, channel density, and the audio-control relationship before building
the real Vue form.

### Audio Control Panel

Extend the existing audio dropdown with:

- Notification workers master toggle.
- Speech master toggle.
- Stop speech button.
- Default speech engine selector.
- Web Speech voice selector when voices are available.
- Kokoro model status and Load button.
- Kokoro voice selector when loaded.
- Screen flash enable/disable toggle.

This is also where first-time Kokoro download progress belongs.

---

## Accessibility and Safety

Notification workers deliberately create sensory output, so the feature needs
strict defaults and escape hatches.

Requirements:

- Respect `prefers-reduced-motion`; disable flash by default for those users.
- Keep flash under WCAG seizure-risk limits: no more than three flashes per
  second, no extreme high-contrast alternating patterns by default.
- Provide global mute toggles for sound, speech, and flash.
- Do not rely on color alone in notification toasts; include icon/text.
- Do not auto-load or auto-play speech until the user has interacted with the
  page and browser policies allow it.
- Make all notification controls reachable by keyboard.
- Keep screen flash overlays `pointer-events: none`.
- Keep toast close buttons accessible and labelled.
- Do not use notification effects for system-critical errors that require
  guaranteed delivery; V1 is best-effort local feedback.

---

## Implementation Plan

### Phase 1: Core Pass-through Worker

Status: implemented.

Backend:

- Add `"notification"` to `VALID_WORKER_TYPES`.
- Add `NotificationWorkerType` in `server/worker_types.py`.
- Normalize `notification`, `icon`, and `color` fields.
- Add notification color token to provider/worker color validation.
- Allow `worker:add` to create notification workers.
- Add `_run_notification_worker()` in `server/workers.py`.
- Validate disposition before routing.
- Render templates server-side.
- Emit `notification:fire`.
- Route ticket through `_on_agent_success()` with `allow_auto_actions=False`
  and an output appender that does not modify ticket body.

Frontend:

- Add Notification to worker type creation UI.
- Add notification-specific config fields to `WorkerConfigModal`.
- Add notification card label/icon/color handling to `WorkerCard`.
- Add `static/notification-worker.js` with toast, sound, and flash support.
- Wire the module in `static/index.html` and app startup.

Tests:

- Worker slot normalization preserves notification fields.
- `worker:add` creates a notification worker with defaults.
- Config validation bounds templates, durations, repeat count, and flash colors.
- Dropping a ticket on a notification worker emits `notification:fire`.
- Notification worker applies configured disposition.
- Invalid disposition blocks the ticket.
- Queue drains after notification worker succeeds.

### Phase 2: Speech

Status: partially implemented. Web Speech API support is included in the
client runtime; Kokoro.js lazy loading remains pending.

Frontend:

- Add Web Speech API support to `static/notification-worker.js`.
- Add global speech controls to the audio menu.
- Add voice selector and settings persistence in `localStorage`.
- Add Kokoro.js lazy loader using the playground as the implementation
  reference.
- Add Kokoro load/progress/status UI.
- Add fallback behavior from `default` to Web Speech API.

Tests:

- Unit-test speech queue policy where feasible.
- Frontend smoke test that receiving `notification:fire` calls the speech
  runtime when speech is enabled.
- Manual QA across Chrome/Safari/Firefox for Web Speech voice enumeration.
- Manual QA for Kokoro first-load, cached reload, unsupported-browser fallback.

### Phase 3: Hardening and Polish

Status: pending.

- Add a compact notification history/debug panel if real use shows operators
  need auditability beyond ticket movement.
- Add richer sound-effect registry entries.
- Add import/export/team/transfer round-trip tests specific to Notification
  workers.
- Add Playwright coverage for toast overflow, mobile layout, and flash disabled
  under reduced motion.
- Add documentation to README worker type list after the feature ships.

---

## Acceptance Criteria

- A user can add a Notification worker to the grid.
- A user can configure toast, sound, flash, and speech settings without seeing
  irrelevant AI/Shell/Service fields.
- Dropping a ticket on the worker produces a notification event and then routes
  the ticket to the configured destination.
- Notification toasts are visually distinct from system toasts.
- A burst of notifications cannot create unbounded visible toasts, sounds,
  speech, or flash effects.
- Flash respects reduced-motion preferences and hard safety caps.
- Speech works through Web Speech API without downloading Kokoro.
- Kokoro does not download until explicit load or first selected use.
- Unknown or unsupported client delivery failures do not block tickets.
- Existing AI, Shell, Service, and Marker workers keep their behavior.

---

## Review

### R1: Client-side delivery is best effort

The main product question is whether a notification worker should merely emit
feedback or require confirmation. This spec chooses best-effort delivery for
v1 because blocking ticket flow on browser playback would make scheduled and
unattended worker chains fragile. If guaranteed human acknowledgement becomes a
requirement, add a separate "Approval" or "Acknowledge" worker rather than
overloading Notification.

### R2: Kokoro first-load cost needs explicit consent

The original note suggested automatic first-time Kokoro model download. The
current spec changes that to lazy/explicit load because the model is large
enough to surprise users and may be a poor fit on some browsers. Web Speech API
should be the no-download default, with Kokoro as an opt-in quality upgrade.

### R3: Sound-effect library is enough for v1

The existing synthesized audio engine already has enough distinct sounds for a
first implementation. A curated file-based library can wait until operators
actually need richer effects.

### R4: Toast overflow needs a separate notification policy

`ToastContainer` currently displays only the last five toasts, but the backing
list can still grow and notification workers can intentionally fire many
messages. Notification-worker toasts need their own visible cap, queue cap,
dedupe, and cooldown rather than relying on the generic system toast path.

### R5: Accessibility is part of the core feature

Screen flash and speech are not decorative implementation details. They must
ship with reduced-motion handling, mute controls, keyboard-accessible settings,
and seizure-risk caps. Without those controls, flash should not ship.

### R6: Synthetic ticket behavior follows runnable workers

Notification workers are runnable workers, not marker-only pass-through
decorations. Empty manual and scheduled runs must create the shared synthetic
worker-run ticket, emit notification intent for that ticket, and then route it
through the configured disposition.

### R7: Template rendering should stay intentionally small

It will be tempting to add filters, conditionals, and formatting. Keep v1 to
approved property lookups. Notification text should be predictable, safe, and
easy to validate.
