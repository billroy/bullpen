const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(path.join(root, 'static/notification-worker.js'), 'utf8');

const calls = {
  generated: [],
  played: [],
  webSpeech: [],
  imports: [],
  objectUrls: [],
  revoked: [],
  emitted: [],
};

class FakeAudio {
  constructor(url) {
    this.url = url;
    this.volume = 1;
    this.playbackRate = 1;
    this.onended = null;
    this.onerror = null;
  }

  play() {
    calls.played.push({ url: this.url, volume: this.volume, playbackRate: this.playbackRate });
    setTimeout(() => {
      if (this.onended) this.onended();
    }, 0);
    return Promise.resolve();
  }

  pause() {}
}

function SpeechSynthesisUtterance(text) {
  this.text = text;
}

const context = {
  console,
  setTimeout,
  clearTimeout,
  navigator: {},
  Audio: FakeAudio,
  SpeechSynthesisUtterance,
  URL: {
    createObjectURL(blob) {
      const url = `blob:${blob.id || calls.objectUrls.length}`;
      calls.objectUrls.push({ url, blob });
      return url;
    },
    revokeObjectURL(url) {
      calls.revoked.push(url);
    },
  },
  document: {
    createElement: () => ({
      className: '',
      style: {},
      children: [],
      appendChild(child) { this.children.push(child); },
      setAttribute() {},
      addEventListener() {},
    }),
    body: { appendChild() {} },
  },
  window: {
    BULLPEN_KOKORO_IMPORT_URL: 'mock:kokoro',
    speechSynthesis: {
      getVoices: () => [{ name: 'Samantha', voiceURI: 'samantha-uri', lang: 'en-US' }],
      speak: (utterance) => {
        calls.webSpeech.push(utterance.text);
        if (utterance.onend) setTimeout(utterance.onend, 0);
      },
      cancel() {},
    },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() {} },
  },
};
context.globalThis = context;
context.window.window = context.window;
context.window.document = context.document;
context.window.navigator = context.navigator;
context.window.Audio = FakeAudio;
context.window.URL = context.URL;
context.window.SpeechSynthesisUtterance = SpeechSynthesisUtterance;
context.window.BULLPEN_KOKORO_LOADER = async () => {
  calls.imports.push('test-loader');
  return {
    KokoroTTS: {
      from_pretrained: async (model, options) => ({
        model,
        options,
        generate: async (text, opts) => {
          calls.generated.push({ text, opts, model, options });
          return { toBlob: () => ({ id: `${opts.voice}:${text}` }) };
        },
      }),
    },
  };
};

vm.createContext(context);
vm.runInContext(source, context);

const runtime = context.window.NotificationWorkers;

async function waitFor(predicate, timeoutMs = 1000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error('Timed out waiting for runtime condition');
}

(async () => {
  runtime.speak({
    enabled: true,
    engine: 'kokoro',
    voice: 'af_bella',
    text: 'Kokoro should speak this',
    rate: 1.2,
    volume: 0.42,
  }, {
    slot: 3,
    worker: { name: 'Kokoro Notify' },
  });

  await waitFor(() => calls.generated.length === 1 && calls.played.length === 1);

  if (calls.imports[0] !== 'test-loader') {
    throw new Error(`Expected Kokoro import, got ${calls.imports[0]}`);
  }
  if (calls.generated[0].text !== 'Kokoro should speak this') {
    throw new Error('Kokoro did not receive rendered speech text');
  }
  if (calls.generated[0].opts.voice !== 'af_bella') {
    throw new Error(`Expected selected Kokoro voice af_bella, got ${calls.generated[0].opts.voice}`);
  }
  if (calls.generated[0].options.device !== 'wasm' || calls.generated[0].options.dtype !== 'q8') {
    throw new Error('Kokoro loader did not use the expected WASM fallback options');
  }
  if (calls.played[0].volume !== 0.42) {
    throw new Error(`Expected generated audio volume 0.42, got ${calls.played[0].volume}`);
  }
  if (calls.played[0].playbackRate !== 1.2) {
    throw new Error(`Expected generated audio playbackRate 1.2, got ${calls.played[0].playbackRate}`);
  }
  if (calls.webSpeech.length) {
    throw new Error('Kokoro engine unexpectedly used Web Speech');
  }
  if (runtime.getKokoroStatus().status !== 'ready') {
    throw new Error(`Expected Kokoro ready status, got ${runtime.getKokoroStatus().status}`);
  }

  runtime.speak({
    enabled: true,
    engine: 'kokoro',
    voice: 'not-real',
    text: 'Fallback voice',
    volume: 1,
  }, {
    slot: 3,
    worker: { name: 'Kokoro Notify' },
  });

  await waitFor(() => calls.generated.length === 2);
  if (calls.generated[1].opts.voice !== 'af_heart') {
    throw new Error(`Expected invalid Kokoro voice to fall back to af_heart, got ${calls.generated[1].opts.voice}`);
  }

  const handlers = {};
  runtime._attached = false;
  runtime.init({
    on(event, handler) { handlers[event] = handler; },
    emit(event, payload) { calls.emitted.push({ event, payload }); },
  });
  handlers['notification:fire']({
    id: 'delivery-1',
    workspaceId: 'ws-test',
    slot: 7,
    worker: { name: 'Kokoro Notify' },
    ticket: { id: 'ticket-1', title: 'Ticket 1' },
    channels: {
      toast: { enabled: false },
      sound: { enabled: false },
      flash: { enabled: false },
      speech: {
        enabled: true,
        engine: 'kokoro',
        voice: 'af_bella',
        text: 'Delivery handshake',
        rate: 1,
        volume: 1,
      },
    },
    policy: { cooldown_ms: 0, dedupe_window_ms: 0 },
  });

  await waitFor(() => calls.emitted.length === 1);
  if (calls.emitted[0].event !== 'notification:complete') {
    throw new Error(`Expected notification:complete, got ${calls.emitted[0].event}`);
  }
  if (calls.emitted[0].payload.delivery_id !== 'delivery-1') {
    throw new Error('Completion payload did not include delivery id');
  }
  if (calls.emitted[0].payload.task_id !== 'ticket-1') {
    throw new Error('Completion payload did not include ticket id');
  }

  calls.emitted.length = 0;
  runtime.addToast = () => new Promise(() => {});
  runtime.playSound = () => new Promise(() => {});
  runtime.flash = () => new Promise(() => {});
  handlers['notification:fire']({
    id: 'delivery-2',
    workspaceId: 'ws-test',
    slot: 8,
    worker: { name: 'Nonblocking Notify' },
    ticket: { id: 'ticket-2', title: 'Ticket 2' },
    channels: {
      toast: { enabled: true, text: 'Toast should not block', duration_ms: 30000 },
      sound: { enabled: true, effect: 'done' },
      flash: { enabled: true, sequence: [{ color: '#00ff88', duration_ms: 500 }] },
      speech: { enabled: false },
    },
    policy: { cooldown_ms: 0, dedupe_window_ms: 0 },
  });

  await waitFor(() => calls.emitted.length === 1, 250);
  if (calls.emitted[0].payload.delivery_id !== 'delivery-2') {
    throw new Error('Toast/sound/flash-only delivery did not complete immediately');
  }

  process.stdout.write(JSON.stringify(calls, null, 2));
})().catch(err => {
  console.error(err);
  process.exit(1);
});
