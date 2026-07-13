const LiveAgentChatTab = {
  props: {
    sessionId: {
      type: String,
      default: null,
    },
    workspaceId: {
      type: String,
      default: null,
    },
    lastAiSelection: {
      type: Object,
      default: null,
    },
  },
  data() {
    return {
      provider: 'claude',
      model: 'claude-sonnet-4-6',
      input: '',
      messages: [],       // {role: 'user'|'assistant', content: string, streaming?: bool}
      busy: false,
      activeSessionId: this.sessionId || _generateChatSessionId(),
      _streamingBuf: '',
      claudeModels: [],
      claudeModelsStatus: '',
      claudeModelsError: '',
      claudeModelsLoading: false,
      claudeModelsRequestSeq: 0,
      codexModels: [],
      codexModelsStatus: '',
      codexModelsError: '',
      codexModelsLoading: false,
      codexModelsRequestSeq: 0,
      opencodeModels: [],
      opencodeModelsStatus: '',
      opencodeModelsError: '',
      opencodeModelsLoading: false,
      opencodeModelsRequestSeq: 0,
      opencodeModelProvider: '',
      opencodeModelSearch: '',
      userSelectedProviderModel: false,
    };
  },
  computed: {
    preferredAiSelection() {
      return normalizedLastAiSelection(this.lastAiSelection);
    },
    providerOptions() {
      return withPreferredOption(AI_PROVIDER_OPTIONS, this.preferredAiSelection?.agent);
    },
    modelOptions() {
      const fallback = MODEL_OPTIONS[this.provider] || [];
      let options = fallback;
      if (this.provider === 'codex' && this.codexModels.length) {
        options = this.codexModels.map(model => model.id);
      } else if (this.provider === 'claude' && this.claudeModels.length) {
        options = this.claudeModels.map(model => model.id);
      }
      const preferred = this.preferredAiSelection;
      const preferredModel = preferred?.agent === this.provider ? preferred.model : '';
      const current = String(this.model || '').trim();
      const hasDynamicCatalog = (this.provider === 'codex' && this.codexModels.length)
        || (this.provider === 'claude' && this.claudeModels.length);
      const currentModel = hasDynamicCatalog && !options.includes(current)
        ? current
        : '';
      return withPreferredOption(withPreferredOption(options, currentModel), preferredModel);
    },
    isClaudeProvider() {
      return this.provider === 'claude';
    },
    claudeCatalogHint() {
      if (this.claudeModelsLoading) return 'Loading Claude models...';
      if (this.claudeModelsError) return this.claudeModelsError;
      return '';
    },
    isCodexProvider() {
      return this.provider === 'codex';
    },
    codexCatalogHint() {
      if (this.codexModelsLoading) return 'Loading Codex models...';
      if (this.codexModelsError) return this.codexModelsError;
      return '';
    },
    isOpenCodeProvider() {
      return this.provider === 'opencode';
    },
    currentOpenCodeProvider() {
      const model = String(this.model || '').trim();
      if (!model.includes('/')) return '';
      return model.split('/', 1)[0];
    },
    opencodeProviders() {
      const providers = this.opencodeModels
        .map(model => String(model.provider || '').trim())
        .filter(Boolean);
      const currentProvider = this.currentOpenCodeProvider;
      if (currentProvider) providers.unshift(currentProvider);
      return [...new Set(providers)].sort((a, b) => a.localeCompare(b));
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
      const current = String(this.model || '').trim();
      return !!current && this.opencodeModels.some(model => model.id === current);
    },
    opencodeCatalogHint() {
      if (this.opencodeModelsLoading) return 'Loading OpenCode models...';
      if (this.opencodeModelsError) return this.opencodeModelsError;
      if (!this.opencodeModels.length && this.opencodeModelsStatus === 'ok') return 'No OpenCode models returned. Enter a custom provider/model value.';
      if (this.opencodeModelsStatus === 'unavailable') return 'OpenCode CLI is not available. Install OpenCode or set BULLPEN_OPENCODE_PATH, then enter a custom provider/model value if needed.';
      return '';
    },
    canSend() {
      return !!this.input.trim() && !this.busy && (!this.isOpenCodeProvider || !!String(this.model || '').trim());
    },
  },
  watch: {
    provider(newProvider) {
      if (newProvider === 'opencode') {
        const preferred = this.preferredAiSelection;
        if (!String(this.model || '').includes('/')) this.model = preferred?.agent === 'opencode' ? preferred.model : '';
        this.syncOpenCodeModelProvider();
        this.ensureOpenCodeModels();
        return;
      }
      if (newProvider === 'codex') this.ensureCodexModels();
      if (newProvider === 'claude') this.ensureClaudeModels();
      const opts = this.modelOptions;
      if (!opts.includes(this.model)) this.model = opts[0] || '';
    },
    lastAiSelection: {
      immediate: true,
      handler(selection) {
        if (this.busy || this.messages.length || this.userSelectedProviderModel) return;
        this.applyPreferredSelection(selection);
      },
    },
  },
  mounted() {
    this._registerSocketHandlers();
    if (this.provider === 'claude') this.ensureClaudeModels();
    if (this.provider === 'codex') this.ensureCodexModels();
    if (this.provider === 'opencode') this.ensureOpenCodeModels();
    this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
  },
  beforeUnmount() {
    this._removeSocketHandlers();
  },
  methods: {
    _registerSocketHandlers() {
      const s = window._bullpenSocket;
      if (!s) return;
      const _sameChatSession = (data) => {
        if (!data || data.sessionId !== this.activeSessionId) return false;
        if (data.workspaceId && this.workspaceId && data.workspaceId !== this.workspaceId) return false;
        return true;
      };
      this._onOutput = (data) => {
        if (!_sameChatSession(data)) return;
        const last = this.messages[this.messages.length - 1];
        if (!last || last.role !== 'assistant' || !last.streaming) {
          this.messages.push({ role: 'assistant', content: '', streaming: true });
        }
        const msg = this.messages[this.messages.length - 1];
        const lines = data.lines || [];
        for (const line of lines) {
          if (msg.content && !msg.content.endsWith('\n')) {
            msg.content += '\n';
          }
          msg.content += line;
        }
        this._scrollToBottom();
      };
      this._onUser = (data) => {
        if (!_sameChatSession(data)) return;
        if (data.senderSid && s.id && data.senderSid === s.id) return;
        const text = String(data.message || '').trim();
        if (!text) return;
        this.messages.push({ role: 'user', content: text });
        this.busy = true;
        this._scrollToBottom();
      };
      this._onDone = (data) => {
        if (!_sameChatSession(data)) return;
        const last = this.messages[this.messages.length - 1];
        if (last && last.streaming) last.streaming = false;
        this.busy = false;
        this._scrollToBottom();
      };
      this._onError = (data) => {
        if (!_sameChatSession(data)) return;
        this.messages.push({ role: 'system', content: 'Error: ' + (data.message || 'Unknown error') });
        this.busy = false;
        this._scrollToBottom();
      };
      this._onCleared = (data) => {
        if (!_sameChatSession(data)) return;
        this.messages = [];
        this.busy = false;
      };
      s.on('chat:user', this._onUser);
      s.on('chat:output', this._onOutput);
      s.on('chat:done', this._onDone);
      s.on('chat:error', this._onError);
      s.on('chat:cleared', this._onCleared);
    },
    _removeSocketHandlers() {
      const s = window._bullpenSocket;
      if (!s) return;
      if (this._onUser) s.off('chat:user', this._onUser);
      if (this._onOutput) s.off('chat:output', this._onOutput);
      if (this._onDone) s.off('chat:done', this._onDone);
      if (this._onError) s.off('chat:error', this._onError);
      if (this._onCleared) s.off('chat:cleared', this._onCleared);
    },
    applyPreferredSelection(selection) {
      const preferred = normalizedLastAiSelection(selection);
      if (!preferred) return;
      this.provider = preferred.agent;
      this.model = preferred.model;
      if (this.provider === 'opencode') {
        this.syncOpenCodeModelProvider();
        this.ensureOpenCodeModels();
      } else if (this.provider === 'codex') {
        this.ensureCodexModels();
      } else if (this.provider === 'claude') {
        this.ensureClaudeModels();
      }
    },
    onProviderChange() {
      this.userSelectedProviderModel = true;
    },
    onModelChange() {
      this.userSelectedProviderModel = true;
    },
    sendMessage() {
      const text = this.input.trim();
      if (!text || this.busy) return;
      if (this.isOpenCodeProvider && !String(this.model || '').trim()) return;
      this.messages.push({ role: 'user', content: text });
      this.input = '';
      this.busy = true;
      this._scrollToBottom();
      const s = window._bullpenSocket;
      if (s) {
        s.emit('chat:send', {
          sessionId: this.activeSessionId,
          provider: this.provider,
          model: this.model,
          message: text,
          workspaceId: this.workspaceId,
        });
      }
    },
    stopChat() {
      const s = window._bullpenSocket;
      if (s) s.emit('chat:stop', { sessionId: this.activeSessionId, workspaceId: this.workspaceId });
    },
    clearChat() {
      this.messages = [];
      this.busy = false;
      const s = window._bullpenSocket;
      if (s) s.emit('chat:clear', { sessionId: this.activeSessionId, workspaceId: this.workspaceId });
      this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
    },
    ensureCodexModels() {
      if (this.codexModels.length || this.codexModelsLoading) return;
      this.loadCodexModels();
    },
    async loadCodexModels({ refresh = false } = {}) {
      const requestSeq = ++this.codexModelsRequestSeq;
      this.codexModelsLoading = true;
      this.codexModelsError = '';
      try {
        const data = await this.$root.requestCodexModels({
          workspaceId: this.workspaceId,
          refresh: !!refresh,
        });
        if (requestSeq !== this.codexModelsRequestSeq) return;
        this.codexModelsStatus = data.status || 'ok';
        const nextModels = Array.isArray(data.models) ? data.models.filter(model => model?.id) : [];
        if (nextModels.length) this.codexModels = nextModels;
        this.codexModelsError = data.status === 'ok' ? '' : (data.error || 'Using fallback Codex models.');
      } catch (err) {
        if (requestSeq !== this.codexModelsRequestSeq) return;
        this.codexModelsStatus = 'error';
        this.codexModelsError = err.message || 'Codex model catalog is unavailable; using fallback models.';
      } finally {
        if (requestSeq === this.codexModelsRequestSeq) this.codexModelsLoading = false;
      }
    },
    refreshCodexModels() {
      return this.loadCodexModels({ refresh: true });
    },
    ensureClaudeModels() {
      if (this.claudeModels.length || this.claudeModelsLoading) return;
      this.loadClaudeModels();
    },
    async loadClaudeModels({ refresh = false } = {}) {
      const requestSeq = ++this.claudeModelsRequestSeq;
      this.claudeModelsLoading = true;
      this.claudeModelsError = '';
      try {
        const data = await this.$root.requestClaudeModels({
          workspaceId: this.workspaceId,
          refresh: !!refresh,
        });
        if (requestSeq !== this.claudeModelsRequestSeq) return;
        this.claudeModelsStatus = data.status || 'ok';
        const nextModels = Array.isArray(data.models) ? data.models.filter(model => model?.id) : [];
        if (nextModels.length) this.claudeModels = nextModels;
        this.claudeModelsError = data.status === 'ok' ? '' : (data.error || 'Using cached or fallback Claude models.');
      } catch (err) {
        if (requestSeq !== this.claudeModelsRequestSeq) return;
        this.claudeModelsStatus = 'error';
        this.claudeModelsError = err.message || 'Claude model catalog is unavailable; using fallback models.';
      } finally {
        if (requestSeq === this.claudeModelsRequestSeq) this.claudeModelsLoading = false;
      }
    },
    refreshClaudeModels() {
      return this.loadClaudeModels({ refresh: true });
    },
    syncOpenCodeModelProvider() {
      const selectedProvider = String(this.opencodeModelProvider || '').trim();
      if (!selectedProvider) return;
      const knownProviders = this.opencodeModels
        .map(model => String(model.provider || '').trim())
        .filter(Boolean);
      if (!knownProviders.includes(selectedProvider)) this.opencodeModelProvider = '';
    },
    ensureOpenCodeModels() {
      if (this.opencodeModels.length || this.opencodeModelsLoading) return;
      this.loadOpenCodeModels();
    },
    async loadOpenCodeModels({ refresh = false } = {}) {
      const requestSeq = ++this.opencodeModelsRequestSeq;
      this.opencodeModelsLoading = true;
      this.opencodeModelsError = '';
      try {
        const data = await this.$root.requestOpenCodeModels({
          workspaceId: this.workspaceId,
          refresh: !!refresh,
        });
        if (requestSeq !== this.opencodeModelsRequestSeq) return;
        const status = data.status || 'ok';
        const nextModels = Array.isArray(data.models) ? data.models : [];
        this.opencodeModelsStatus = status;
        if (status === 'error') {
          this.opencodeModelsError = data.error || 'OpenCode model catalog is unavailable. Enter a custom provider/model value.';
        } else {
          this.opencodeModels = nextModels;
          this.opencodeModelsError = '';
        }
        this.syncOpenCodeModelProvider();
      } catch (err) {
        if (requestSeq !== this.opencodeModelsRequestSeq) return;
        this.opencodeModelsStatus = 'error';
        this.opencodeModelsError = err.message || 'OpenCode model catalog is unavailable. Enter a custom provider/model value.';
      } finally {
        if (requestSeq === this.opencodeModelsRequestSeq) this.opencodeModelsLoading = false;
      }
    },
    refreshOpenCodeModels() {
      return this.loadOpenCodeModels({ refresh: true });
    },
    onOpenCodeProviderChange() {
      this.userSelectedProviderModel = true;
      this.opencodeModelSearch = '';
    },
    onOpenCodeModelSelect(e) {
      this.userSelectedProviderModel = true;
      this.model = e.target.value || '';
      this.syncOpenCodeModelProvider();
    },
    onKeydown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    },
    _scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.messages;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
  },
  template: `
    <div class="chat-tab">
      <div class="chat-toolbar">
        <label class="chat-label">Provider</label>
        <select class="form-select chat-select" v-model="provider" :disabled="busy" @change="onProviderChange">
          <option v-for="p in providerOptions" :key="p" :value="p">{{ p }}</option>
        </select>
        <label class="chat-label">Model</label>
        <select v-if="!isOpenCodeProvider" class="form-select chat-select" v-model="model" :disabled="busy" @change="onModelChange">
          <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
        </select>
        <button v-if="isCodexProvider" class="btn btn-sm" @click="refreshCodexModels" :disabled="busy || codexModelsLoading">
          {{ codexModelsLoading ? 'Refreshing...' : 'Refresh' }}
        </button>
        <span v-if="isCodexProvider && codexCatalogHint" class="chat-hint">{{ codexCatalogHint }}</span>
        <button v-if="isClaudeProvider" class="btn btn-sm" @click="refreshClaudeModels" :disabled="busy || claudeModelsLoading">
          {{ claudeModelsLoading ? 'Refreshing...' : 'Refresh' }}
        </button>
        <span v-if="isClaudeProvider && claudeCatalogHint" class="chat-hint">{{ claudeCatalogHint }}</span>
        <template v-if="isOpenCodeProvider">
          <select class="form-select chat-select" v-model="opencodeModelProvider" :disabled="busy" @change="onOpenCodeProviderChange">
            <option value="">All providers</option>
            <option v-for="provider in opencodeProviders" :key="provider" :value="provider">{{ provider }}</option>
          </select>
          <input class="form-input chat-model-search" v-model="opencodeModelSearch" :disabled="busy" placeholder="Search models">
          <select class="form-select chat-select chat-model-select" :value="model" :disabled="busy" @change="onOpenCodeModelSelect">
            <option value="">Select a model...</option>
            <option v-if="model && !isOpenCodeModelInCatalog" :value="model">{{ model }}</option>
            <option v-for="m in filteredOpenCodeModels" :key="m.id" :value="m.id">{{ m.id }}</option>
          </select>
          <input class="form-input chat-custom-model" v-model="model" :disabled="busy" placeholder="provider/model" @input="onModelChange">
          <button class="btn btn-sm" @click="refreshOpenCodeModels" :disabled="busy || opencodeModelsLoading">
            {{ opencodeModelsLoading ? 'Refreshing...' : 'Refresh' }}
          </button>
          <span v-if="opencodeCatalogHint" class="chat-hint">{{ opencodeCatalogHint }}</span>
        </template>
        <button class="btn btn-sm" @click="clearChat" :disabled="busy">Clear</button>
      </div>
      <div class="chat-messages" ref="messages">
        <div v-if="messages.length === 0" class="chat-empty">
          Start a conversation with the AI agent.
        </div>
        <div v-for="(msg, i) in messages" :key="i"
             :class="['chat-message', 'chat-message--' + msg.role]">
          <div class="chat-bubble">
            <pre class="chat-text">{{ msg.content }}<span v-if="msg.streaming" class="chat-cursor">▍</span></pre>
          </div>
        </div>
      </div>
      <div class="chat-input-row">
        <textarea
          ref="input"
          class="chat-input"
          v-model="input"
          :disabled="busy"
          placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
          rows="3"
          @keydown="onKeydown"
        ></textarea>
        <button v-if="busy" class="btn btn-danger chat-stop-btn" @click="stopChat">Stop</button>
        <button v-else class="btn chat-send-btn" :disabled="!canSend" @click="sendMessage">Send</button>
      </div>
    </div>
  `,
};

function _generateChatSessionId() {
  return 'chat-' + crypto.randomUUID();
}
