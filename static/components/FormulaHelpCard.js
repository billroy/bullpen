let bullpenFormulaHelpIndexCache = null;
let bullpenFormulaHelpIndexPromise = null;
const bullpenFormulaHelpDetailCache = new Map();

function bullpenFormulaHelpPosition(input) {
  const rect = input.getBoundingClientRect();
  const margin = 12;
  const gap = 10;
  const width = Math.min(420, Math.max(280, window.innerWidth - (margin * 2)));
  const height = Math.min(520, Math.max(320, window.innerHeight - (margin * 2)));
  let left = rect.right + gap;
  if (left + width > window.innerWidth - margin) left = rect.left - width - gap;
  if (left < margin) left = Math.max(margin, window.innerWidth - width - margin);
  const top = Math.min(
    Math.max(margin, rect.top),
    Math.max(margin, window.innerHeight - height - margin),
  );
  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    maxHeight: `${height}px`,
  };
}

function bullpenFormulaHelpQuery(input) {
  const value = String(input?.value || '');
  const caret = Number.isInteger(input?.selectionStart) ? input.selectionStart : value.length;
  const match = value.slice(0, caret).match(/([A-Za-z][A-Za-z0-9.]*)$/);
  return match ? match[1].toUpperCase() : '';
}

function requestBullpenFormulaHelp(requestEvent, responseEvent, payload = {}) {
  const socket = window._bullpenSocket;
  if (!socket?.connected) return Promise.reject(new Error('Bullpen is disconnected'));
  const requestId = `formula-help-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error('Formula help timed out'));
    }, 15000);
    const cleanup = () => {
      window.clearTimeout(timer);
      socket.off(responseEvent, onResponse);
      socket.off('formula-help:error', onError);
    };
    const onResponse = eventPayload => {
      if (eventPayload?.request_id !== requestId) return;
      cleanup();
      resolve(eventPayload);
    };
    const onError = eventPayload => {
      if (eventPayload?.request_id !== requestId) return;
      cleanup();
      reject(new Error(eventPayload.error || 'Formula help is unavailable'));
    };
    socket.on(responseEvent, onResponse);
    socket.on('formula-help:error', onError);
    socket.emit(requestEvent, { ...payload, request_id: requestId });
  });
}

async function loadBullpenFormulaHelpIndex() {
  if (bullpenFormulaHelpIndexCache) return bullpenFormulaHelpIndexCache;
  if (!bullpenFormulaHelpIndexPromise) {
    bullpenFormulaHelpIndexPromise = requestBullpenFormulaHelp(
      'formula-help:index',
      'formula-help:indexed',
    )
      .then(payload => {
        if (!Array.isArray(payload?.functions)) throw new Error('Formula help index is invalid');
        bullpenFormulaHelpIndexCache = payload.functions;
        return bullpenFormulaHelpIndexCache;
      })
      .finally(() => {
        bullpenFormulaHelpIndexPromise = null;
      });
  }
  return bullpenFormulaHelpIndexPromise;
}

async function loadBullpenFormulaHelpDetail(name) {
  if (bullpenFormulaHelpDetailCache.has(name)) {
    return bullpenFormulaHelpDetailCache.get(name);
  }
  const payload = await requestBullpenFormulaHelp(
    'formula-help:function',
    'formula-help:function-loaded',
    { name },
  );
  if (!payload?.function) throw new Error('Function help is invalid');
  bullpenFormulaHelpDetailCache.set(name, payload.function);
  return payload.function;
}

const FormulaHelpCard = {
  props: {
    initialQuery: {
      type: String,
      default: '',
    },
    positionStyle: {
      type: Object,
      default: () => ({}),
    },
  },
  emits: ['close'],
  template: `
    <Teleport to="body">
      <section class="formula-help-card"
               data-formula-help
               aria-label="Formula function help"
               :style="positionStyle"
               @pointerdown.stop
               @click.stop
               @keydown.esc.prevent.stop="$emit('close')">
        <header class="formula-help-header">
          <button v-if="selectedName"
                  type="button"
                  class="formula-help-back"
                  @click="showIndex"
                  aria-label="Back to function search">&larr;</button>
          <strong>{{ selectedName || 'Formula help' }}</strong>
          <button type="button"
                  class="formula-help-close"
                  @click="$emit('close')"
                  aria-label="Close formula help">&times;</button>
        </header>

        <template v-if="!selectedName">
          <label class="formula-help-search-label" for="formula-help-search">Search functions</label>
          <input id="formula-help-search"
                 ref="searchInput"
                 v-model="query"
                 class="formula-help-search"
                 type="search"
                 autocomplete="off"
                 placeholder="Name, category, or argument"
                 @keydown.down.prevent="focusFirstResult">
          <div v-if="loading" class="formula-help-status">Loading function index…</div>
          <div v-else-if="error" class="formula-help-status formula-help-error">
            <span>{{ error }}</span>
            <button type="button" class="formula-help-retry" @click="loadIndex">Retry</button>
          </div>
          <div v-else class="formula-help-results" aria-label="Formula functions">
            <button v-for="item in filteredFunctions"
                    :key="item.name"
                    ref="resultButtons"
                    type="button"
                    class="formula-help-result"
                    @click="selectFunction(item.name)">
              <span class="formula-help-result-heading">
                <strong>{{ item.name }}</strong>
                <span>{{ item.category }}</span>
              </span>
              <code>{{ item.signature }}</code>
            </button>
            <p v-if="!filteredFunctions.length" class="formula-help-empty">
              No matching functions.
            </p>
          </div>
        </template>

        <div v-else class="formula-help-detail">
          <div v-if="detailLoading" class="formula-help-status">Loading {{ selectedName }}…</div>
          <div v-else-if="error" class="formula-help-status formula-help-error">
            <span>{{ error }}</span>
            <button type="button" class="formula-help-retry" @click="selectFunction(selectedName)">Retry</button>
          </div>
          <template v-else-if="detail">
            <div class="formula-help-category">
              {{ detail.category }}
              <span v-if="detail.accepts_ranges" class="formula-help-range-badge">Accepts ranges</span>
            </div>
            <div class="formula-help-syntax-row">
              <code>{{ detail.signature }}</code>
              <button type="button" class="formula-help-copy" @click="copyText(detail.signature, 'Syntax copied')">Copy</button>
            </div>
            <div class="formula-help-prose" v-html="renderedDocumentation"></div>
            <div v-if="detail.examples?.length" class="formula-help-examples">
              <strong>Example</strong>
              <div v-for="example in detail.examples" :key="example" class="formula-help-example-row">
                <code>{{ example }}</code>
                <button type="button" class="formula-help-copy" @click="copyText(example, 'Example copied')">Copy</button>
              </div>
            </div>
          </template>
        </div>
        <div class="formula-help-live" aria-live="polite">{{ liveMessage }}</div>
      </section>
    </Teleport>
  `,
  data() {
    return {
      query: this.initialQuery,
      functions: [],
      selectedName: '',
      detail: null,
      loading: true,
      detailLoading: false,
      error: '',
      liveMessage: '',
    };
  },
  computed: {
    filteredFunctions() {
      const needle = this.query.trim().toLowerCase();
      if (!needle) return this.functions;
      return this.functions.filter(item => (
        `${item.name} ${item.category} ${item.signature} ${item.summary || ''}`
          .toLowerCase()
          .includes(needle)
      ));
    },
    renderedDocumentation() {
      const markdown = String(this.detail?.documentation || '');
      if (!markdown) return '';
      return window.markdownit({ html: false, linkify: false }).render(markdown);
    },
  },
  mounted() {
    this.loadIndex();
    this.$nextTick(() => this.$refs.searchInput?.focus?.());
  },
  beforeUnmount() {
    if (this._liveTimer) window.clearTimeout(this._liveTimer);
  },
  methods: {
    async loadIndex() {
      this.loading = true;
      this.error = '';
      try {
        this.functions = await loadBullpenFormulaHelpIndex();
      } catch (_error) {
        this.error = 'Could not load formula help.';
      } finally {
        this.loading = false;
      }
    },
    async selectFunction(name) {
      this.selectedName = name;
      this.detail = null;
      this.detailLoading = true;
      this.error = '';
      try {
        this.detail = await loadBullpenFormulaHelpDetail(name);
      } catch (_error) {
        this.error = `Could not load help for ${name}.`;
      } finally {
        this.detailLoading = false;
      }
    },
    showIndex() {
      this.selectedName = '';
      this.detail = null;
      this.error = '';
      this.$nextTick(() => this.$refs.searchInput?.focus?.());
    },
    focusFirstResult() {
      const buttons = this.$refs.resultButtons;
      const first = Array.isArray(buttons) ? buttons[0] : buttons;
      first?.focus?.();
    },
    async copyText(value, message) {
      if (!navigator.clipboard?.writeText) {
        this.announce('Clipboard is unavailable.');
        return;
      }
      try {
        await navigator.clipboard.writeText(String(value || ''));
        this.announce(message);
      } catch (_error) {
        this.announce('Could not copy to the clipboard.');
      }
    },
    announce(message) {
      this.liveMessage = message;
      if (this._liveTimer) window.clearTimeout(this._liveTimer);
      this._liveTimer = window.setTimeout(() => {
        this.liveMessage = '';
      }, 1800);
    },
  },
};
