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

    getFlags() {
      return { ...this.flags };
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
      this._speechQueue = [];
      this._speaking = false;
      try {
        window.speechSynthesis?.cancel();
      } catch (_err) {}
    },

    init(socket) {
      if (!socket || this._attached) return;
      this._attached = true;
      socket.on('notification:fire', payload => this.handle(payload));
    },

    handle(payload) {
      if (!this.flags.enabled || !payload || typeof payload !== 'object') return;
      if (this._shouldDedupe(payload)) return;
      const run = () => this._deliver(payload);
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

    _deliver(payload) {
      const channels = payload.channels || {};
      if (channels.toast?.enabled && this.flags.toasts) this.addToast(payload);
      if (channels.sound?.enabled && this.flags.sounds) this.playSound(channels.sound);
      if (channels.speech?.enabled && this.flags.speech) this.speak(channels.speech, payload);
      if (channels.flash?.enabled && this.flags.flash) this.flash(channels.flash);
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
      setTimeout(() => this.dismissToast(id), duration);
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
      if (!window.ambientAudio) return;
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
    },

    speak(speech, payload) {
      const synth = window.speechSynthesis;
      if (!synth || !speech.text) return;
      const workerKey = String(payload.slot ?? payload.worker?.name ?? 'worker');
      this._speechQueue = this._speechQueue.filter(item => item.workerKey !== workerKey);
      this._speechQueue.push({ speech, workerKey });
      this._speechQueue = this._speechQueue.slice(-3);
      this._drainSpeech();
    },

    _drainSpeech() {
      if (this._speaking || !this._speechQueue.length) return;
      const synth = window.speechSynthesis;
      if (!synth) return;
      const next = this._speechQueue.shift();
      const utterance = new SpeechSynthesisUtterance(String(next.speech.text || ''));
      utterance.rate = Math.max(0.5, Math.min(Number(next.speech.rate ?? 1), 2));
      utterance.volume = Math.max(0, Math.min(Number(next.speech.volume ?? 1), 1));
      const voiceName = String(next.speech.voice || '').trim();
      if (voiceName) {
        const voice = synth.getVoices().find(v => v.name === voiceName || v.voiceURI === voiceName);
        if (voice) {
          utterance.voice = voice;
          utterance.lang = voice.lang;
        }
      }
      utterance.onend = () => {
        this._speaking = false;
        this._drainSpeech();
      };
      utterance.onerror = () => {
        this._speaking = false;
        this._drainSpeech();
      };
      this._speaking = true;
      try {
        synth.speak(utterance);
      } catch (_err) {
        this._speaking = false;
      }
    },

    flash(flash) {
      const prefersReduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
      if (prefersReduced && !this.flags.reducedMotionFlash) return;
      const sequence = Array.isArray(flash.sequence) ? flash.sequence.slice(0, 6) : [];
      if (!sequence.length) return;
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
})();
