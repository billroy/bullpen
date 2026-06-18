const BentoImportReviewModal = {
  props: ['visible', 'preview', 'columns'],
  emits: ['close', 'apply'],
  data() {
    return {
      placementStrategy: 'place-right',
      anchorCol: 0,
      anchorRow: 0,
      approvals: {},
      targetStatus: 'backlog',
    };
  },
  template: `
    <div v-if="visible && preview" class="modal-overlay" @click.self="$emit('close')" @keydown.escape="$emit('close')" @keydown.meta.enter="submit" tabindex="0" ref="overlay">
      <div class="modal modal-wide bento-import-modal">
        <div class="modal-header">
          <h2>Import Package</h2>
          <button class="btn btn-icon" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body bento-import-body">
          <section class="bento-review-section">
            <div class="bento-review-heading">
              <span>{{ displayKind }}</span>
              <span class="bento-review-count">{{ itemCount }} item{{ itemCount === 1 ? '' : 's' }}</span>
            </div>
            <div v-if="items.length" class="bento-review-items">
              <div v-for="item in items" :key="item.item_id || item.title || item.name" class="bento-review-item">
                <span class="bento-review-item-name">{{ item.name || item.title || item.label || 'Item' }}</span>
                <span class="bento-review-item-meta">{{ item.worker_type || item.ticket_type || item.type || 'item' }}</span>
              </div>
            </div>
          </section>

          <section v-if="hasPlacementConflict" class="bento-review-section">
            <div class="bento-review-heading">Placement</div>
            <label class="form-label">
              Strategy
              <select class="form-select" v-model="placementStrategy">
                <option value="place-right">Place right</option>
                <option value="place-below">Place below</option>
                <option value="choose-anchor">Choose anchor</option>
              </select>
            </label>
            <div v-if="placementStrategy === 'choose-anchor'" class="bento-anchor-grid">
              <label class="form-label">
                Column
                <input class="form-input" type="number" v-model.number="anchorCol">
              </label>
              <label class="form-label">
                Row
                <input class="form-input" type="number" v-model.number="anchorRow">
              </label>
            </div>
          </section>

          <section v-if="capabilityEntries.length" class="bento-review-section">
            <div class="bento-review-heading">Capabilities</div>
            <label v-for="entry in capabilityEntries" :key="entry.key" class="bento-review-check">
              <input type="checkbox" v-model="approvals[entry.key]">
              <span>{{ entry.label }}</span>
              <span class="bento-review-count">{{ entry.count }}</span>
            </label>
          </section>

          <section v-if="isTicketPackage" class="bento-review-section">
            <div class="bento-review-heading">Ticket Target</div>
            <label class="form-label">
              Column
              <select class="form-select" v-model="targetStatus">
                <option v-for="column in safeTicketColumns" :key="column.key" :value="column.key">
                  {{ column.label }}
                </option>
              </select>
            </label>
          </section>

          <section v-if="warnings.length" class="bento-review-section">
            <div class="bento-review-heading">Warnings</div>
            <ul class="bento-review-warnings">
              <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
            </ul>
          </section>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="$emit('close')">Cancel</button>
          <button class="btn btn-primary" @click="submit">Import</button>
        </div>
      </div>
    </div>
  `,
  computed: {
    kind() {
      return this.preview?.bullpen?.kind || this.preview?.kind || 'package';
    },
    displayKind() {
      return String(this.kind || 'package').replace(/-/g, ' ');
    },
    items() {
      return Array.isArray(this.preview?.bullpen?.items) ? this.preview.bullpen.items : [];
    },
    itemCount() {
      return this.items.length || Number(this.preview?.item_count || 0);
    },
    hasPlacementConflict() {
      return this.preview?.bullpen?.placement?.status === 'conflict';
    },
    capabilityEntries() {
      const labels = {
        commands: 'Command fields',
        env: 'Environment variables',
        services: 'Service worker settings',
        notifications: 'Notification settings',
        git: 'Git automation settings',
      };
      const capabilities = this.preview?.bullpen?.capabilities || {};
      return Object.entries(labels)
        .map(([key, label]) => ({ key, label, count: Number(capabilities[key] || 0) }))
        .filter(entry => Number.isFinite(entry.count) && entry.count > 0);
    },
    isTicketPackage() {
      return this.kind === 'ticket' || this.kind === 'ticket-bundle';
    },
    safeTicketColumns() {
      const active = new Set(['assigned', 'in_progress', 'in-progress']);
      const columns = Array.isArray(this.columns) ? this.columns : [];
      const safe = columns
        .filter(column => column && typeof column === 'object')
        .map(column => ({
          key: String(column.key || '').trim(),
          label: String(column.label || column.key || '').trim(),
        }))
        .filter(column => column.key && !active.has(column.key));
      return safe.length ? safe : [{ key: 'backlog', label: 'Backlog' }];
    },
    warnings() {
      return Array.isArray(this.preview?.bullpen?.warnings) ? this.preview.bullpen.warnings : [];
    },
  },
  watch: {
    visible(v) {
      if (v) {
        this.resetForm();
        this.$nextTick(() => {
          if (this.$refs.overlay) this.$refs.overlay.focus();
        });
      }
    },
    preview() {
      if (this.visible) this.resetForm();
    },
  },
  methods: {
    resetForm() {
      this.placementStrategy = 'place-right';
      this.anchorCol = 0;
      this.anchorRow = 0;
      this.approvals = {};
      for (const entry of this.capabilityEntries) {
        this.approvals[entry.key] = false;
      }
      const fallback = this.preview?.bullpen?.import?.target_status || 'backlog';
      this.targetStatus = this.safeTicketColumns.some(column => column.key === fallback)
        ? fallback
        : this.safeTicketColumns[0].key;
    },
    submit() {
      const decisions = {};
      if (this.hasPlacementConflict) {
        decisions.placement = { strategy: this.placementStrategy };
        if (this.placementStrategy === 'choose-anchor') {
          decisions.placement.anchor = {
            col: Number(this.anchorCol) || 0,
            row: Number(this.anchorRow) || 0,
          };
        }
      }
      if (this.capabilityEntries.length) {
        decisions.approvals = { ...this.approvals };
      }
      if (this.isTicketPackage) {
        decisions.target_status = this.targetStatus;
      }
      this.$emit('apply', decisions);
    },
  },
};
