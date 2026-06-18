const BentoImportReviewModal = {
  props: ['visible', 'preview', 'columns', 'layout', 'gridCols'],
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

          <section v-if="placementRows.length" class="bento-review-section">
            <div class="bento-review-heading">Placement</div>
            <label v-if="hasPlacementConflict" class="form-label">
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
            <div v-if="placementFootprintRows.length" class="bento-placement-footprint" :style="placementFootprintStyle">
              <template v-for="cell in placementFootprintCells" :key="cell.key">
                <div
                  class="bento-placement-cell"
                  :class="{ occupied: cell.occupied, target: cell.target, overlap: cell.occupied && cell.target }"
                  :title="cell.title"
                >
                  <span>{{ cell.label }}</span>
                </div>
              </template>
            </div>
            <div class="bento-placement-table">
              <div class="bento-placement-row bento-placement-header">
                <span>Worker</span>
                <span>Source</span>
                <span>Target</span>
              </div>
              <div v-for="row in placementRows" :key="row.key" class="bento-placement-row">
                <span class="bento-review-item-name">{{ row.name }}</span>
                <span>{{ coordLabel(row.from) }}</span>
                <span>{{ coordLabel(row.to) }}</span>
              </div>
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
    placementRequests() {
      const requested = this.preview?.bullpen?.placement?.requested;
      return Array.isArray(requested) ? requested : [];
    },
    workerPlacementItems() {
      const byId = {};
      for (const item of this.items) {
        if (item?.item_id) byId[item.item_id] = item;
      }
      return this.placementRequests.map((request, index) => {
        const item = byId[request.item_id] || this.items[index] || {};
        const coord = request.coord || item.coord || {};
        return {
          key: request.item_id || item.item_id || `worker-${index}`,
          name: item.name || item.label || `Worker ${index + 1}`,
          coord: {
            col: this.safeInt(coord.col, 0),
            row: this.safeInt(coord.row, 0),
          },
        };
      });
    },
    occupiedCoords() {
      const slots = Array.isArray(this.layout?.slots) ? this.layout.slots : [];
      const cols = Math.max(this.safeInt(this.gridCols, 4), 1);
      return slots
        .map((worker, index) => {
          if (!worker || typeof worker !== 'object') return null;
          return {
            col: this.safeInt(worker.col, index % cols),
            row: this.safeInt(worker.row, Math.floor(index / cols)),
          };
        })
        .filter(Boolean);
    },
    placementAnchor() {
      const items = this.workerPlacementItems;
      if (!items.length) return { col: 0, row: 0 };
      if (!this.hasPlacementConflict) {
        return {
          col: Math.min(...items.map(item => item.coord.col)),
          row: Math.min(...items.map(item => item.coord.row)),
        };
      }
      if (this.placementStrategy === 'choose-anchor') {
        return {
          col: this.safeInt(this.anchorCol, 0),
          row: this.safeInt(this.anchorRow, 0),
        };
      }
      return this.autoPlacementAnchor(this.placementStrategy, items);
    },
    placementRows() {
      const items = this.workerPlacementItems;
      if (!items.length) return [];
      const sourceMinCol = Math.min(...items.map(item => item.coord.col));
      const sourceMinRow = Math.min(...items.map(item => item.coord.row));
      const anchor = this.placementAnchor;
      return items.map(item => ({
        key: item.key,
        name: item.name,
        from: item.coord,
        to: {
          col: anchor.col + (item.coord.col - sourceMinCol),
          row: anchor.row + (item.coord.row - sourceMinRow),
        },
      }));
    },
    placementFootprintBounds() {
      const targetCoords = this.placementRows.map(row => row.to);
      const coords = [...this.occupiedCoords, ...targetCoords];
      if (!coords.length) return null;
      return {
        minCol: Math.min(...coords.map(coord => coord.col)),
        maxCol: Math.max(...coords.map(coord => coord.col)),
        minRow: Math.min(...coords.map(coord => coord.row)),
        maxRow: Math.max(...coords.map(coord => coord.row)),
      };
    },
    placementFootprintCols() {
      const bounds = this.placementFootprintBounds;
      if (!bounds) return [];
      return Array.from({ length: bounds.maxCol - bounds.minCol + 1 }, (_value, index) => bounds.minCol + index);
    },
    placementFootprintRows() {
      const bounds = this.placementFootprintBounds;
      if (!bounds) return [];
      return Array.from({ length: bounds.maxRow - bounds.minRow + 1 }, (_value, index) => bounds.minRow + index);
    },
    placementFootprintStyle() {
      return {
        gridTemplateColumns: `repeat(${Math.max(this.placementFootprintCols.length, 1)}, 28px)`,
      };
    },
    placementFootprintCells() {
      const occupied = new Set(this.occupiedCoords.map(coord => `${coord.col},${coord.row}`));
      const targets = new Map(this.placementRows.map(row => [`${row.to.col},${row.to.row}`, row.name]));
      const cells = [];
      for (const row of this.placementFootprintRows) {
        for (const col of this.placementFootprintCols) {
          const key = `${col},${row}`;
          const targetName = targets.get(key);
          const isOccupied = occupied.has(key);
          cells.push({
            key,
            occupied: isOccupied,
            target: Boolean(targetName),
            label: targetName ? 'I' : (isOccupied ? 'O' : ''),
            title: `${key}${targetName ? ` target: ${targetName}` : ''}${isOccupied ? ' occupied' : ''}`,
          });
        }
      }
      return cells;
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
    safeInt(value, fallback) {
      const number = Number(value);
      return Number.isFinite(number) ? Math.trunc(number) : fallback;
    },
    coordLabel(coord) {
      return `${coord?.col ?? 0},${coord?.row ?? 0}`;
    },
    candidatePositions(items, anchor) {
      if (!items.length) return [];
      const sourceMinCol = Math.min(...items.map(item => item.coord.col));
      const sourceMinRow = Math.min(...items.map(item => item.coord.row));
      return items.map(item => ({
        col: anchor.col + (item.coord.col - sourceMinCol),
        row: anchor.row + (item.coord.row - sourceMinRow),
      }));
    },
    positionsAvailable(positions) {
      const seen = new Set();
      const occupied = new Set(this.occupiedCoords.map(coord => `${coord.col},${coord.row}`));
      for (const coord of positions) {
        if (coord.col < 0 || coord.row < 0) return false;
        const key = `${coord.col},${coord.row}`;
        if (seen.has(key) || occupied.has(key)) return false;
        seen.add(key);
      }
      return true;
    },
    autoPlacementAnchor(strategy, items) {
      const occupied = this.occupiedCoords;
      if (!occupied.length) return { col: 0, row: 0 };
      let anchor = strategy === 'place-below'
        ? {
            col: Math.min(...occupied.map(coord => coord.col)),
            row: Math.max(...occupied.map(coord => coord.row)) + 1,
          }
        : {
            col: Math.max(...occupied.map(coord => coord.col)) + 1,
            row: Math.min(...occupied.map(coord => coord.row)),
          };
      while (!this.positionsAvailable(this.candidatePositions(items, anchor))) {
        anchor = strategy === 'place-below'
          ? { col: anchor.col, row: anchor.row + 1 }
          : { col: anchor.col + 1, row: anchor.row };
      }
      return anchor;
    },
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
