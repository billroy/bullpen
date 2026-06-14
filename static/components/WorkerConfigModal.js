const DEFAULT_NOTIFICATION_FORM = {
  toast: {
    enabled: true,
    template: '{ticket.title} reached {worker.name}.',
    variant: 'stage',
    duration_ms: 6000,
  },
  speech: {
    enabled: false,
    template: '{ticket.title} is ready.',
    voice: 'af_heart',
    engine: 'kokoro',
    rate: 1.0,
    volume: 1.0,
  },
  sound: {
    enabled: false,
    effect: 'done',
    repeat_count: 1,
    gap_ms: 250,
    volume: 1.0,
  },
  flash: {
    enabled: false,
    sequence: [{ color: '#facc15', duration_ms: 180 }],
    opacity: 0.35,
  },
  policy: {
    cooldown_ms: 1000,
    dedupe_window_ms: 3000,
  },
};

const KOKORO_VOICE_OPTIONS = [
  { value: 'af_heart', label: 'Heart - US female' },
  { value: 'af_bella', label: 'Bella - US female' },
  { value: 'af_nicole', label: 'Nicole - US female' },
  { value: 'am_michael', label: 'Michael - US male' },
  { value: 'am_fenrir', label: 'Fenrir - US male' },
  { value: 'bf_emma', label: 'Emma - UK female' },
  { value: 'bm_george', label: 'George - UK male' },
];

function cloneNotificationForm(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  const merged = JSON.parse(JSON.stringify(DEFAULT_NOTIFICATION_FORM));
  for (const key of Object.keys(merged)) {
    if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      merged[key] = { ...merged[key], ...source[key] };
    }
  }
  if (Array.isArray(source.flash?.sequence)) {
    merged.flash.sequence = source.flash.sequence.length
      ? source.flash.sequence.map(step => ({
          color: step?.color || '#facc15',
          duration_ms: Number(step?.duration_ms || 180),
        }))
      : [{ color: '#facc15', duration_ms: 180 }];
  }
  return merged;
}

