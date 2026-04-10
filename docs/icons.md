# Icons Implementation

This implements the approved icon proposal from `docs/icon.md`.

## Standard

- Icon set: **Lucide** (loaded via CDN)
- Human icon: `user`
- Worker/robot icon: `bot`

## Implemented Use Cases

1. Worker cards
- Location: worker card header, before worker name
- Size: 16px
- Selection rule: show `user` when `worker.is_human === true`, `worker.type === 'human'`, or `worker.agent === 'human'`; otherwise show `bot`

2. Ticket queues (left pane worker roster)
- Location: before worker queue name
- Size: 14px
- Selection rule: same as worker cards

## Files Changed

- `static/index.html`
  - Adds Lucide CDN script (`window.lucide`)
- `static/utils.js`
  - Adds `isHumanWorker(worker)`, `getWorkerTypeIcon(worker)`, and `renderLucideIcons(rootEl)`
- `static/components/WorkerCard.js`
  - Adds icon in card header (`data-lucide="user|bot"`)
  - Renders Lucide icons on `mounted` and `updated`
- `static/components/LeftPane.js`
  - Adds icon in worker roster item (`data-lucide="user|bot"`)
  - Renders Lucide icons on `mounted` and `updated`
- `static/style.css`
  - Adds layout and size styles for card/roster icons and baseline `[data-lucide]` styling

## Example Markup

```html
<i class="worker-type-icon worker-type-icon--card" :data-lucide="workerIcon" aria-hidden="true"></i>
<i class="worker-type-icon worker-type-icon--roster" :data-lucide="workerTypeIcon(w)" aria-hidden="true"></i>
```
