# Icon System — Recommendation

## Decision: Lucide Icons via CDN

**Lucide** is the best fit for Bullpen. It's the maintained fork of Feather Icons
with 1,500+ icons, MIT licensed, and available as a simple ES module from CDN —
no build step required.

### Why Lucide over alternatives

| Library         | Icons | Size (full) | CDN ESM | Style        | Notes                          |
|-----------------|-------|-------------|---------|--------------|--------------------------------|
| **Lucide**      | 1,500+| ~180 KB     | Yes     | Stroke-based | Active, tree-shakeable via ESM |
| Font Awesome    | 2,000+| ~400 KB     | Yes     | Mixed        | Heavy, free tier limited       |
| Material Icons  | 2,500+| ~600 KB     | Yes     | Filled       | Google aesthetic, heavy        |
| Heroicons       | 300   | ~50 KB      | Yes     | Stroke/solid | Small set, may need more later |
| Tabler Icons    | 4,500+| ~500 KB     | Yes     | Stroke-based | Large but heavier              |

Lucide wins because:
- Stroke-based style matches the lightweight, utilitarian feel of the existing UI
- Individual icons can be imported by name — no need to load the full set
- First-class ESM support: `import { User, Bot } from 'lucide'`
- Active maintenance (weekly releases)
- Consistent 24×24 grid, 2px stroke, round joins

### Integration approach

Add to `index.html`:

```html
<script type="module">
  import { createIcons, User, Bot, /* ...others */ } from
    'https://esm.sh/lucide@latest';
  window.lucideIcons = { createIcons, User, Bot };
</script>
```

Use in templates:

```html
<i data-lucide="user"></i>    <!-- human icon -->
<i data-lucide="bot"></i>     <!-- worker/robot icon -->
```

Call `lucideIcons.createIcons()` after Vue mounts or after dynamic content
renders to replace `<i>` tags with inline SVGs.

Alternatively, render SVGs directly in Vue templates using Lucide's icon data
(each icon exports an array of SVG element descriptors).

---

## Use Case 1: Worker Cards

Each worker card should show a small icon indicating whether it represents a
human or an AI worker.

### Suggested icons

| Meaning     | Lucide icon name | Visual                | Notes                           |
|-------------|------------------|-----------------------|---------------------------------|
| **Human**   | `user`           | Person silhouette (👤) | Universal, immediately readable |
| **AI/Robot**| `bot`            | Robot face (🤖)        | Clearly "not human"             |

### Placement

Place the icon in the worker card header, to the left of the worker name. Size
it at 16×16px to match the existing compact card aesthetic.

```
┌──────────────────────────┐
│ 🤖 worker-alpha   ⋯     │  ← icon before name
│ status: working          │
│ ▲ pass-up                │
└──────────────────────────┘
```

### Example markup (WorkerCard.js)

```html
<span class="worker-icon">
  <i data-lucide="bot" style="width:16px;height:16px;"></i>
</span>
<span class="worker-name">{{ worker.name }}</span>
```

---

## Use Case 2: Ticket Queues

Ticket queues in the left pane should indicate whether they belong to a human
queue or an AI worker queue.

### Suggested icons

Same `user` / `bot` pair, sized at 14×14px to fit the sidebar list density.

### Placement

Inline before the queue name in the left pane worker roster.

```
Left Pane — Workers
───────────────────
  🤖 worker-alpha (3)
  🤖 worker-beta  (1)
  👤 human-review (5)
```

### Example markup (LeftPane.js)

```html
<li v-for="w in workers" class="queue-item">
  <i :data-lucide="w.is_human ? 'user' : 'bot'"
     style="width:14px;height:14px;"></i>
  {{ w.name }}
  <span class="queue-count">({{ w.queue_length }})</span>
</li>
```

---

## Other icons likely needed soon

| Purpose              | Lucide icon     | Notes                              |
|----------------------|-----------------|------------------------------------|
| Add / create ticket  | `plus`          | Replace text "+" buttons           |
| Settings / config    | `settings`      | Worker config modal trigger        |
| Refresh / sync       | `refresh-cw`    | Manual refresh actions             |
| Trash / delete       | `trash-2`       | Delete confirmations               |
| Chat / conversation  | `message-square` | Live agent chat tab               |
| File / document      | `file-text`     | Files tab                          |
| Git commit           | `git-commit`    | Commits tab                        |
| Search               | `search`        | Filter/search inputs               |
| Sun / Moon (theme)   | `sun` / `moon`  | Replace current Unicode ☀/☽        |

---

## CSS considerations

Lucide renders inline `<svg>` elements. Add baseline styles:

```css
[data-lucide] {
  display: inline-block;
  vertical-align: middle;
  stroke: currentColor;
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
```

This ensures icons inherit text color from the surrounding context and work
correctly in both light and dark themes without extra effort.
