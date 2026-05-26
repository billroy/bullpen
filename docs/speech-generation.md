# Speech Generation for Bullpen

**Date:** May 2026  
**Purpose:** Evaluate text-to-speech options for two use cases: (1) worker speech output during workflow execution, and (2) an MCP tool endpoint for triggering synthesis.

---

## Summary

| Scenario | Recommended | Rationale |
|----------|-------------|-----------|
| Local / production Linux (no GPU) | **Kokoro-82M** | Sub-300ms on CPU, Apache 2.0, tiny footprint |
| Local / macOS dev | **`say` command** | Zero deps; swap for Kokoro if quality matters |
| Cloud / lowest latency | **Cartesia Sonic-3** | 40ms TTFA; websocket streaming |
| Cloud / best naturalness | **ElevenLabs Flash v2.5** | 75ms TTFA; highest quality scores |
| Voice cloning required | **Coqui XTTS-v2** or **F5-TTS** | Both clone from short samples |
| Multilingual | **Coqui XTTS-v2** | 17 languages; mature library |

---

## Local / Offline Options

### Kokoro-82M ★ Recommended

An 82M-parameter neural TTS model released in early 2025, built on StyleTTS2/ISTFTNet. The defining characteristic is speed: it runs at RTF ~0.45–0.51 on CPU, meaning a typical 10-word sentence generates in under 300ms without any GPU. It trades voice variety and cloning for raw throughput.

- **Quality:** Wins ~44% of head-to-head comparisons on TTS Arena V2; prosody sounds natural, not robotic.
- **Latency:** <300ms CPU; ~100ms GPU.
- **Python:** HuggingFace model card + community FastAPI wrapper (`ghcr.io/remsky/kokoro-fastapi-gpu`); works with `transformers`.
- **License:** Apache 2.0 — no commercial restrictions.
- **Weaknesses:** English-only; no voice cloning; newer model with a shorter production track record.

**Why it wins for Bullpen production:** Workers need low-latency audio without requiring a GPU-equipped server. Kokoro is the only local model that reliably hits <300ms on CPU hardware.

---

### macOS `say` (dev only)

Apple's built-in TTS via Core Speech. Available via subprocess or `pyttsx3` (which wraps `NSSpeechSynthesizer`). Zero dependencies, zero cost, fast (<100ms). The Neural voices (`Siri` variants) are genuinely good.

- **Latency:** <100ms.
- **Python:** `subprocess.run(["say", text])` or `pyttsx3`.
- **Weaknesses:** macOS-only. Not usable on Linux production. Limited customization.

Use for dev iteration; ship Kokoro to Linux.

---

### Coqui TTS / XTTS-v2

Mature open-source TTS toolkit; XTTS-v2 is the multilingual model with voice cloning from a 10-second reference clip.

- **Quality:** Excellent; voice clone similarity 85–95%.
- **Latency:** ~200ms streaming with GPU; 1–5s on CPU (not viable for latency-critical workflows on CPU).
- **Python:** `pip install coqui-tts`; includes a built-in REST server.
- **License:** MPL 2.0 — review commercial use restrictions.
- **Weaknesses:** GPU is effectively required for production. Larger model footprint (4–6GB VRAM). CPU performance is poor.

Best choice if voice cloning or multilingual support (17 languages) is a hard requirement.

---

### Piper TTS

ONNX-optimized TTS from NVIDIA, designed for edge/embedded devices (Raspberry Pi, home automation). Good quality-vs-resource tradeoff.

- **Quality:** Good; 16–22kHz output; several quality tiers (x_low to high).
- **Latency:** 1–3s depending on quality tier; works on low-power hardware.
- **Python:** `pip install piper-onnx`; also CLI-friendly.
- **License:** Open-source, permissive.
- **Weaknesses:** No voice cloning; not faster than Kokoro on capable hardware.

Good fit for constrained/embedded deployments. Less relevant if the server is anything modern.

---

### F5-TTS

Flow-matching TTS that generates all tokens in parallel rather than autoregressively. Fast with GPU; supports voice cloning from ~3 seconds of audio.

- **Quality:** Among the best open models; excellent controllability.
- **Latency:** 5–8× real-time on RTX 4070; requires GPU.
- **Python:** HuggingFace/PyTorch; growing community support.
- **Weaknesses:** Poor CPU performance; newer with limited production track record.

