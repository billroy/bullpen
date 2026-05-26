# Sound Effects for Bullpen

**Date:** May 2026  
**Purpose:** Evaluate sound effect options for worker-triggered audio during workflow execution, and for an MCP tool endpoint for same.

---

## Summary

| Need | Recommended | Why |
|------|-------------|-----|
| Asset library | **OpenGameArt CC0 packs** | Friction-free license, game/UI optimized |
| Supplemental sourcing | **Freesound.org API** | 700K+ sounds, Python client, CC-filterable |
| Frontend playback | **Howler.js** + **@vueuse/sound** | 7 KB, audio sprites, Vue 3 composable |
| Procedural fallback | **ZzFX** | <1 KB, zero file deps, retro/click sounds |
| Synthesis | **Tone.js** | If richer programmatic design is needed |

---

## Strategy Options

There are three approaches, not mutually exclusive:

**A. Curated static library** — download a set of 20–50 named WAV/MP3 files, host them in `static/sounds/`, expose a simple `play('name')` API. Workers reference sounds by name. Low moving parts.

**B. Freesound API integration** — a Flask endpoint or worker action fetches sounds from Freesound on demand (or on first use), cached locally. More flexible but requires API key and network.

**C. Procedural synthesis** — no audio files; sounds are generated in the browser from parameter arrays (ZzFX) or synthesizer patches (Tone.js). Zero file management but limited palette.

**Recommendation for Bullpen:** Start with A (static library from OpenGameArt CC0), add ZzFX for programmatic click/beep sounds that don't need files. Option B is available as a power-user feature if workers need to pull arbitrary sounds.

---

## Sound Asset Collections

### OpenGameArt.org ★ Recommended starting point

Curated packs of CC0 (public domain) and CC-BY sound effects aimed at game developers — which makes them well-suited for interactive/UI use. The CC0 packs have zero legal friction for commercial projects.

- **License:** CC0 (most UI packs) and CC-BY 3.0
- **Quality:** Game-developer quality; optimized for short interactive clips
- **Formats:** WAV, OGG
- **Access:** Direct bulk download; no API, no registration
- **Useful packs:** "100+ CC0 SFX", "50 RPG Sound Effects", various UI click/tap/notification packs
- **Size:** ~3 GB total archive; pick the 20–50 sounds you need

Best first step: download one or two CC0 packs and hand-curate a named set (success, error, warning, click, complete, start, etc.).

---

### Freesound.org

700,000+ user-uploaded sounds. Highly variable quality, but filterable by CC license, rating, and duration. The real value for Bullpen is the Python API client — a Flask backend could search and cache sounds dynamically.

- **License:** Mix of CC0, CC-BY, CC-BY-NC — filter carefully for commercial use
- **API:** Official FreeSound APIv2 with Python client library; supports search, filter, download
- **Formats:** MP3, WAV, OGG
- **Access:** Free tier with rate limits; registration required
- **Quality:** Variable; filter by ratings and downloads to get good results

Useful for workers that want to fetch a specific sound by search term rather than picking from a fixed palette.

---

### Sonniss GDC Audio Bundles

Annual free bundle released at the Game Developers Conference. Unambiguously commercial-safe (royalty-free, no attribution, no AI restriction notice). The full archive is 200+ GB, but the annual release is a manageable ~7 GB of professionally produced WAVs.

- **License:** Royalty-free, commercial, unlimited projects, no attribution
- **Quality:** Professional game/film production
- **Access:** Direct download; no API
- **Best for:** Ambient, cinematic, environment sounds — less UI-click-optimized than OpenGameArt

Good supplementary source for richer ambient or process-complete sounds.

---

### BBC Sound Effects (RemArc)

33,000+ archive-quality recordings, some vintage from the 1920s. Excellent quality. However, the RemArc license is **non-commercial only** — not suitable for a SaaS or commercial product without purchasing individual sounds separately.

- **License:** RemArc — research/education/personal use only
- **Skip for Bullpen** unless the product is strictly internal/non-commercial.

---

### Pixabay Sounds / Mixkit / ZapSplat

All are royalty-free, no attribution, reasonable quality. None have a usable programmatic API — they are browser-download-only services. Good for manually sourcing individual sounds to fill gaps, not for automation pipelines.

- **ZapSplat:** 160K+ sounds; WAV requires paid plan (~£4/month)
- **Pixabay:** 120K+ sounds; MP3 only; free
- **Mixkit:** Curated, professional; Envato brand; no API

Use these to hand-pick specific sounds during curation; don't build an integration around them.

---

## JavaScript Playback Libraries

### Howler.js ★ Recommended

The standard for web audio playback. 7 KB gzipped, handles MP3/WAV/OGG with graceful Web Audio API → HTML5 Audio fallback. The killer feature for Bullpen is **audio sprites**: bundle all sounds into a single file with named time-coded segments, so the browser loads one request and plays any sound by name.

```js
const sfx = new Howl({
  src: ['sounds.webm', 'sounds.mp3'],
  sprite: {
    success: [0, 800],
    error: [1000, 600],
    click: [2000, 150],
    complete: [3000, 1200],
  }
});

sfx.play('success');
```

