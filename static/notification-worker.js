/**
 * Notification worker client runtime.
 *
 * Handles the server's notification:fire intent with local, best-effort
 * delivery. This module deliberately keeps its own toast stack and settings so
 * workflow-stage notifications cannot flood system toasts.
 */
(function () {
  const STORAGE_KEY = 'bullpen.notificationWorkers';
  const MAX_TOASTS = 20;
  const VISIBLE_TOASTS = 3;
  const GLOBAL_START_GAP_MS = 250;
  const KOKORO_IMPORT_URL = 'https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js';
  const KOKORO_MODEL_ID = 'onnx-community/Kokoro-82M-v1.0-ONNX';
  const KOKORO_DEFAULT_VOICE = 'af_heart';
  const KOKORO_VOICES = [
    { value: 'af_heart', label: 'Heart - US female' },
    { value: 'af_bella', label: 'Bella - US female' },
    { value: 'af_nicole', label: 'Nicole - US female' },
    { value: 'am_michael', label: 'Michael - US male' },
    { value: 'am_fenrir', label: 'Fenrir - US male' },
    { value: 'bf_emma', label: 'Emma - UK female' },
    { value: 'bm_george', label: 'George - UK male' },
  ];

  const DEFAULT_FLAGS = {
    enabled: true,
    toasts: true,
    sounds: true,
    speech: true,
    flash: true,
    reducedMotionFlash: false,
  };

  const SOUND_METHODS = {
    toast: 'playToast',
    start: 'playStart',
    done: 'playDone',
    move: 'playMove',
    warning: 'playError',
    error: 'playError',
    spawn: 'playSpawn',
    despawn: 'playDespawn',
  };

  function loadFlags() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return { ...DEFAULT_FLAGS, ...(parsed && typeof parsed === 'object' ? parsed : {}) };
    } catch (_err) {
      return { ...DEFAULT_FLAGS };
    }
  }

  function saveFlags(flags) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(flags));
    } catch (_err) {}
  }

  const NotificationWorkers = {
    flags: loadFlags(),
    _attached: false,
    _toasts: [],
    _toastRoot: null,
    _flashRoot: null,
    _recent: new Map(),
    _workerCooldowns: new Map(),
    _lastStart: 0,
    _speechQueue: [],
    _speaking: false,
    _socket: null,
    _activeDeliveries: new Map(),
    _kokoroTTS: null,
    _kokoroLoading: null,
    _kokoroStatus: 'not-loaded',
    _kokoroError: '',

    getFlags() {
      return { ...this.flags };
    },

    getKokoroVoices() {
      return KOKORO_VOICES.map(voice => ({ ...voice }));
    },

    getKokoroStatus() {
      return { status: this._kokoroStatus, error: this._kokoroError };
    },

    setFlag(key, value) {
      if (!(key in DEFAULT_FLAGS)) return;
      this.flags[key] = !!value;
      saveFlags(this.flags);
      if (key === 'speech' && !this.flags.speech) this.stopSpeech();
      this.renderToasts();
    },

    resetFlags() {
      this.flags = { ...DEFAULT_FLAGS };
      saveFlags(this.flags);
      this.renderToasts();
    },

    stopSpeech() {
      for (const item of this._speechQueue.splice(0)) {
        try { item.resolve?.(); } catch (_err) {}
      }
      this._speaking = false;
      try {
        window.speechSynthesis?.cancel();
      } catch (_err) {}
      try {
        this._currentAudio?.pause?.();
      } catch (_err) {}
      this._currentAudio = null;
    },

    init(socket) {
      if (!socket || this._attached) return;
      this._attached = true;
      this._socket = socket;
      socket.on('notification:fire', payload => this.handle(payload));
      socket.on('notification:cancel', payload => this.cancelDelivery(payload));
    },

    handle(payload) {
      if (!payload || typeof payload !== 'object') return;
      if (!this.flags.enabled) {
        this.completeDelivery(payload, 'complete');
        return;
      }
      if (this._shouldDedupe(payload)) {
        this.completeDelivery(payload, 'complete');
        return;
      }
      const run = () => {
        this._deliver(payload)
          .then(() => this.completeDelivery(payload, 'complete'))
          .catch(err => this.completeDelivery(payload, 'failed', err?.message || String(err || 'delivery failed')));
      };
      const now = Date.now();
      const gap = now - this._lastStart;
      if (gap >= GLOBAL_START_GAP_MS) {
        this._lastStart = now;
        run();
        return;
      }
      setTimeout(() => {
        this._lastStart = Date.now();
        run();
      }, Math.max(0, GLOBAL_START_GAP_MS - gap));
    },

    completeDelivery(payload, status = 'complete', error = '') {
      if (!this._socket || !payload) return;
      const deliveryId = String(payload.id || payload.delivery_id || '');
      if (deliveryId) this._activeDeliveries.delete(deliveryId);
      this._socket.emit('notification:complete', {
        workspaceId: payload.workspaceId,
        delivery_id: deliveryId,
        slot: payload.slot,
        task_id: payload.ticket?.id || payload.task_id || '',
        status,
        error,
      });
    },

    cancelDelivery(payload) {
      const deliveryId = String(payload?.delivery_id || payload?.id || '');
      if (!deliveryId) return;
      const active = this._activeDeliveries.get(deliveryId);
      if (active?.cancel) active.cancel();
      this._activeDeliveries.delete(deliveryId);
    },

    _shouldDedupe(payload) {
      const policy = payload.policy || {};
      const now = Date.now();
      const workerKey = String(payload.slot ?? payload.worker?.name ?? 'worker');
      const cooldownMs = Math.max(0, Number(policy.cooldown_ms || 0));
      const lastWorker = this._workerCooldowns.get(workerKey) || 0;
      if (cooldownMs && now - lastWorker < cooldownMs) return true;
      this._workerCooldowns.set(workerKey, now);

      const toastText = payload.channels?.toast?.text || '';
      const speechText = payload.channels?.speech?.text || '';
      const dedupeText = toastText || speechText || payload.ticket?.title || '';
      const dedupeKey = `${workerKey}:${payload.ticket?.id || ''}:${dedupeText}`;
      const dedupeWindowMs = Math.max(0, Number(policy.dedupe_window_ms || 0));
      const lastSame = this._recent.get(dedupeKey) || 0;
      if (dedupeWindowMs && now - lastSame < dedupeWindowMs) return true;
      this._recent.set(dedupeKey, now);
      return false;
    },

    async _deliver(payload) {
      const channels = payload.channels || {};
      const deliveryId = String(payload.id || '');
      const controllers = [];
      if (deliveryId) {
        this._activeDeliveries.set(deliveryId, {
          cancel: () => {
            for (const cancel of controllers) {
              try { cancel(); } catch (_err) {}
            }
            this.stopSpeech();
          },
        });
      }
      try {
        const promises = [];
        if (channels.toast?.enabled && this.flags.toasts) this.addToast(payload);
        if (channels.sound?.enabled && this.flags.sounds) this.playSound(channels.sound);
        if (channels.speech?.enabled && this.flags.speech) promises.push(this.speak(channels.speech, payload));
        if (channels.flash?.enabled && this.flags.flash) this.flash(channels.flash);
        await Promise.all(promises);
      } finally {
        if (deliveryId) this._activeDeliveries.delete(deliveryId);
      }
    },

    ensureToastRoot() {
      if (this._toastRoot) return this._toastRoot;
      const root = document.createElement('div');
      root.className = 'notification-worker-toast-container';
      root.setAttribute('aria-live', 'polite');
      root.setAttribute('aria-label', 'Notification worker messages');
      document.body.appendChild(root);
      this._toastRoot = root;
      return root;
    },

    addToast(payload) {
      const toast = payload.channels?.toast || {};
      const id = payload.id || `notification-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const item = {
        id,
        text: String(toast.text || payload.ticket?.title || 'Notification'),
        worker: String(payload.worker?.name || 'Notification worker'),
        variant: String(toast.variant || 'stage'),
      };
      this._toasts.push(item);
      this._toasts = this._toasts.slice(-MAX_TOASTS);
      this.renderToasts();
      const duration = Math.max(1000, Math.min(Number(toast.duration_ms || 6000), 30000));
      return new Promise(resolve => {
        setTimeout(() => {
          this.dismissToast(id);
          resolve();
        }, duration);
      });
    },

    dismissToast(id) {
      this._toasts = this._toasts.filter(toast => toast.id !== id);
      this.renderToasts();
    },

    renderToasts() {
      const root = this.ensureToastRoot();
      root.innerHTML = '';
      if (!this.flags.enabled || !this.flags.toasts) return;
      for (const toast of this._toasts.slice(-VISIBLE_TOASTS)) {
        const el = document.createElement('div');
        el.className = `notification-worker-toast notification-worker-toast--${toast.variant}`;

        const icon = document.createElement('span');
        icon.className = 'notification-worker-toast-icon';
        icon.textContent = '!';
        el.appendChild(icon);

        const body = document.createElement('span');
        body.className = 'notification-worker-toast-body';
        const title = document.createElement('span');
        title.className = 'notification-worker-toast-title';
        title.textContent = toast.worker;
        const text = document.createElement('span');
        text.className = 'notification-worker-toast-text';
        text.textContent = toast.text;
        body.appendChild(title);
        body.appendChild(text);
        el.appendChild(body);

        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'notification-worker-toast-close';
        close.setAttribute('aria-label', 'Dismiss notification');
        close.textContent = 'x';
        close.addEventListener('click', () => this.dismissToast(toast.id));
        el.appendChild(close);
        root.appendChild(el);
      }
      if (window.renderLucideIcons) window.renderLucideIcons(root);
    },

    playSound(sound) {
      if (!window.ambientAudio) return Promise.resolve();
      const method = SOUND_METHODS[String(sound.effect || 'done')] || 'playDone';
      const repeat = Math.max(1, Math.min(Number(sound.repeat_count || 1), 5));
      const gap = Math.max(100, Math.min(Number(sound.gap_ms || 250), 2000));
      for (let i = 0; i < repeat; i += 1) {
        setTimeout(() => {
          try { window.ambientAudio.unlock(); } catch (_err) {}
          try { window.ambientAudio._duckAmbient?.(6, 300); } catch (_err) {}
          try { window.ambientAudio[method]?.(); } catch (_err) {}
        }, i * gap);
      }
      return new Promise(resolve => setTimeout(resolve, ((repeat - 1) * gap) + 350));
    },

    speak(speech, payload) {
      if (!speech.text) return Promise.resolve();
      const workerKey = String(payload.slot ?? payload.worker?.name ?? 'worker');
      for (const item of this._speechQueue.filter(item => item.workerKey === workerKey)) {
        try { item.resolve?.(); } catch (_err) {}
      }
      this._speechQueue = this._speechQueue.filter(item => item.workerKey !== workerKey);
      const promise = new Promise((resolve, reject) => {
        this._speechQueue.push({ speech, workerKey, resolve, reject });
        this._speechQueue = this._speechQueue.slice(-3);
        this._drainSpeech();
      });
      return promise;
    },

    _drainSpeech() {
      if (this._speaking || !this._speechQueue.length) return;
      const next = this._speechQueue.shift();
      const engine = String(next.speech.engine || 'kokoro').toLowerCase();
      this._speaking = true;
      if (engine === 'kokoro') {
        this._speakKokoro(next.speech)
          .then(() => next.resolve?.())
          .catch(err => {
            this._kokoroError = err?.message || String(err || 'Kokoro speech failed');
            this._kokoroStatus = 'failed';
            console.warn('Notification worker Kokoro speech failed:', err);
            next.reject?.(err);
          })
          .finally(() => {
            this._speaking = false;
            this._drainSpeech();
          });
        return;
      }
      if (engine === 'default') {
        this._speakKokoro(next.speech)
          .catch(() => this._speakWebSpeechPromise(next.speech))
          .then(() => next.resolve?.())
          .catch(err => next.reject?.(err))
          .finally(() => {
            this._speaking = false;
            this._drainSpeech();
          });
        return;
      }
      const spoken = this._speakWebSpeech(next.speech, () => {
        next.resolve?.();
        this._speaking = false;
        this._drainSpeech();
      });
      if (!spoken) {
        next.reject?.(new Error('Web Speech is unavailable'));
        this._speaking = false;
        this._drainSpeech();
      }
    },

    async loadKokoro() {
      if (this._kokoroTTS) return this._kokoroTTS;
      if (this._kokoroLoading) return this._kokoroLoading;
      this._kokoroStatus = 'loading';
      this._kokoroError = '';
      this._kokoroLoading = (async () => {
        const module = typeof window.BULLPEN_KOKORO_LOADER === 'function'
          ? await window.BULLPEN_KOKORO_LOADER()
          : await import(window.BULLPEN_KOKORO_IMPORT_URL || KOKORO_IMPORT_URL);
        const KokoroTTS = module.KokoroTTS;
        if (!KokoroTTS?.from_pretrained) throw new Error('KokoroTTS loader is unavailable');
        const device = navigator.gpu ? 'webgpu' : 'wasm';
        const dtype = device === 'webgpu' ? 'fp32' : 'q8';
        const tts = await KokoroTTS.from_pretrained(KOKORO_MODEL_ID, { dtype, device });
        this._kokoroTTS = tts;
        this._kokoroStatus = 'ready';
        this._kokoroLoading = null;
        return tts;
      })().catch(err => {
        this._kokoroLoading = null;
        this._kokoroStatus = 'failed';
        this._kokoroError = err?.message || String(err || 'Kokoro load failed');
        throw err;
      });
      return this._kokoroLoading;
    },

    async _speakKokoro(speech) {
      const tts = await this.loadKokoro();
      const voice = KOKORO_VOICES.some(item => item.value === speech.voice)
        ? speech.voice
        : KOKORO_DEFAULT_VOICE;
      const result = await tts.generate(String(speech.text || ''), { voice });
      const blob = typeof result?.toBlob === 'function' ? result.toBlob() : result;
      if (!blob) throw new Error('Kokoro did not return audio');
      const url = URL.createObjectURL(blob);
      try {
        await this._playGeneratedAudio(url, speech);
      } finally {
        try { URL.revokeObjectURL(url); } catch (_err) {}
      }
    },

    _playGeneratedAudio(url, speech) {
      return new Promise((resolve, reject) => {
        const audio = new Audio(url);
        this._currentAudio = audio;
        audio.volume = Math.max(0, Math.min(Number(speech.volume ?? 1), 1));
        audio.playbackRate = Math.max(0.5, Math.min(Number(speech.rate ?? 1), 2));
        audio.onended = () => {
          if (this._currentAudio === audio) this._currentAudio = null;
          resolve();
        };
        audio.onerror = () => {
          if (this._currentAudio === audio) this._currentAudio = null;
          reject(new Error('Generated Kokoro audio could not play'));
        };
        try {
          const playResult = audio.play();
          if (playResult?.catch) playResult.catch(reject);
        } catch (err) {
          reject(err);
        }
      });
    },

    _speakWebSpeech(speech, done) {
      const synth = window.speechSynthesis;
      if (!synth) return false;
      const utterance = new SpeechSynthesisUtterance(String(speech.text || ''));
      utterance.rate = Math.max(0.5, Math.min(Number(speech.rate ?? 1), 2));
      utterance.volume = Math.max(0, Math.min(Number(speech.volume ?? 1), 1));
      const voiceName = String(speech.voice || '').trim();
      if (voiceName) {
        const voice = synth.getVoices().find(v => v.name === voiceName || v.voiceURI === voiceName);
        if (voice) {
          utterance.voice = voice;
          utterance.lang = voice.lang;
        }
      }
      utterance.onend = () => {
        if (typeof done === 'function') done();
      };
      utterance.onerror = () => {
        if (typeof done === 'function') done();
      };
      try {
        synth.speak(utterance);
        return true;
      } catch (_err) {
        return false;
      }
    },

    _speakWebSpeechPromise(speech) {
      return new Promise((resolve, reject) => {
        const ok = this._speakWebSpeech(speech, resolve);
        if (!ok) reject(new Error('Web Speech is unavailable'));
      });
    },

    flash(flash) {
      const prefersReduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
      if (prefersReduced && !this.flags.reducedMotionFlash) return Promise.resolve();
      const sequence = Array.isArray(flash.sequence) ? flash.sequence.slice(0, 6) : [];
      if (!sequence.length) return Promise.resolve();
      const opacity = Math.max(0, Math.min(Number(flash.opacity ?? 0.35), 0.5));
      const root = this.ensureFlashRoot();
      let offset = 0;
      for (const step of sequence) {
        const duration = Math.max(50, Math.min(Number(step.duration_ms || 180), 1000));
        const color = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(String(step.color || ''))
          ? String(step.color)
          : '#facc15';
        setTimeout(() => {
          root.style.background = color;
          root.style.opacity = String(opacity);
        }, offset);
        offset += duration;
        setTimeout(() => {
          root.style.opacity = '0';
        }, offset);
        offset += Math.max(120, duration);
        if (offset > 3000) break;
      }
      return new Promise(resolve => setTimeout(resolve, offset));
    },

    ensureFlashRoot() {
      if (this._flashRoot) return this._flashRoot;
      const root = document.createElement('div');
      root.className = 'notification-worker-flash';
      document.body.appendChild(root);
      this._flashRoot = root;
      return root;
    },
  };

  window.NotificationWorkers = NotificationWorkers;
  window.NOTIFICATION_WORKER_FLAGS_DEFAULTS = { ...DEFAULT_FLAGS };
  window.NOTIFICATION_WORKER_KOKORO_VOICES = KOKORO_VOICES.map(voice => ({ ...voice }));
})();