Strong alternative to Coqui XTTS-v2 when a GPU is available and cloning is needed.

---

### edge-tts

Python client that reverse-engineers the Microsoft Edge browser's neural TTS service. High-quality neural output, no API key required.

- **Quality:** Very high (Microsoft Neural voices).
- **Latency:** 200–400ms (network-dependent).
- **Python:** `pip install edge-tts`; simple async API.
- **Weaknesses:** **Unsupported, undocumented, likely ToS violation.** Treats a free-rider on Microsoft's infrastructure as a production dependency — this is a risk. Not recommended for production.

Fine for personal hacking; not for a shipping product.

---

### Bark (Suno AI)

Transformer-based generative model that produces speech plus sound effects and music. Novel, but the wrong tool for workflow speech output.

- **Quality:** Highly realistic; supports emotion, laughter, non-verbal sounds.
- **Latency:** Very slow on CPU; 2–5s on GPU; overkill for automation.
- **License:** Open-source.
- **Weaknesses:** Slow, large, overkill. Audio limited to 24kHz.

Skip for Bullpen unless workers need ambient soundscapes, which they don't.

---

### StyleTTS2

Diffusion + style-control model with voice cloning. Expressive and high quality, but heavily GPU-dependent (~500ms on T4; 5–6s on Apple Silicon).

- Skip for CPU-only servers. Consider for high-quality offline voice cloning if a GPU is available.

---

## Cloud / API Options

All cloud options require network access and API keys. They are appropriate when quality and voice variety outweigh cost, or when local inference hardware isn't available.

### Cartesia Sonic-3 ★ Recommended for latency-critical MCP

Cartesia's real-time TTS API, optimized for conversational AI.

- **Latency:** 40ms TTFA (Turbo tier); full streaming latency ~90ms.
- **Python:** Official SDK; websocket streaming for real-time delivery.
- **Pricing:** Free tier 20k credits; Pro $5/month for 100k chars (~$0.05/1K chars).
- **Weaknesses:** Newer provider; quality trails ElevenLabs in some head-to-head tests.

The fastest option available anywhere (cloud or local). Best for an MCP endpoint where the caller is waiting.

---

### ElevenLabs Flash v2.5 ★ Recommended for best cloud quality

- **Latency:** ~75ms TTFA; 250–300ms full generation.
- **Quality:** Best-in-class naturalness and emotional range; wins most head-to-head quality evaluations.
- **Python:** Official SDK; streaming support.
- **Pricing:** $5/month starter (30k chars); $22/month creator (100k chars); ~$0.015–$0.167/1K chars depending on tier.
- **Weaknesses:** More expensive per character than Google/Amazon at volume; vendor lock-in.

The right choice when voice quality is the primary metric. The Flash v2.5 model specifically gives low latency without sacrificing naturalness.

---

### OpenAI TTS (tts-1 / tts-1-hd / gpt-4o-mini-tts)

- **Latency:** ~500ms; no published TTFA specs.
- **Quality:** Good; tts-1-hd better than tts-1.
- **Pricing:** tts-1 $15/1M chars; tts-1-hd $30/1M chars.
- **Weaknesses:** Slowest of the major cloud options; no published latency guarantees; not a strong choice if you're not already committed to OpenAI.

Choose this only if you're already deep in the OpenAI ecosystem.

---

### Google Cloud Text-to-Speech

WaveNet / Neural2 / Chirp 3 voice tiers. Enterprise-grade reliability and broad language support.

- **Latency:** 200–500ms; Chirp 3 has low-latency streaming mode.
- **Quality:** Excellent (WaveNet is among the best neural voices).
- **Pricing:** Standard 4M free chars/month then $4/M; WaveNet 1M free then $16/M; Chirp 3 1M free then $30/M.
- **Weaknesses:** More setup complexity; latency not competitive with ElevenLabs/Cartesia.

Best value at high volume (generous free tier) or when existing Google Cloud infrastructure is already in play.

---

### Amazon Polly

- **Latency:** 100–500ms.
- **Pricing:** Standard $4.80/M chars; Neural $19.20/M chars; 5M standard free/month.
- **Weaknesses:** Highest latency of the major providers; expensive for Neural voices.