- **License:** MIT
- **Size:** 7 KB gzip
- **Maintenance:** Actively maintained

---

### @vueuse/sound

Thin Vue 3 composable wrapper over Howler.js. Adds reactive volume/mute tracking and Vue lifecycle integration. The right choice for Vue 3 component-level sound triggers.

```js
import { useSound } from '@vueuse/sound'

const { play } = useSound('/sounds/success.mp3')
play()
```

- **License:** MIT
- **Size:** <1 KB + Howler loaded async
- **Maintenance:** VueUse org; actively maintained

For a central sound manager, wrap this in a composable that maps `play('name')` to the right file path.

---

### ZzFX ★ Recommended for procedural sounds

A 1 KB procedural sound synthesizer. Sounds are defined as arrays of 20 numbers — no audio files needed. Excellent for clicks, beeps, and simple notification tones where retro aesthetics are acceptable or desirable.

```js
import zzfx from 'zzfx'

const sounds = {
  click:   [.05, 0,  50, .01, .05,   0, 1, 1],
  success: [1,   0, 400, .05,  .1,  .1, 1, 1.5],
  error:   [1,   0, 200, .05,  .3,  .1, 1, 0.5],
}

zzfx(...sounds.click)
```

The companion [ZzFX Sound Designer](https://killedbyapixel.github.io/ZzFX/) lets you tweak parameters interactively and copy the array. No asset pipeline at all.

- **License:** MIT
- **Size:** <1 KB gzip
- **Limitation:** Retro/synthetic aesthetic only

---

### Tone.js

Full synthesis framework — oscillators, FM/AM synths, effects chains, musical timing. 50 KB gzipped. Worth it if Bullpen needs rich programmatic sound design (e.g., a sound whose pitch reflects a metric, or multi-note sequences). Overkill for simple notification sounds.

- **License:** MIT
- **Size:** ~50 KB gzip
- **Use when:** You want synthesis, not just playback

---

### jsfxr

JavaScript port of the classic `sfxr` retro sound designer. Named presets for game-style effects (pickupCoin, laserShoot, explosion, powerUp, hitHurt, jump, blipSelect). Slightly higher level than ZzFX for retro effects.

- **License:** Open-source
- **Use when:** You want retro presets without tuning parameter arrays by hand

---

## Hybrid / Bundled Approaches

### @peal-sounds/peal

A small npm package (~2 KB wrapper) that ships with 15+ curated professional UI sounds and a typed `peal.success()` / `peal.error()` API. Uses Howler.js under the hood. Essentially does the curation work for you.

Worth evaluating as a starting point, with the option to extend the sound set with additional files.

---

### Custom sound manager (recommended pattern)

For Bullpen the right shape is a thin central module that maps sound names to files (or ZzFX arrays), with a single `play(name)` call used everywhere:

```js
// static/sounds/soundManager.js
import { Howl } from 'howler'
import zzfx from 'zzfx'

const fileSprite = new Howl({
  src: ['/static/sounds/sfx.webm', '/static/sounds/sfx.mp3'],
  sprite: { /* generated from asset pipeline */ }
})

const synth = {
  click: [.05, 0, 50, .01, .05, 0, 1, 1],
  tick:  [.02, 0, 80, .01, .02, 0, 1, 1],
}

export function play(name) {
  if (fileSprite._sprite[name]) fileSprite.play(name)
  else if (synth[name]) zzfx(...synth[name])
}
```

Workers emit a Socket.IO event or call the MCP tool with `{ "sound": "complete" }`. The frontend receives it and calls `play('complete')`.

---

## Architecture: Worker → Sound

```
Worker code
  └─ emit socketio event  {"event": "play_sound", "sound": "complete"}
       └─ Vue frontend receives
            └─ soundManager.play('complete')
                 └─ Howler plays sprite segment or ZzFX synthesizes
```

For the MCP tool endpoint:

```
MCP tool: play_sound(sound: str)
  └─ emits Socket.IO event to browser session
       └─ same frontend path as above
```

The server does not need to synthesize or stream audio — it just signals the browser, which does the actual playback. This keeps audio delivery simple and avoids server-side audio processing entirely.

---

## Recommended Next Steps

1. **Pick a starter CC0 pack** from OpenGameArt and select 20–30 sounds. Name them semantically: `success`, `error`, `warning`, `click`, `task-start`, `task-complete`, `worker-start`, `worker-complete`, `notify`, `tick`, etc.
2. **Bundle into an audio sprite** using `audiosprite` (npm) — one file, named segments, one browser request.
3. **Wire up Howler.js** (or `@vueuse/sound`) to play sprites by name.
4. **Add ZzFX** for a handful of synthetic click/beep sounds that don't need files.
5. **Add a Socket.IO event** (`play_sound`) that workers can emit from Python via the existing event system.
6. **Expose an MCP tool** (`play_sound(name: str)`) that wraps the Socket.IO emit.
