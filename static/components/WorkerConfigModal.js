const WorkerConfigModal = {
  props: ['worker', 'slotIndex', 'columns'],
  emits: ['close', 'save', 'remove', 'save-profile'],
  data() {
    return {
      form: {}
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
          this.form = {
            name: w.name || '',
            agent: w.agent || 'claude',
            model: w.model || 'claude-sonnet-4-6',
            activation: w.activation || 'on_drop',
            disposition: w.disposition || 'review',
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
    modelOptions() {
      if (this.form.agent === 'claude') {
        return ['claude-opus-4-6', 'claude-opus-4-5-20250514', 'claude-sonnet-4-6', 'claude-sonnet-4-5-20250514', 'claude-haiku-4-6', 'claude-haiku-4-5-20250414'];
      } else if (this.form.agent === 'codex') {
        return ['o3', 'gpt-4.1', 'codex-1', 'o4-mini', 'o3-mini'];
      }
      return ['default'];
    },
    showCustomModel() {
      return !this.modelOptions.includes(this.form.model);
    },
    modelSelectValue() {
      return this.modelOptions.includes(this.form.model) ? this.form.model : '__custom__';
    }
  },
  template: `
    <div v-if="worker" class="modal-overlay" @click.self="$emit('close')" @keydown.escape="$emit('close')" tabindex="0" ref="overlay">
      <div class="modal modal-wide">
        <div class="modal-header">
          <h2>Configure: {{ form.name }}</h2>
          <button class="btn btn-icon" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <label class="form-label">
            Name
            <input class="form-input" v-model="form.name">
          </label>
          <div class="form-row">
            <label class="form-label">
              AI Provider
              <select class="form-select" v-model="form.agent" @change="onAgentChange">
                <option value="claude">Claude</option>
                <option value="codex">Codex</option>
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
              Activation
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
              Disposition
              <select class="form-select" v-model="form.disposition">
                <option value="review">Review</option>
                <option value="done">Done</option>
              </select>
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
          <label class="form-label">
            Expertise Prompt
            <textarea class="form-textarea" v-model="form.expertise_prompt" rows="8"></textarea>
          </label>
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
    onSave() {
      this.$emit('save', { slot: this.slotIndex, fields: { ...this.form } });
      this.$emit('close');
    },
    onRemove() {
      if (confirm('Remove this worker from the grid?')) {
        this.$emit('remove', this.slotIndex);
        this.$emit('close');
      }
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