Good free tier; otherwise not a strong choice compared to others.

---

### Azure Cognitive Services Speech

- **Latency:** Claims millisecond real-time latency; batch synthesis available.
- **Pricing:** Real-time ~$0.017/1K chars; batch ~$0.006/1K chars.
- **Strengths:** Batch synthesis is cheapest cloud option for non-real-time use.

Best for batch-processing workflows; less compelling for real-time MCP endpoints.

---

### Deepgram Aura-2

Part of Deepgram's unified voice-agent platform (STT + TTS + LLM orchestration).

- **Latency:** 90ms optimized TTFB; sub-200ms streaming.
- **Pricing:** $0.030/1K chars; $200 free starter credit.
- **Strengths:** Single SDK if you need STT + TTS in the same workflow.

Relevant if Bullpen workers start doing speech-to-text too. Not the right choice for pure TTS.

---

## Comparison Tables

### Cloud: Latency & Price

| Provider | Model | TTFA | Est. cost / 1K chars |
|----------|-------|------|----------------------|
| Cartesia | Sonic-3 Turbo | **40ms** | ~$0.05 |
| ElevenLabs | Flash v2.5 | **75ms** | ~$0.015–$0.17 |
| Deepgram | Aura-2 | ~90ms | $0.030 |
| Azure | Neural | ~100ms | $0.017 |
| Amazon Polly | Neural | 100–500ms | $0.019 |
| Google Cloud | Chirp 3 | 200–500ms | $0.030 |
| OpenAI | TTS-1 | ~500ms | $0.015 |

### Local: Latency & Resource Needs

| Model | CPU latency | GPU latency | VRAM | Voice clone | License |
|-------|-------------|-------------|------|-------------|---------|
| Kokoro-82M | **<300ms** | ~100ms | <2GB | No | Apache 2.0 |
| Piper | 1–3s | Low | 1–2GB | No | Permissive |
| Coqui XTTS-v2 | 1–5s | ~200ms | 4–6GB | Yes | MPL 2.0 |
| F5-TTS | High | 5–8×RT | 4–8GB | Yes | Open |
| StyleTTS2 | 5–10s | ~500ms | 6–8GB | Yes | Mixed |
| Bark | Very high | 2–5s | 8–10GB | No | Open |

---

## Architecture Recommendations

### For worker speech output

Workers should call a thin local TTS service rather than shelling out directly. This keeps the model loaded in memory across calls (no cold-start penalty) and lets you swap implementations without touching worker code.

```
Worker → HTTP POST /speak {text, voice?} → TTS service → plays audio / returns bytes
```

For macOS dev, the service wraps `say`. For Linux production, it wraps Kokoro. The interface is identical.

### For the MCP tool endpoint

The MCP tool synthesizes speech on demand. Latency is the primary concern here because the caller is blocked. Two viable paths:

1. **Local (Kokoro):** Model stays loaded; responses in <300ms on CPU. Completely offline.
2. **Cloud (Cartesia or ElevenLabs):** 40–75ms TTFA; higher quality; requires API key and network.

A clean implementation supports both, selected by config:

```python
TTS_BACKEND=kokoro   # or: elevenlabs, cartesia, say
TTS_API_KEY=...      # only used for cloud backends
```

### Audio delivery

Workers running in microsandboxes can't directly play audio on the host. Options:

- **Return audio bytes** from the MCP tool (base64-encoded WAV or MP3); the host-side MCP handler plays it via `afplay` / `aplay`.
- **Emit a Socket.IO event** with the audio payload to the browser; the frontend plays it via Web Audio API.
- **Write to a named pipe or tmp file** that a local player process is watching.

The Socket.IO approach integrates most naturally with Bullpen's existing event system and lets the browser display a visual indicator alongside the audio.

---

## Recommended Next Steps

1. **Start with `say` on macOS** — wire up a `/speak` endpoint using subprocess. Zero deps, proves the plumbing.
2. **Add Kokoro as the Linux backend** — same interface, swap in production.
3. **Expose an MCP tool** (`tts`) that POSTs to the local TTS service and returns success/audio bytes.
4. **Add a Cloud backend config** (Cartesia or ElevenLabs) for higher quality on demand, gated by env var.
5. **Stream to browser via Socket.IO** so workers can emit speech visible in the UI.
