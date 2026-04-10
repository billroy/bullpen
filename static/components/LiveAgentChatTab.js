const LiveAgentChatTab = {
  data() {
    return {
      provider: 'claude',
      model: 'claude-sonnet-4-6',
      input: '',
      messages: [],       // {role: 'user'|'assistant', content: string, streaming?: bool}
      busy: false,
      sessionId: _generateChatSessionId(),
      _streamingBuf: '',
    };
  },
  computed: {
    providerOptions() {
      return ['claude', 'codex'];
    },
    modelOptions() {
      const map = {
        claude: ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5-20251001'],
        codex: ['codex-mini-latest', 'o4-mini'],
      };
      return map[this.provider] || [];
    },
  },
  watch: {
    provider(newProvider) {
      const opts = this.modelOptions;
      if (!opts.includes(this.model)) this.model = opts[0] || '';
    },
  },
  mounted() {
    this._registerSocketHandlers();
    this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
  },
  beforeUnmount() {
    this._removeSocketHandlers();
  },
  methods: {
    _registerSocketHandlers() {
      const s = window._bullpenSocket;
      if (!s) return;
      this._onOutput = (data) => {
        if (data.sessionId !== this.sessionId) return;
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
      this._onDone = (data) => {
        if (data.sessionId !== this.sessionId) return;
        const last = this.messages[this.messages.length - 1];
        if (last && last.streaming) last.streaming = false;
        this.busy = false;
        this._scrollToBottom();
      };
      this._onError = (data) => {
        if (data.sessionId !== this.sessionId) return;
        this.messages.push({ role: 'system', content: 'Error: ' + (data.message || 'Unknown error') });
        this.busy = false;
        this._scrollToBottom();
      };
      s.on('chat:output', this._onOutput);
      s.on('chat:done', this._onDone);
      s.on('chat:error', this._onError);
    },
    _removeSocketHandlers() {
      const s = window._bullpenSocket;
      if (!s) return;
      if (this._onOutput) s.off('chat:output', this._onOutput);
      if (this._onDone) s.off('chat:done', this._onDone);
      if (this._onError) s.off('chat:error', this._onError);
    },
    sendMessage() {
      const text = this.input.trim();
      if (!text || this.busy) return;
      this.messages.push({ role: 'user', content: text });
      this.input = '';
      this.busy = true;
      this._scrollToBottom();
      const s = window._bullpenSocket;
      if (s) {
        s.emit('chat:send', {
          sessionId: this.sessionId,
          provider: this.provider,
          model: this.model,
          message: text,
        });
      }
    },
    stopChat() {
      const s = window._bullpenSocket;
      if (s) s.emit('chat:stop', { sessionId: this.sessionId });
    },
    clearChat() {
      this.messages = [];
      this.busy = false;
      const s = window._bullpenSocket;
      if (s) s.emit('chat:clear', { sessionId: this.sessionId });
      this.sessionId = _generateChatSessionId();
      this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
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
        <select class="form-select chat-select" v-model="provider" :disabled="busy">
          <option v-for="p in providerOptions" :key="p" :value="p">{{ p }}</option>
        </select>
        <label class="chat-label">Model</label>
        <select class="form-select chat-select" v-model="model" :disabled="busy">
          <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
        </select>
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
        <button v-else class="btn chat-send-btn" :disabled="!input.trim()" @click="sendMessage">Send</button>
      </div>
    </div>
  `,
};

function _generateChatSessionId() {
  return 'chat-' + Math.random().toString(36).slice(2, 10) + '-' + Date.now();
}
