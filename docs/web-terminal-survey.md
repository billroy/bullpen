# Web Terminal Libraries — State of the Art Survey

*April 2026 — Prepared for the Bullpen project*

---

## Bullpen Tech Stack Context

Bullpen is a **Vue 3 + Flask + Flask-SocketIO** app. The frontend loads all dependencies via CDN — no build step, no npm. The backend is Python with threading async mode. This shapes the integration criteria:

- Library must be loadable from a CDN `<script>` tag
- Should speak WebSocket (preferably Socket.io)
- Ideally has a Python/Flask PTY bridge pattern available

---

## Library Comparison Table

| Project | Type | Stars | Language | CDN? | Demo | Flask/Python Integration | Bullpen Fit |
|---|---|---|---|---|---|---|---|
| [**xterm.js**](https://github.com/xtermjs/xterm.js) | Full PTY emulator | ~17k | TypeScript | ✅ jsDelivr/cdnjs | [xtermjs.org](https://xtermjs.org/) | ⭐⭐⭐ via [pyxtermjs](https://github.com/cs01/pyxtermjs) pattern | **Top pick** |
| [**jQuery Terminal**](https://github.com/jcubic/jquery.terminal) | CLI framework (fake terminal) | ~3k | JavaScript | ✅ cdnjs | [terminal.jcubic.pl](https://terminal.jcubic.pl/) | ⭐⭐⭐ drop-in CDN, no PTY needed | **Good for agent output UI** |
| [**XTerminal**](https://github.com/henryhale/xterminal) | Lightweight CLI framework | ~200 | JavaScript | ✅ unpkg | [xterminal.js.org/demo](https://xterminal.js.org/demo/) | ⭐⭐ minimal deps, pure JS | Secondary option |
| [**ttyd**](https://github.com/tsl0922/ttyd) | Standalone server | ~20k | C | N/A (binary) | [tsl0922.github.io/ttyd](https://tsl0922.github.io/ttyd/) | ⭐ subprocess only, not embeddable | Not ideal |
| [**GoTTY**](https://github.com/sorenisanerd/gotty) | Standalone server | ~3.5k | Go | N/A (binary) | — | ⭐ subprocess only | Not ideal |
| [**Wetty**](https://github.com/butlerx/wetty) | Full-stack terminal | ~4.5k | Node.js | N/A | — | ⭐ Node.js only, not Flask-native | Not ideal |
| [**pyxtermjs**](https://github.com/cs01/pyxtermjs) | Flask+xterm.js reference impl | ~1.5k | Python | — | — | ⭐⭐⭐ copy-paste ready for Bullpen | **Reference pattern** |
| [**flask-terminal**](https://github.com/thevgergroup/flask-terminal) | Flask blueprint | ~50 | Python | — | — | ⭐⭐⭐ Flask blueprint, HTTP polling | Simple but limited |
| [**butterfly**](https://github.com/paradoxxxzero/butterfly) | Web terminal server | ~2.5k | Python | N/A | — | ⭐⭐ Python but uses Tornado, not Flask | Not ideal |

---

## Integration Recommendation

**The natural path is xterm.js + a lightweight Python PTY bridge over the existing Socket.io channel.**

### Frontend

Load xterm.js and its FitAddon via CDN in `index.html` (both are available on cdnjs/jsDelivr — no build step change needed):

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5/css/xterm.css">
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5/lib/xterm.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10/lib/addon-fit.js"></script>
```

Add a new Vue component — e.g. `TerminalTab.js` — that instantiates `xterm.Terminal` and connects to a dedicated Socket.io event channel.

### Backend

Add a handler in `events.py` using Python's built-in `pty` module to spawn a subprocess (e.g. `bash`, or a `claude` agent session), forwarding I/O over the existing `flask-socketio` connection. This is exactly the pattern demonstrated by [pyxtermjs](https://github.com/cs01/pyxtermjs).

### Why this fits Bullpen

- One new component file (`TerminalTab.js`)
- A few new Socket.io event handlers in `events.py`
- Two CDN additions to `index.html`
- No changes to the build system, no npm
- Reuses the existing Flask-SocketIO infrastructure already in the app

### Alternative: jQuery Terminal for agent output

If the goal is a stylized output panel for streaming agent logs rather than a full interactive shell, **jQuery Terminal** is a lighter-weight option. It has no PTY requirement, supports custom command handlers, and is trivially loadable from cdnjs. It would be simpler to integrate but won't support raw ANSI escape codes or interactive programs.

---

## Sources

- [xterm.js GitHub](https://github.com/xtermjs/xterm.js)
- [xterm.js official site](https://xtermjs.org/)
- [pyxtermjs – Flask + xterm.js reference](https://github.com/cs01/pyxtermjs)
- [flask-terminal – Flask blueprint](https://github.com/thevgergroup/flask-terminal)
- [jQuery Terminal](https://github.com/jcubic/jquery.terminal) / [demo](https://terminal.jcubic.pl/)
- [XTerminal (henryhale)](https://github.com/henryhale/xterminal) / [demo](https://xterminal.js.org/demo/)
- [ttyd](https://github.com/tsl0922/ttyd) / [site](https://tsl0922.github.io/ttyd/)
- [GoTTY](https://github.com/sorenisanerd/gotty)
- [Wetty](https://github.com/butlerx/wetty)
- [butterfly](https://github.com/paradoxxxzero/butterfly)
- [Best Open Source Web Terminals – sabujkundu.com](https://sabujkundu.com/best-open-source-web-terminals-for-embedding-in-your-browser/)
- [10 Best Terminal Emulators in JS/jQuery – jqueryscript.net](https://www.jqueryscript.net/blog/best-terminal-emulator.html)
