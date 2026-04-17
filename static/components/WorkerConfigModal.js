const WorkerConfigModal = {
  props: ['worker', 'slotIndex', 'columns', 'workers', 'gridRows', 'gridCols'],
  emits: ['close', 'save', 'remove', 'save-profile'],
  data() {
    return {
      form: {},
      overlayMouseDown: false
    };
  },
  watch: {
    worker: {
      immediate: true,
      handler(w, oldW) {
        if (w) {
          if (!oldW) {
            this.$nextTick(() => { if (this.$refs.overlay) this.$refs.overlay.focus(); });
          }
          let disposition = w.disposition || 'review';
          let randomName = '';
          if (disposition.startsWith('random:')) {
            randomName = disposition.substring('random:'.length);
            disposition = 'random:';
          }
          this.form = {
            name: w.name || '',
            agent: w.agent || 'claude',
            model: w.model || 'claude-sonnet-4-6',
            activation: w.activation || 'on_drop',
            disposition,
            random_name: randomName,
            watch_column: w.watch_column || '',
            expertise_prompt: w.expertise_prompt || '',
            max_retries: w.max_retries ?? 1,
            use_worktree: w.use_worktree || false,
            auto_commit: w.auto_commit || false,
            auto_pr: w.auto_pr || false,
            trigger_time: w.trigger_time || '',
            trigger_interval_minutes: w.trigger_interval_minutes || 60,
            trigger_every_day: w.trigger_every_day || false,
            paused: w.paused || false,
          };
        }
      }
    }
  },
  computed: {
    otherWorkers() {
      if (!this.workers) return [];
      return this.workers
        .map((w, i) => w && i !== this.slotIndex ? { name: w.name, slot: i } : null)
        .filter(Boolean);
    },
    modelOptions() {
      return MODEL_OPTIONS[this.form.agent] || ['default'];
    },
    passAvailability() {
      // Disable pass options when this worker is at the edge of the grid
      // or the adjacent cell has no worker — mirroring the drag-handle
      // availability shown on the grid.
      const rows = this.gridRows || 4;
      const cols = this.gridCols || 6;
      const idx = this.slotIndex;
      const slots = this.workers || [];
      if (idx == null || idx < 0) return { up: false, down: false, left: false, right: false };
      const r = Math.floor(idx / cols);
      const c = idx % cols;
      const occupied = (targetIdx) => targetIdx >= 0 && targetIdx < slots.length && !!slots[targetIdx];
      return {
        up: r > 0 && occupied((r - 1) * cols + c),
        down: r < rows - 1 && occupied((r + 1) * cols + c),
        left: c > 0 && occupied(r * cols + (c - 1)),
        right: c < cols - 1 && occupied(r * cols + (c + 1)),
      };
    },
    showCustomModel() {
      return !this.modelOptions.includes(this.form.model);
    },
    modelSelectValue() {
      return this.modelOptions.includes(this.form.model) ? this.form.model : '__custom__';
    }
  },
  template: `
    <div v-if="worker" class="modal-overlay" @mousedown.self="overlayMouseDown = true" @click.self="onOverlayClick" @keydown.escape="$emit('close')" @keydown.meta.enter="onPrimaryShortcut" tabindex="0" ref="overlay">
      <div class="modal modal-wide" @mouseup="overlayMouseDown = false">
        <div class="modal-header">
          <h2>Configure: {{ form.name }}</h2>
          <button class="btn btn-icon" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <label class="form-label">
            Name
            <input class="form-input" v-model="form.name">
          </label>
          <label class="form-label">
            Expertise Prompt
            <textarea class="form-textarea" v-model="form.expertise_prompt" rows="5"></textarea>
          </label>
          <div class="form-row">
            <label class="form-label">
              AI Provider
              <select class="form-select" v-model="form.agent" @change="onAgentChange">
                <option value="claude">Claude</option>
                <option value="codex">Codex</option>
                <option value="gemini">Gemini</option>
              </select>
            </label>
            <label class="form-label">
              Model
              <select class="form-select" :value="modelSelectValue" @change="onModelSelect">
                <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
                <option value="__custom__">Custom...</option>
              </select>
              <input v-if="showCustomModel" class="form-input" v-model="form.model" placeholder="Enter model slug" style="margin-top: 4px;">
            </label>
          </div>
          <div class="form-row">
            <label class="form-label">
              Input Trigger
              <select class="form-select" v-model="form.activation">
                <option value="on_drop">On Drop</option>
                <option value="on_queue">On Queue (Watch Column)</option>
                <option value="manual">Manual</option>
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
            <label class="form-label form-label-inline" v-if="form.activation === 'at_time' || form.activation === 'on_interval'">
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
          <div class="form-row">
            <label class="form-label form-label-inline">
              <input type="checkbox" v-model="form.use_worktree">
              Use Git Worktree
              <span class="form-hint">(isolate agent work in a separate branch)</span>
            </label>
            <label class="form-label form-label-inline">
              <input type="checkbox" v-model="form.auto_commit">
              Auto-Commit
              <span class="form-hint">(commit agent changes on success)</span>
            </label>
            <label class="form-label form-label-inline">
              <input type="checkbox" v-model="form.auto_pr" :disabled="!form.use_worktree || !form.auto_commit">
              Auto-PR
              <span class="form-hint">(open PR after commit; requires worktree + auto-commit)</span>
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-danger btn-sm" @click="onRemove">Remove Worker</button>
          <div class="modal-footer-right">
            <button class="btn btn-sm" @click="onSaveProfile">Save as Profile</button>
            <button class="btn" @click="$emit('close')">Cancel</button>
            <button class="btn btn-primary" @click="onSave">Save</button>
          </div>
        </div>
      </div>
    </div>
  `,
  methods: {
    onPrimaryShortcut(e) {
      e.preventDefault();
      this.onSave();
    },
    onAgentChange() {
      this.form.model = this.modelOptions[0];
    },
    onModelSelect(e) {
      if (e.target.value === '__custom__') {
        this.form.model = '';
      } else {
        this.form.model = e.target.value;
      }
    },
    onOverlayClick() {
      if (this.overlayMouseDown) this.$emit('close');
      this.overlayMouseDown = false;
    },
    onSave() {
      const fields = { ...this.form };
      if (fields.disposition === 'random:') {
        fields.disposition = 'random:' + (fields.random_name || '').trim();
      }
      delete fields.random_name;
      this.$emit('save', { slot: this.slotIndex, fields });
      this.$emit('close');
    },
    onRemove() {
      this.$emit('remove', this.slotIndex);
      this.$emit('close');
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