const WorkerConfigModal = {
  props: ['worker', 'slotIndex', 'columns', 'workers', 'gridRows', 'gridCols', 'providerColors', 'defaultProviderColors', 'activeWorkspaceId'],
  emits: ['close', 'save', 'remove', 'save-profile'],
  data() {
    return {
      form: {},
      overlayMouseDown: false,
      servicePreview: null,
      servicePreviewError: '',
      servicePreviewLoading: false,
      serviceSuggestedPort: null,
      servicePortAutoFilled: false,
      servicePreviewSeq: 0,
      servicePreviewTimer: null,
      workerColorPickerInput: null,
      opencodeModels: [],
      opencodeModelsStatus: '',
      opencodeModelsError: '',
      opencodeModelsLoading: false,
      opencodeModelProvider: '',
      opencodeModelSearch: '',
      webSpeechVoices: [],
    };
  },
  watch: {
    worker: {
      immediate: true,
      handler(w, oldW) {
        if (w) {
          if (!oldW) {
            this.$nextTick(() => {
              if (this.$refs.nameInput) this.$refs.nameInput.focus();
              else if (this.$refs.overlay) this.$refs.overlay.focus();
            });
          }
          let disposition = w.disposition || 'review';
          let randomName = '';
          if (disposition.startsWith('random:')) {
            randomName = disposition.substring('random:'.length);
            disposition = 'random:';
          }
          this.form = {
            type: w.type || 'ai',
            name: w.name || '',
            note: w.note || '',
            agent: w.agent || 'claude',
            model: w.model || 'claude-sonnet-4-6',
            activation: w.activation || (w.type === 'service' ? 'manual' : 'on_drop'),
            disposition,
            random_name: randomName,
            watch_column: w.watch_column || '',
            expertise_prompt: w.expertise_prompt || '',
            trust_mode: w.trust_mode || 'trusted',
            max_retries: w.max_retries ?? ((w.type === 'shell' || w.type === 'marker') ? 0 : 1),
            use_worktree: w.use_worktree || false,
            auto_commit: w.auto_commit || false,
            auto_pr: w.auto_pr || false,
            trigger_time: w.trigger_time || '',
            trigger_interval_minutes: w.trigger_interval_minutes || 60,
            trigger_every_day: w.trigger_every_day || false,
            paused: w.paused || false,
            color: w.color || '',
            // Shell-specific fields
            command: w.command || '',
            cwd: w.cwd || '',
            timeout_seconds: w.timeout_seconds ?? 60,
            ticket_delivery: w.ticket_delivery || 'stdin-json',
            env: Array.isArray(w.env) ? w.env.map(e => ({ key: e.key || '', value: e.value || '' })) : [],
            // Service-specific fields
            command_source: w.command_source || 'manual',
            procfile_process: w.procfile_process || 'web',
            port: w.port ?? '',
            pre_start: w.pre_start || '',
            ticket_action: w.ticket_action || 'start-if-stopped-else-restart',
            startup_grace_seconds: w.startup_grace_seconds ?? 2,
            startup_timeout_seconds: w.startup_timeout_seconds ?? 60,
            health_type: w.health_type || 'none',
            health_url: w.health_url || '',
            health_command: w.health_command || '',
            health_interval_seconds: w.health_interval_seconds ?? 5,
            health_timeout_seconds: w.health_timeout_seconds ?? 2,
            health_failure_threshold: w.health_failure_threshold ?? 3,
            on_crash: w.on_crash || 'stay-crashed',
            stop_timeout_seconds: w.stop_timeout_seconds ?? 5,
            log_max_bytes: w.log_max_bytes ?? 5242880,
            value: w.value ?? '',
            value_type: w.value_type || 'auto',
            resolved_value_type: w.resolved_value_type || 'string',
            format: w.format && typeof w.format === 'object' ? { ...w.format } : { kind: 'auto' },
            notification: cloneNotificationForm(w.notification),
          };
          this.servicePreview = null;
          this.servicePreviewError = '';
          this.serviceSuggestedPort = null;
          this.servicePortAutoFilled = false;
          this.syncOpenCodeModelProvider();
          if (this.isOpenCodeAgent) this.ensureOpenCodeModels();
          this.scheduleServicePreview();
        }
      }
    },
    form: {
      deep: true,
      handler() {
        this.scheduleServicePreview();
      },
    }
  },
  mounted() {
    this.loadWebSpeechVoices();
    try {
      window.speechSynthesis?.addEventListener?.('voiceschanged', this.loadWebSpeechVoices);
    } catch (_err) {}
  },
  beforeUnmount() {
    if (this.servicePreviewTimer) clearTimeout(this.servicePreviewTimer);
    this.teardownWorkerColorPicker();
    try {
      window.speechSynthesis?.removeEventListener?.('voiceschanged', this.loadWebSpeechVoices);
    } catch (_err) {}
  },
  computed: {
    isShell() {
      return this.form.type === 'shell';
    },
    isService() {
      return this.form.type === 'service';
    },
    isMarker() {
      return this.form.type === 'marker';
    },
    isNotification() {
      return this.form.type === 'notification';
    },
    isValue() {
      return this.form.type === 'value';
    },
    isProcfileService() {
      return this.isService && this.form.command_source === 'procfile';
    },
    isAI() {
      return this.form.type === 'ai' || this.form.type == null;
    },
    isOpenCodeAgent() {
      return this.isAI && this.form.agent === 'opencode';
    },
    canPauseWorker() {
      return this.isAI || this.isShell || this.isService || this.isNotification;
    },
    isUntrustedAI() {
      return this.isAI && this.form.trust_mode === 'untrusted';
    },
    otherWorkers() {
      if (!this.workers) return [];
      return this.workers
        .map((w, i) => w && i !== this.slotIndex ? { name: w.name, slot: i } : null)
        .filter(Boolean);
    },
    modelOptions() {
      return MODEL_OPTIONS[this.form.agent] || ['default'];
    },
    opencodeProviders() {
      const providers = this.opencodeModels
        .map(model => String(model.provider || '').trim())
        .filter(Boolean);
      const currentProvider = this.currentOpenCodeProvider;
      if (currentProvider) providers.unshift(currentProvider);
      return [...new Set(providers)].sort((a, b) => a.localeCompare(b));
    },
    currentOpenCodeProvider() {
      const model = String(this.form.model || '').trim();
      if (!model.includes('/')) return '';
      return model.split('/', 1)[0];
    },
    filteredOpenCodeModels() {
      const provider = String(this.opencodeModelProvider || '').trim();
      const query = String(this.opencodeModelSearch || '').trim().toLowerCase();
      return this.opencodeModels.filter(model => {
        if (provider && model.provider !== provider) return false;
        if (!query) return true;
        const id = String(model.id || '').toLowerCase();
        const label = String(model.model || '').toLowerCase();
        return id.includes(query) || label.includes(query);
      });
    },
    isOpenCodeModelInCatalog() {
      const current = String(this.form.model || '').trim();
      return !!current && this.opencodeModels.some(model => model.id === current);
    },
    opencodeCatalogHint() {
      if (this.opencodeModelsLoading) return 'Loading OpenCode models...';
      if (this.opencodeModelsError) return this.opencodeModelsError;
      if (!this.opencodeModels.length && this.opencodeModelsStatus === 'ok') return 'No OpenCode models returned. Enter a custom provider/model value.';
      if (this.opencodeModelsStatus === 'unavailable') return 'OpenCode CLI is not available. Install OpenCode or set BULLPEN_OPENCODE_PATH, then enter a custom provider/model value if needed.';
      return '';
    },
    passAvailability() {
      const rows = this.gridRows || 4;
      const cols = this.gridCols || 6;
      const idx = this.slotIndex;
      const slots = this.workers || [];
      if (idx == null || idx < 0) return { up: false, down: false, left: false, right: false };
      const r = Math.floor(idx / cols);
      const c = idx % cols;
      const occupied = (targetIdx) => targetIdx >= 0 && targetIdx < slots.length && !!slots[targetIdx];
      const up = r > 0 && occupied((r - 1) * cols + c);
      const down = r < rows - 1 && occupied((r + 1) * cols + c);
      const left = c > 0 && occupied(r * cols + (c - 1));
      const right = c < cols - 1 && occupied(r * cols + (c + 1));
      return { up, down, left, right, any: up || down || left || right };
    },
    showCustomModel() {
      return !this.isOpenCodeAgent && !this.modelOptions.includes(this.form.model);
    },
    modelSelectValue() {
      return this.modelOptions.includes(this.form.model) ? this.form.model : '__custom__';
    },
    procfileProcessOptions() {
      const names = Array.isArray(this.servicePreview?.process_names)
        ? [...this.servicePreview.process_names]
        : [];
      const current = String(this.form.procfile_process || '').trim();
      if (current && !names.includes(current)) names.unshift(current);
      return names;
    },
    selectedWorkerColorOverride() {
      return typeof this.form.color === 'string' ? this.form.color.trim() : '';
    },
    workerColorDefaultLabel() {
      const key = workerColorKey(this.worker) || 'worker';
      return key === 'marker' ? 'marker' : key;
    },
    workerColorDefaultValue() {
      const key = workerColorKey(this.worker) || 'worker';
      return (this.providerColors && this.providerColors[key])
        || (this.defaultProviderColors && this.defaultProviderColors[key])
        || '#6B7280';
    },
    workerColorPreviewValue() {
      return this.resolveWorkerColorValue(this.selectedWorkerColorOverride) || this.workerColorDefaultValue;
    },
    workerColorPickerValue() {
      return this.normalizeHexColor(this.selectedWorkerColorOverride) || this.workerColorPreviewValue;
    },
    notificationSpeechEngine() {
      return String(this.form.notification?.speech?.engine || 'kokoro');
    },
    notificationVoiceOptions() {
      const engine = this.notificationSpeechEngine;
      if (engine === 'kokoro') return KOKORO_VOICE_OPTIONS;
      const options = [{ value: '', label: 'Browser default voice' }];
      for (const voice of this.webSpeechVoices || []) {
        const value = voice.voiceURI || voice.name;
        if (!value) continue;
        options.push({
          value,
          label: `${voice.name || value}${voice.lang ? ` (${voice.lang})` : ''}${voice.default ? ' - default' : ''}`,
        });
      }
      const current = String(this.form.notification?.speech?.voice || '');
      if (current && !options.some(option => option.value === current)) {
        options.push({ value: current, label: `${current} (saved voice)` });
      }
      return options;
    },
    notificationSpeechHint() {
      const engine = this.notificationSpeechEngine;
      if (engine === 'kokoro') return 'Kokoro runs locally and loads its model on first speech use.';
      if (engine === 'web-speech') return 'Web Speech voices come from the browser or operating system.';
      return 'Automatic uses Kokoro first, then browser speech if Kokoro cannot load.';
    },
  },
  template: `
    <div v-if="worker" class="modal-overlay" @mousedown.self="overlayMouseDown = true" @click.self="onOverlayClick" @keydown.escape="$emit('close')" @keydown.meta.enter="onPrimaryShortcut" tabindex="0" ref="overlay">
      <div class="modal modal-wide" @mouseup="overlayMouseDown = false">
        <div class="modal-header">
          <h2>
            Configure: {{ form.name }}
            <span v-if="isShell" class="worker-type-badge">Shell</span>
            <span v-if="isService" class="worker-type-badge">Service</span>
            <span v-if="isMarker" class="worker-type-badge">Marker</span>
            <span v-if="isNotification" class="worker-type-badge">Notification</span>
            <span v-if="isValue" class="worker-type-badge">Value</span>
          </h2>
          <button class="btn btn-icon" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <label class="form-label">
            Name
            <input class="form-input" v-model="form.name" ref="nameInput">
          </label>

          <template v-if="isMarker">
            <label class="form-label">
              Note
              <textarea class="form-textarea" v-model="form.note" rows="3" maxlength="500"
                        placeholder="Optional label note or routing hint"></textarea>
            </label>
          </template>

          <template v-if="isValue">
            <div class="form-row">
              <label class="form-label">
                Value
                <input class="form-input" v-model="form.value">
              </label>
              <label class="form-label">
                Type
                <select class="form-select" v-model="form.value_type">
                  <option value="auto">Auto</option>
                  <option value="number">Number</option>
                  <option value="string">String</option>
                </select>
              </label>
            </div>
            <div class="form-row">
              <label class="form-label">
                Format
                <select class="form-select" v-model="form.format.kind">
                  <option value="auto">Auto</option>
                  <option value="general">General</option>
                  <option value="number">Number</option>
                  <option value="currency">Currency</option>
                  <option value="string-left">Text left</option>
                  <option value="string-right">Text right</option>
                </select>
              </label>
              <label class="form-label" v-if="form.format.kind === 'number' || form.format.kind === 'currency'">
                Decimal Places
                <input class="form-input" type="number" v-model.number="form.format.places" min="0" max="10">
              </label>
              <label class="form-label" v-if="form.format.kind === 'currency'">
                Symbol
                <input class="form-input" v-model="form.format.symbol" maxlength="8">
              </label>
            </div>
          </template>

          <!-- AI-only: expertise prompt, agent, model -->
          <template v-if="isAI">
            <label class="form-label">
              Expertise Prompt
              <textarea class="form-textarea" v-model="form.expertise_prompt" rows="5"></textarea>
            </label>
            <label class="form-label">
              Trust Mode
              <select class="form-select" v-model="form.trust_mode" @change="onTrustModeChange">
                <option value="untrusted">Untrusted (safer defaults)</option>
                <option value="trusted">Trusted</option>
              </select>
              <span class="form-hint">
                Untrusted mode treats ticket, chat, and repo content as lower-priority data and disables auto-commit / auto-PR.
              </span>
            </label>
            <div class="form-row">
              <label class="form-label">
                AI Provider
                <select class="form-select" v-model="form.agent" @change="onAgentChange">
                  <option value="claude">Claude</option>
                  <option value="codex">Codex</option>
                  <option value="gemini">Gemini</option>
                  <option value="opencode">OpenCode</option>
                </select>
              </label>
              <label v-if="!isOpenCodeAgent" class="form-label">
                Model
                <select class="form-select" :value="modelSelectValue" @change="onModelSelect">
                  <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
                  <option value="__custom__">Custom...</option>
                </select>
                <input v-if="showCustomModel" class="form-input" v-model="form.model" placeholder="Enter model slug" style="margin-top: 4px;">
              </label>
            </div>
            <template v-if="isOpenCodeAgent">
              <div class="form-row">
                <label class="form-label">
                  Model Provider
                  <select class="form-select" v-model="opencodeModelProvider" @change="onOpenCodeProviderChange">
                    <option value="">All providers</option>
                    <option v-for="provider in opencodeProviders" :key="provider" :value="provider">{{ provider }}</option>
                  </select>
                </label>
                <label class="form-label">
                  Search Models
                  <input class="form-input" v-model="opencodeModelSearch" placeholder="Search OpenCode models">
                </label>
                <label class="form-label">
                  Catalog
                  <button type="button" class="btn btn-sm" @click="refreshOpenCodeModels" :disabled="opencodeModelsLoading">
                    {{ opencodeModelsLoading ? 'Refreshing...' : 'Refresh' }}
                  </button>
                </label>
              </div>
              <label class="form-label">
                Model
                <select class="form-select" :value="form.model" @change="onOpenCodeModelSelect">
                  <option value="">Select a model...</option>
                  <option v-if="form.model && !isOpenCodeModelInCatalog" :value="form.model">{{ form.model }}</option>
                  <option v-for="model in filteredOpenCodeModels" :key="model.id" :value="model.id">{{ model.id }}</option>
                </select>
                <span v-if="opencodeCatalogHint" class="form-hint">{{ opencodeCatalogHint }}</span>
              </label>
              <label class="form-label">
                Custom Model
                <input class="form-input" v-model="form.model" placeholder="provider/model">
                <span class="form-hint">OpenCode model IDs are passed through as <code>provider/model</code>.</span>
              </label>
            </template>
          </template>

          <!-- Shell-only: command, delivery, cwd, timeout, env -->
          <template v-if="isShell">
            <label class="form-label">
              Command
              <textarea class="form-textarea form-textarea--mono" v-model="form.command" rows="3"
                        placeholder="python3 scripts/check_ticket.py"></textarea>
              <span class="form-hint">Executed with <code>/bin/sh -c</code> (POSIX) or <code>cmd.exe /c</code> (Windows). Ticket fields are never interpolated; Value placeholders are raw text.</span>
            </label>
            <div class="shell-warning">
              <strong>Stored in plaintext:</strong> command and env values live in
              <code>layout.json</code>. Stdout/stderr are saved under
              <code>.bullpen/logs/worker-runs/</code> and appear in ticket
              history. Do not put real secrets here; reference variables already
              in the server environment instead.
            </div>
            <div class="form-row">
              <label class="form-label">
                Pass ticket as
                <select class="form-select" v-model="form.ticket_delivery">
                  <option value="stdin-json">stdin-json (JSON on stdin)</option>
                  <option value="env-vars">env-vars (BULLPEN_TICKET_*)</option>
                  <option value="argv-json">argv-json (single positional arg)</option>
                </select>
              </label>
              <label class="form-label">
                Timeout (seconds)
                <input class="form-input" type="number" v-model.number="form.timeout_seconds" min="1" max="600">
              </label>
            </div>
            <label class="form-label">
              Working directory
              <input class="form-input" v-model="form.cwd" placeholder="(workspace root)">
              <span class="form-hint">Relative to workspace root. Must stay inside the workspace.</span>
            </label>
            <div class="form-label">
              <span>Environment</span>
              <div class="shell-env-list">
                <div v-for="(item, i) in form.env" :key="i" class="shell-env-row">
                  <input class="form-input" v-model="item.key" placeholder="KEY" />
                  <input class="form-input" v-model="item.value" placeholder="value" />
                  <button class="btn btn-sm btn-danger" @click="removeEnv(i)" title="Remove">&times;</button>
                </div>
                <button class="btn btn-sm" @click="addEnv">Add env var</button>
              </div>
              <span class="form-hint">
                Variables whose names contain TOKEN, KEY, SECRET, PASSWORD,
                CREDENTIAL, or PASSPHRASE are filtered from the inherited env
                by default. Re-add them here explicitly if non-sensitive.
                <code>BULLPEN_MCP_TOKEN</code> is always rejected.
              </span>
            </div>
          </template>

          <!-- Service-only: command, lifecycle, health, env -->
          <template v-if="isService">
            <div class="form-row">
              <label class="form-label">
                Command Source
                <select class="form-select" v-model="form.command_source">
                  <option value="manual">Inline command</option>
                  <option value="procfile">Procfile</option>
                </select>
              </label>
              <label class="form-label">
                Port
                <input class="form-input" type="number" v-model="form.port" min="1" max="65535" :placeholder="serviceSuggestedPort ? String(serviceSuggestedPort) : '3000'">
                <span class="form-hint">
                  <span v-if="serviceSuggestedPort">Suggested open port: <code>{{ serviceSuggestedPort }}</code>. </span>
                  Seeds <code>PORT</code> in the Service worker env.
                </span>
              </label>
            </div>
            <label v-if="!isProcfileService" class="form-label">
              Command
              <textarea class="form-textarea form-textarea--mono" v-model="form.command" rows="3"
                        placeholder="python3 hosted-app.py --port=$HOSTED_PORT"></textarea>
              <span class="form-hint">Executed with <code>/bin/sh -c</code> (POSIX) or <code>cmd.exe /c</code> (Windows). Ticket fields are exposed through <code>BULLPEN_*</code> variables.</span>
            </label>
            <div v-else class="form-row">
              <label class="form-label">
                Procfile process
                <select v-if="procfileProcessOptions.length" class="form-select" v-model="form.procfile_process">
                  <option v-for="name in procfileProcessOptions" :key="name" :value="name">{{ name }}</option>
                </select>
                <input v-else class="form-input" v-model="form.procfile_process" placeholder="web">
              </label>
              <label class="form-label">
                Procfile path
                <input class="form-input" :value="servicePreview?.procfile_path || 'Procfile will be read from <cwd>/Procfile'" readonly>
              </label>
            </div>
            <div class="form-row">
              <label class="form-label">
                Input Trigger
                <select class="form-select" v-model="form.activation">
                  <option value="on_drop">Auto on Assignment</option>
                  <option value="on_queue">On Queue (Watch Column)</option>
                  <option value="manual">Hold for Run</option>
                  <option value="at_time">At Time</option>
                  <option value="on_interval">On Interval</option>
                </select>
              </label>
              <label class="form-label" v-if="form.activation === 'on_queue'">
                Watch Column
                <select class="form-select" v-model="form.watch_column">
                  <option value="">None</option>
                  <option v-for="col in columns" :key="col.key" :value="col.key">{{ col.label }}</option>
                </select>
              </label>
              <label class="form-label" v-if="form.activation === 'at_time'">
                Trigger Time (HH:MM, local)
                <input class="form-input" v-model="form.trigger_time" placeholder="09:00" pattern="\\d{2}:\\d{2}">
              </label>
              <label class="form-label form-label-inline" v-if="form.activation === 'at_time'">
                <input type="checkbox" v-model="form.trigger_every_day">
                Repeat every day
              </label>
              <label class="form-label" v-if="form.activation === 'on_interval'">
                Interval (minutes)
                <input class="form-input" type="number" v-model.number="form.trigger_interval_minutes" min="1" max="1440">
              </label>
              <label class="form-label form-label-inline" v-if="canPauseWorker">
                <input type="checkbox" v-model="form.paused">
                Paused
              </label>
            </div>
            <div class="form-row">
              <label class="form-label">
                Output
                <select class="form-select" v-model="form.disposition">
                  <optgroup label="Columns">
                    <option v-for="col in columns" :key="col.key" :value="col.key">{{ col.label }}</option>
                  </optgroup>
                  <optgroup label="Workers" v-if="otherWorkers.length">
                    <option v-for="w in otherWorkers" :key="'worker:' + w.name" :value="'worker:' + w.name">\u2192 {{ w.name }}</option>
                  </optgroup>
                  <optgroup label="Pass">
                    <option value="pass:up" :disabled="!passAvailability.up">\u2191 Up</option>
                    <option value="pass:down" :disabled="!passAvailability.down">\u2193 Down</option>
                    <option value="pass:left" :disabled="!passAvailability.left">\u2190 Left</option>
                    <option value="pass:right" :disabled="!passAvailability.right">\u2192 Right</option>
                    <option value="pass:random" :disabled="!passAvailability.any">? Random Direction</option>
                  </optgroup>
                  <optgroup label="Random">
                    <option value="random:">? Random Worker</option>
                  </optgroup>
                </select>
                <input v-if="form.disposition === 'random:'" class="form-input" v-model="form.random_name" placeholder="Worker name (blank matches all)" style="margin-top: 4px;">
              </label>
              <label class="form-label">
                Max Retries
                <select class="form-select" v-model.number="form.max_retries">
                  <option :value="0">0</option>
                  <option :value="1">1</option>
                  <option :value="2">2</option>
                  <option :value="3">3</option>
                </select>
              </label>
            </div>
            <label class="form-label">
              Pre-start
              <textarea class="form-textarea form-textarea--mono" v-model="form.pre_start" rows="2"
                        placeholder="git fetch && git checkout &quot;$BULLPEN_SERVICE_COMMIT&quot;"></textarea>
              <span class="form-hint">Optional. Runs before the main service command and must finish successfully.</span>
            </label>
            <div class="form-label">
              <span>Resolved command preview</span>
              <div class="shell-warning" v-if="servicePreviewError">{{ servicePreviewError }}</div>
              <div class="shell-warning" v-else-if="servicePreviewLoading">Resolving command…</div>
              <div class="shell-warning" v-else-if="servicePreview">
                <div><strong>Raw:</strong> <code>{{ servicePreview.raw_command || '(none)' }}</code></div>
                <div><strong>Resolved:</strong> <code>{{ servicePreview.resolved_command || '(none)' }}</code></div>
                <div v-if="servicePreview.warnings?.length" style="margin-top: 6px;">
                  <div v-for="warning in servicePreview.warnings" :key="warning">{{ warning }}</div>
                </div>
              </div>
            </div>
            <div class="shell-warning">
              <strong>Stored in plaintext:</strong> command, pre-start, env values, and logs live under
              <code>.bullpen/</code>. Do not put real secrets here.
            </div>
            <div class="form-row">
              <label class="form-label">
                Ticket action
                <select class="form-select" v-model="form.ticket_action">
                  <option value="start-if-stopped-else-restart">Start if stopped, otherwise restart</option>
                  <option value="restart">Always restart</option>
                  <option value="start-if-stopped">Start only if stopped</option>
                </select>
              </label>
              <label class="form-label">
                Working directory
                <input class="form-input" v-model="form.cwd" placeholder="(workspace root)">
              </label>
            </div>
            <div class="form-row">
              <label class="form-label">
                Startup grace seconds
                <input class="form-input" type="number" v-model.number="form.startup_grace_seconds" min="0" max="3600">
              </label>
              <label class="form-label">
                Startup timeout seconds
                <input class="form-input" type="number" v-model.number="form.startup_timeout_seconds" min="1" max="86400">
              </label>
              <label class="form-label">
                Stop timeout seconds
                <input class="form-input" type="number" v-model.number="form.stop_timeout_seconds" min="0" max="3600">
              </label>
            </div>
            <div class="form-row">
              <label class="form-label">
                Health check
                <select class="form-select" v-model="form.health_type">
                  <option value="none">None</option>
                  <option value="http">HTTP</option>
                  <option value="shell">Shell command</option>
                </select>
              </label>
              <label class="form-label" v-if="form.health_type === 'http'">
                Health URL
                <input class="form-input" v-model="form.health_url" placeholder="http://localhost:3000/health">
              </label>
              <label class="form-label" v-if="form.health_type === 'shell'">
                Health command
                <input class="form-input" v-model="form.health_command" placeholder="curl -fsS http://localhost:3000/health">
              </label>
            </div>
            <div class="form-row" v-if="form.health_type !== 'none'">
              <label class="form-label">
                Check interval seconds
                <input class="form-input" type="number" v-model.number="form.health_interval_seconds" min="1" max="3600">
              </label>
              <label class="form-label">
                Check timeout seconds
                <input class="form-input" type="number" v-model.number="form.health_timeout_seconds" min="1" max="3600">
              </label>
              <label class="form-label">
                Failure threshold
                <input class="form-input" type="number" v-model.number="form.health_failure_threshold" min="1" max="100">
              </label>
            </div>
            <div class="form-row">
              <label class="form-label">
                On crash
                <select class="form-select" v-model="form.on_crash">
                  <option value="stay-crashed">Stay crashed</option>
                </select>
              </label>
              <label class="form-label">
                Log max bytes
                <input class="form-input" type="number" v-model.number="form.log_max_bytes" min="1024" max="1073741824">
              </label>
            </div>
            <div class="form-label">
              <span>Environment</span>
              <div class="shell-env-list">
                <div v-for="(item, i) in form.env" :key="i" class="shell-env-row">
                  <input class="form-input" v-model="item.key" placeholder="KEY" />
                  <input class="form-input" v-model="item.value" placeholder="value" />
                  <button class="btn btn-sm btn-danger" @click="removeEnv(i)" title="Remove">&times;</button>
                </div>
                <button class="btn btn-sm" @click="addEnv">Add env var</button>
              </div>
              <span class="form-hint">
                <code>BULLPEN_*</code> names are reserved for injected Service variables and cannot be configured.
              </span>
            </div>
          </template>

          <!-- Notification-only: toast, speech, sound, flash, policy -->
          <template v-if="isNotification">
            <div class="notification-config-block">
              <div class="notification-channel">
                <label class="form-label form-label-inline notification-channel-title">
                  <input type="checkbox" v-model="form.notification.toast.enabled">
                  Toast
                </label>
                <label class="form-label">
                  Message template
                  <textarea class="form-textarea" v-model="form.notification.toast.template" rows="3" maxlength="2000"
                            placeholder="{ticket.title} reached {worker.name}."></textarea>
                  <span class="form-hint">Variables: <code>{ticket.title}</code>, <code>{worker.name}</code>, <code>{workspace.name}</code></span>
                </label>
                <div class="form-row">
                  <label class="form-label">
                    Variant
                    <select class="form-select" v-model="form.notification.toast.variant">
                      <option value="stage">Stage</option>
                      <option value="success">Success</option>
                      <option value="warning">Warning</option>
                      <option value="error">Error</option>
                    </select>
                  </label>
                  <label class="form-label">
                    Duration (ms)
                    <input class="form-input" type="number" v-model.number="form.notification.toast.duration_ms" min="1000" max="30000">
                  </label>
                </div>
              </div>

              <div class="notification-channel">
                <label class="form-label form-label-inline notification-channel-title">
                  <input type="checkbox" v-model="form.notification.speech.enabled">
                  Speech
                </label>
                <label class="form-label">
                  Speech template
                  <textarea class="form-textarea" v-model="form.notification.speech.template" rows="3" maxlength="2000"
                            placeholder="{ticket.title} is ready."></textarea>
                </label>
                <div class="form-row">
                  <label class="form-label">
                    Engine
                    <select class="form-select" v-model="form.notification.speech.engine" @change="onNotificationSpeechEngineChange">
                      <option value="kokoro">Kokoro</option>
                      <option value="web-speech">Web Speech</option>
                      <option value="default">Automatic fallback</option>
                    </select>
                  </label>
                  <label class="form-label">
                    Voice
                    <select class="form-select" v-model="form.notification.speech.voice" @focus="loadWebSpeechVoices">
                      <option v-for="voice in notificationVoiceOptions" :key="voice.value" :value="voice.value">{{ voice.label }}</option>
                    </select>
                  </label>
                  <label class="form-label">
                    Rate
                    <input class="form-input" type="number" step="0.1" v-model.number="form.notification.speech.rate" min="0.5" max="2">
                  </label>
                  <label class="form-label">
                    Volume
                    <input class="form-input" type="number" step="0.1" v-model.number="form.notification.speech.volume" min="0" max="1">
                  </label>
                </div>
                <span class="form-hint">{{ notificationSpeechHint }}</span>
              </div>

              <div class="notification-channel">
                <label class="form-label form-label-inline notification-channel-title">
                  <input type="checkbox" v-model="form.notification.sound.enabled">
                  Sound
                </label>
                <div class="form-row">
                  <label class="form-label">
                    Effect
                    <select class="form-select" v-model="form.notification.sound.effect">
                      <option value="toast">Toast chime</option>
                      <option value="start">Start</option>
                      <option value="done">Done chime</option>
                      <option value="move">Move tick</option>
                      <option value="warning">Warning</option>
                      <option value="error">Error</option>
                      <option value="spawn">Spawn</option>
                      <option value="despawn">Despawn</option>
                    </select>
                  </label>
                  <label class="form-label">
                    Repeat
                    <input class="form-input" type="number" v-model.number="form.notification.sound.repeat_count" min="1" max="5">
                  </label>
                  <label class="form-label">
                    Gap (ms)
                    <input class="form-input" type="number" v-model.number="form.notification.sound.gap_ms" min="100" max="2000">
                  </label>
                  <label class="form-label">
                    Volume
                    <input class="form-input" type="number" step="0.1" v-model.number="form.notification.sound.volume" min="0" max="1">
                  </label>
                </div>
              </div>

              <div class="notification-channel">
                <label class="form-label form-label-inline notification-channel-title">
                  <input type="checkbox" v-model="form.notification.flash.enabled">
                  Screen flash
                </label>
                <div class="shell-warning">
                  Flash respects reduced-motion settings and is capped by the client runtime.
                </div>
                <div class="shell-env-list">
                  <div v-for="(step, i) in form.notification.flash.sequence" :key="i" class="shell-env-row">
                    <input class="form-input" v-model="step.color" placeholder="#facc15">
                    <input class="form-input" type="number" v-model.number="step.duration_ms" min="50" max="1000" placeholder="180">
                    <button class="btn btn-sm btn-danger" @click="removeFlashStep(i)" title="Remove">&times;</button>
                  </div>
                  <button class="btn btn-sm" @click="addFlashStep" :disabled="form.notification.flash.sequence.length >= 6">Add flash step</button>
                </div>
                <label class="form-label">
                  Opacity
                  <input class="form-input" type="number" step="0.05" v-model.number="form.notification.flash.opacity" min="0" max="0.5">
                </label>
              </div>

              <div class="notification-channel">
                <div class="notification-channel-title">Notification policy</div>
                <div class="form-row">
                  <label class="form-label">
                    Cooldown (ms)
                    <input class="form-input" type="number" v-model.number="form.notification.policy.cooldown_ms" min="0" max="60000">
                  </label>
                  <label class="form-label">
                    Dedupe window (ms)
                    <input class="form-input" type="number" v-model.number="form.notification.policy.dedupe_window_ms" min="0" max="300000">
                  </label>
                </div>
              </div>
            </div>
          </template>

          <!-- Shared: activation, disposition, max retries -->
          <div v-if="!isService && !isValue" class="form-row">
            <label class="form-label">
              Input Trigger
              <select class="form-select" v-model="form.activation">
                <option value="on_drop">Auto on Assignment</option>
                <option value="on_queue">On Queue (Watch Column)</option>
                <option value="manual">Hold for Run</option>
                <option value="at_time">At Time</option>
                <option value="on_interval">On Interval</option>
              </select>
            </label>
            <label class="form-label" v-if="form.activation === 'on_queue'">
              Watch Column
              <select class="form-select" v-model="form.watch_column">
                <option value="">None</option>
                <option v-for="col in columns" :key="col.key" :value="col.key">{{ col.label }}</option>
              </select>
            </label>
            <label class="form-label" v-if="form.activation === 'at_time'">
              Trigger Time (HH:MM, local)
              <input class="form-input" v-model="form.trigger_time" placeholder="09:00" pattern="\\d{2}:\\d{2}">
            </label>
            <label class="form-label form-label-inline" v-if="form.activation === 'at_time'">
              <input type="checkbox" v-model="form.trigger_every_day">
              Repeat every day
            </label>
            <label class="form-label" v-if="form.activation === 'on_interval'">
              Interval (minutes)
              <input class="form-input" type="number" v-model.number="form.trigger_interval_minutes" min="1" max="1440">
            </label>
            <label class="form-label form-label-inline" v-if="canPauseWorker">
              <input type="checkbox" v-model="form.paused">
              Paused
            </label>
          </div>
          <div v-if="!isService && !isValue" class="form-row">
            <label class="form-label">
              {{ (isMarker || isNotification) ? 'Pass tickets to' : 'Output' }}
              <select class="form-select" v-model="form.disposition">
                <optgroup label="Columns">
                  <option v-for="col in columns" :key="col.key" :value="col.key">{{ col.label }}</option>
                </optgroup>
                <optgroup label="Workers" v-if="otherWorkers.length">
                  <option v-for="w in otherWorkers" :key="'worker:' + w.name" :value="'worker:' + w.name">\u2192 {{ w.name }}</option>
                </optgroup>
                <optgroup label="Pass">
                  <option value="pass:up" :disabled="!passAvailability.up">\u2191 Up</option>
                  <option value="pass:down" :disabled="!passAvailability.down">\u2193 Down</option>
                  <option value="pass:left" :disabled="!passAvailability.left">\u2190 Left</option>
                  <option value="pass:right" :disabled="!passAvailability.right">\u2192 Right</option>
                  <option value="pass:random" :disabled="!passAvailability.any">? Random Direction</option>
                </optgroup>
                <optgroup label="Random">
                  <option value="random:">? Random Worker</option>
                </optgroup>
              </select>
              <input v-if="form.disposition === 'random:'" class="form-input" v-model="form.random_name" placeholder="Worker name (blank matches all)" style="margin-top: 4px;">
            </label>
            <label v-if="!isMarker && !isNotification" class="form-label">
              Max Retries
              <select class="form-select" v-model.number="form.max_retries">
                <option :value="0">0</option>
                <option :value="1">1</option>
                <option :value="2">2</option>
                <option :value="3">3</option>
              </select>
            </label>
          </div>

          <!-- AI-only: worktree / commit / PR -->
          <div v-if="isAI" class="form-row">
            <label class="form-label form-label-inline">
              <input type="checkbox" v-model="form.use_worktree">
              Use Git Worktree
              <span class="form-hint">(isolate agent work in a separate branch)</span>
            </label>
            <label class="form-label form-label-inline">
              <input type="checkbox" v-model="form.auto_commit" :disabled="isUntrustedAI">
              Auto-Commit
              <span class="form-hint">(commit agent changes on success)</span>
            </label>
            <label class="form-label form-label-inline">
              <input type="checkbox" v-model="form.auto_pr" :disabled="isUntrustedAI || !form.use_worktree || !form.auto_commit">
              Auto-PR
              <span class="form-hint">(open PR after commit; requires worktree + auto-commit)</span>
            </label>
          </div>

          <div class="form-label">
            <span>Card Color</span>
            <div class="worker-color-override-controls">
              <button
                type="button"
                class="worker-color-override-trigger"
                ref="workerColorTrigger"
                @click="openWorkerColorPicker"
                :aria-label="selectedWorkerColorOverride ? 'Choose a different card color override' : 'Choose a card color override'"
              >
                <i data-lucide="palette" aria-hidden="true"></i>
                <span class="worker-color-override-swatch" :style="{ background: workerColorPreviewValue }" aria-hidden="true"></span>
              </button>
              <button type="button" class="btn btn-sm" @click="onRestoreDefaultColor" :disabled="!selectedWorkerColorOverride">Restore Default</button>
            </div>
            <span class="form-hint">
              Default uses the workspace <code>{{ workerColorDefaultLabel }}</code> color. Use the palette button to pick any per-card override.
            </span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-danger btn-sm" @click="onRemove">Remove Worker</button>
          <div class="modal-footer-right">
            <button v-if="isAI" class="btn btn-sm" @click="onSaveProfile">Save as Profile</button>
            <button class="btn" @click="$emit('close')">Cancel</button>
            <button class="btn btn-primary" @click="onSave">Save</button>
          </div>
        </div>
      </div>
    </div>
  `,
  methods: {
    normalizeHexColor(value) {
      const text = String(value || '').trim();
      if (!text) return '';
      const shortMatch = text.match(/^#([0-9a-fA-F]{3})$/);
      if (shortMatch) {
        return `#${shortMatch[1].split('').map(ch => ch + ch).join('').toLowerCase()}`;
      }
      const longMatch = text.match(/^#([0-9a-fA-F]{6})$/);
      return longMatch ? `#${longMatch[1].toLowerCase()}` : '';
    },
    resolveWorkerColorValue(value) {
      const normalized = this.normalizeHexColor(value);
      if (normalized) return normalized;
      const key = String(value || '').trim();
      if (!key) return '';
      return (this.providerColors && this.providerColors[key])
        || (this.defaultProviderColors && this.defaultProviderColors[key])
        || '';
    },
    getWorkerColorPickerAnchor() {
      const trigger = this.$refs.workerColorTrigger;
      if (!trigger || typeof trigger.getBoundingClientRect !== 'function') return null;
      const rect = trigger.getBoundingClientRect();
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
      const width = Math.max(24, Math.round(rect.width || 0));
      const height = Math.max(24, Math.round(rect.height || 0));
      const maxLeft = Math.max(0, viewportWidth - width);
      const maxTop = Math.max(0, viewportHeight - height);
      return {
        top: Math.min(Math.max(0, Math.round(rect.top)), maxTop),
        left: Math.min(Math.max(0, Math.round(rect.left)), maxLeft),
        width,
        height,
      };
    },
    buildWorkerColorPickerInput(anchor) {
      const input = document.createElement('input');
      input.type = 'color';
      input.value = this.workerColorPickerValue;
      input.className = 'worker-color-override-input';
      input.tabIndex = -1;
      input.setAttribute('aria-hidden', 'true');
      Object.assign(input.style, {
        position: 'fixed',
        top: `${anchor.top}px`,
        left: `${anchor.left}px`,
        width: `${anchor.width}px`,
        height: `${anchor.height}px`,
        margin: '0',
        padding: '0',
        border: '0',
        opacity: '0',
        pointerEvents: 'none',
        zIndex: '2147483647',
      });
      return input;
    },
    teardownWorkerColorPicker() {
      const input = this.workerColorPickerInput;
      if (input && input.parentNode) input.parentNode.removeChild(input);
      this.workerColorPickerInput = null;
    },
    openWorkerColorPicker() {
      const anchor = this.getWorkerColorPickerAnchor();
      if (!anchor) return;
      this.teardownWorkerColorPicker();
      const input = this.buildWorkerColorPickerInput(anchor);
      const cleanup = () => {
        input.removeEventListener('change', handleChange);
        input.removeEventListener('input', handleInput);
        input.removeEventListener('blur', cleanup);
        window.removeEventListener('focus', cleanup);
        this.teardownWorkerColorPicker();
      };
      const handleInput = (e) => this.onWorkerColorInput(e);
      const handleChange = (e) => {
        this.onWorkerColorInput(e);
        cleanup();
      };
      input.addEventListener('input', handleInput);
      input.addEventListener('change', handleChange);
      input.addEventListener('blur', cleanup);
      window.addEventListener('focus', cleanup, { once: true });
      document.body.appendChild(input);
      this.workerColorPickerInput = input;
      requestAnimationFrame(() => {
        if (this.workerColorPickerInput !== input) return;
        input.focus({ preventScroll: true });
        if (typeof input.showPicker === 'function') {
          input.showPicker();
          return;
        }
        input.click();
      });
    },
    onWorkerColorInput(e) {
      this.form.color = this.normalizeHexColor(e?.target?.value) || '';
    },
    onPrimaryShortcut(e) {
      e.preventDefault();
      this.onSave();
    },
    onAgentChange() {
      if (this.form.agent === 'opencode') {
        if (!String(this.form.model || '').includes('/')) this.form.model = '';
        this.syncOpenCodeModelProvider();
        this.ensureOpenCodeModels();
        return;
      }
      this.form.model = this.modelOptions[0];
    },
    onTrustModeChange() {
      if (this.form.trust_mode !== 'trusted') {
        this.form.auto_commit = false;
        this.form.auto_pr = false;
      }
    },
    onModelSelect(e) {
      if (e.target.value === '__custom__') {
        this.form.model = '';
      } else {
        this.form.model = e.target.value;
      }
    },
    syncOpenCodeModelProvider() {
      const currentProvider = this.currentOpenCodeProvider;
      if (currentProvider) {
        this.opencodeModelProvider = currentProvider;
      } else if (!this.opencodeModelProvider && this.opencodeProviders.length === 1) {
        this.opencodeModelProvider = this.opencodeProviders[0];
      }
    },
    ensureOpenCodeModels() {
      if (this.opencodeModels.length || this.opencodeModelsLoading) return;
      this.loadOpenCodeModels();
    },
    async loadOpenCodeModels({ refresh = false } = {}) {
      this.opencodeModelsLoading = true;
      this.opencodeModelsError = '';
      try {
        const params = new URLSearchParams();
        const workspaceId = this.activeWorkspaceId || this.$root?.activeWorkspaceId || '';
        if (workspaceId) params.set('workspaceId', workspaceId);
        if (refresh) params.set('refresh', '1');
        const query = params.toString();
        const resp = await fetch(`/api/models/opencode${query ? `?${query}` : ''}`, {
          credentials: 'same-origin',
        });
        const data = await resp.json();
        this.opencodeModelsStatus = data.status || (resp.ok ? 'ok' : 'error');
        this.opencodeModels = Array.isArray(data.models) ? data.models : [];
        if (!resp.ok || this.opencodeModelsStatus === 'error') {
          this.opencodeModelsError = data.error || 'OpenCode model catalog is unavailable. Enter a custom provider/model value.';
        } else {
          this.opencodeModelsError = '';
        }
        this.syncOpenCodeModelProvider();
      } catch (err) {
        this.opencodeModelsStatus = 'error';
        this.opencodeModels = [];
        this.opencodeModelsError = err.message || 'OpenCode model catalog is unavailable. Enter a custom provider/model value.';
      } finally {
        this.opencodeModelsLoading = false;
      }
    },
    refreshOpenCodeModels() {
      return this.loadOpenCodeModels({ refresh: true });
    },
    onOpenCodeProviderChange() {
      this.opencodeModelSearch = '';
    },
    onOpenCodeModelSelect(e) {
      this.form.model = e.target.value || '';
      this.syncOpenCodeModelProvider();
    },
    onOverlayClick() {
      if (this.overlayMouseDown) this.$emit('close');
      this.overlayMouseDown = false;
    },
    scheduleServicePreview() {
      if (!this.isService || this.slotIndex == null) return;
      if (this.servicePreviewTimer) clearTimeout(this.servicePreviewTimer);
      this.servicePreviewTimer = setTimeout(() => this.fetchServicePreview(), 120);
    },
    async fetchServicePreview() {
      if (!this.isService || this.slotIndex == null) return;
      const seq = ++this.servicePreviewSeq;
      this.servicePreviewLoading = true;
      this.servicePreviewError = '';
      const fields = {
        command: this.form.command,
        command_source: this.form.command_source,
        procfile_process: this.form.procfile_process,
        port: this.form.port,
        cwd: this.form.cwd,
        pre_start: this.form.pre_start,
        health_type: this.form.health_type,
        health_command: this.form.health_command,
        env: (this.form.env || []).map(e => ({ key: e.key || '', value: e.value || '' })),
      };
      try {
        const resp = await fetch('/api/service/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            workspaceId: this.$root.activeWorkspaceId,
            slot: this.slotIndex,
            fields,
          }),
        });
        const data = await resp.json();
        if (seq !== this.servicePreviewSeq) return;
        if (!resp.ok) {
          this.servicePreview = null;
          this.servicePreviewError = data.error || 'Preview unavailable';
          return;
        }
        this.serviceSuggestedPort = Number.isInteger(data.suggested_port) ? data.suggested_port : null;
        this.servicePreview = data;
        this.servicePreviewError = '';
        if (!this.form.port && this.serviceSuggestedPort && !this.servicePortAutoFilled) {
          this.servicePortAutoFilled = true;
          this.form.port = this.serviceSuggestedPort;
        }
      } catch (err) {
        if (seq !== this.servicePreviewSeq) return;
        this.servicePreview = null;
        this.servicePreviewError = err.message || 'Preview unavailable';
      } finally {
        if (seq === this.servicePreviewSeq) this.servicePreviewLoading = false;
      }
    },
    addEnv() {
      this.form.env.push({ key: '', value: '' });
    },
    removeEnv(i) {
      this.form.env.splice(i, 1);
    },
    addFlashStep() {
      const notification = this.form.notification || cloneNotificationForm();
      if (!Array.isArray(notification.flash.sequence)) notification.flash.sequence = [];
      if (notification.flash.sequence.length >= 6) return;
      notification.flash.sequence.push({ color: '#facc15', duration_ms: 180 });
    },
    removeFlashStep(i) {
      const sequence = this.form.notification?.flash?.sequence;
      if (!Array.isArray(sequence)) return;
      sequence.splice(i, 1);
      if (!sequence.length) sequence.push({ color: '#facc15', duration_ms: 180 });
    },
    loadWebSpeechVoices() {
      try {
        const voices = window.speechSynthesis?.getVoices?.() || [];
        this.webSpeechVoices = Array.isArray(voices)
          ? voices.map(voice => ({
              name: String(voice.name || ''),
              voiceURI: String(voice.voiceURI || ''),
              lang: String(voice.lang || ''),
              default: !!voice.default,
            }))
          : [];
      } catch (_err) {
        this.webSpeechVoices = [];
      }
    },
    onNotificationSpeechEngineChange() {
      const speech = this.form.notification?.speech;
      if (!speech) return;
      const valid = this.notificationVoiceOptions.some(option => option.value === speech.voice);
      if (!valid) speech.voice = speech.engine === 'kokoro' ? 'af_heart' : '';
    },
    onSave() {
      const fields = { ...this.form };
      if (fields.disposition === 'random:') {
        fields.disposition = 'random:' + (fields.random_name || '').trim();
      }
      delete fields.random_name;
      if (this.isValue) {
        fields.name = String(fields.name || '').trim();
        fields.value_type = String(fields.value_type || 'auto');
        fields.format = fields.format && typeof fields.format === 'object' ? { ...fields.format } : { kind: 'auto' };
        delete fields.resolved_value_type;
        delete fields.note;
        delete fields.agent;
        delete fields.model;
        delete fields.activation;
        delete fields.disposition;
        delete fields.watch_column;
        delete fields.expertise_prompt;
        delete fields.trust_mode;
        delete fields.max_retries;
        delete fields.use_worktree;
        delete fields.auto_commit;
        delete fields.auto_pr;
        delete fields.trigger_time;
        delete fields.trigger_interval_minutes;
        delete fields.trigger_every_day;
        delete fields.paused;
        delete fields.command;
        delete fields.cwd;
        delete fields.timeout_seconds;
        delete fields.ticket_delivery;
        delete fields.env;
        delete fields.command_source;
        delete fields.procfile_process;
        delete fields.port;
        delete fields.pre_start;
        delete fields.ticket_action;
        delete fields.startup_grace_seconds;
        delete fields.startup_timeout_seconds;
        delete fields.health_type;
        delete fields.health_url;
        delete fields.health_command;
        delete fields.health_interval_seconds;
        delete fields.health_timeout_seconds;
        delete fields.health_failure_threshold;
        delete fields.on_crash;
        delete fields.stop_timeout_seconds;
        delete fields.log_max_bytes;
        delete fields.notification;
        fields.color = String(fields.color || '').trim();
      } else if (this.isMarker || this.isNotification) {
        delete fields.agent;
        delete fields.model;
        delete fields.expertise_prompt;
        delete fields.trust_mode;
        delete fields.max_retries;
        delete fields.use_worktree;
        delete fields.auto_commit;
        delete fields.auto_pr;
        delete fields.command;
        delete fields.cwd;
        delete fields.timeout_seconds;
        delete fields.ticket_delivery;
        delete fields.env;
        delete fields.command_source;
        delete fields.procfile_process;
        delete fields.port;
        delete fields.pre_start;
        delete fields.ticket_action;
        delete fields.startup_grace_seconds;
        delete fields.startup_timeout_seconds;
        delete fields.health_type;
        delete fields.health_url;
        delete fields.health_command;
        delete fields.health_interval_seconds;
        delete fields.health_timeout_seconds;
        delete fields.health_failure_threshold;
        delete fields.on_crash;
        delete fields.stop_timeout_seconds;
        delete fields.log_max_bytes;
        if (this.isMarker) {
          fields.note = String(fields.note || '');
          delete fields.notification;
        } else {
          delete fields.note;
          fields.notification = cloneNotificationForm(fields.notification);
        }
        fields.color = String(fields.color || '').trim();
      } else if (this.isShell || this.isService) {
        // Drop AI-only fields from the payload so server-side normalization
        // never writes them onto a non-AI slot.
        delete fields.note;
        delete fields.agent;
        delete fields.model;
        delete fields.expertise_prompt;
        delete fields.trust_mode;
        delete fields.use_worktree;
        delete fields.auto_commit;
        delete fields.auto_pr;
        delete fields.notification;
        fields.color = String(fields.color || '').trim();
        fields.env = (fields.env || [])
          .filter(e => e && String(e.key || '').trim())
          .map(e => ({ key: String(e.key).trim(), value: String(e.value || '') }));
        if (this.isShell) {
          delete fields.pre_start;
          delete fields.ticket_action;
          delete fields.startup_grace_seconds;
          delete fields.startup_timeout_seconds;
          delete fields.health_type;
          delete fields.health_url;
          delete fields.health_command;
          delete fields.health_interval_seconds;
          delete fields.health_timeout_seconds;
          delete fields.health_failure_threshold;
          delete fields.on_crash;
          delete fields.stop_timeout_seconds;
          delete fields.log_max_bytes;
        } else {
          delete fields.timeout_seconds;
          delete fields.ticket_delivery;
        }
      } else {
        // Drop non-AI fields from AI payloads.
        delete fields.note;
        delete fields.notification;
        delete fields.command;
        delete fields.cwd;
        delete fields.timeout_seconds;
        delete fields.ticket_delivery;
        delete fields.env;
        delete fields.pre_start;
        delete fields.ticket_action;
        delete fields.startup_grace_seconds;
        delete fields.startup_timeout_seconds;
        delete fields.health_type;
        delete fields.health_url;
        delete fields.health_command;
        delete fields.health_interval_seconds;
        delete fields.health_timeout_seconds;
        delete fields.health_failure_threshold;
        delete fields.on_crash;
        delete fields.stop_timeout_seconds;
        delete fields.log_max_bytes;
        fields.color = String(fields.color || '').trim();
        if (fields.trust_mode !== 'trusted') {
          fields.auto_commit = false;
          fields.auto_pr = false;
        }
      }
      delete fields.type;
      this.$emit('save', { slot: this.slotIndex, fields });
      this.$emit('close');
    },
    onRemove() {
      this.$emit('remove', this.slotIndex);
      this.$emit('close');
    },
    onRestoreDefaultColor() {
      this.form.color = '';
    },
    onSaveProfile() {
      const id = this.form.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');
      this.$emit('save-profile', {
        id,
        name: this.form.name,
        default_agent: this.form.agent,
        default_model: this.form.model,
        color_hint: 'gray',
        expertise_prompt: this.form.expertise_prompt,
      });
    }
  }
};
