const BullpenTab = {
  UNCONFIGURED_PROFILE_ID: 'unconfigured-worker',
  HEADER_WIDTH: 40,
  HEADER_HEIGHT: 24,
  props: ['layout', 'config', 'profiles', 'tasks', 'workspace', 'multipleWorkspaces'],
  emits: ['add-worker', 'configure-worker', 'select-task', 'open-focus', 'transfer-worker'],
  components: { WorkerCard },
  data() {
    return {
      showLibrary: false,
      selectedAddCoord: null,
      hoveredCoord: null,
      selectedCell: null,
      emptyMenuCoord: null,
      emptyMenuPos: null,
      clipboardWorker: null,
      viewportOrigin: { col: 0, row: 0 },
      viewportPx: { width: 0, height: 0 },
      dragStart: null,
      isPanning: false,
      minimapCollapsed: false,
      liveMessage: '',
      columnResize: null,
      draggingColumnWidth: null,
    };
  },
  template: `
    <div class="bullpen-grid-container">
      <Teleport to="#worker-tab-toolbar-slot">
        <div class="worker-layout-buttons" aria-label="Worker card layout">
          <button v-for="mode in ['small', 'medium', 'large']"
                  :key="mode"
                  class="btn btn-sm worker-layout-btn"
                  :class="{ active: layoutMode === mode }"
                  :title="'Use ' + mode + ' worker cards'"
                  @click="setLayoutMode(mode)">
            {{ mode.charAt(0).toUpperCase() }}
          </button>
        </div>
        <label class="worker-width-control">
          <span>Width</span>
          <input type="number" min="140" max="480" step="20" :value="columnWidth" @change="onWidthChange">
          <span>px</span>
        </label>
        <button class="btn btn-sm" @click="jumpHome">Home</button>
        <button class="btn btn-sm" @click="fitOccupied">Fit</button>
      </Teleport>

      <div class="worker-grid-viewport"
           ref="viewport"
           tabindex="0"
           role="grid"
           :aria-label="'Worker grid at column ' + Math.floor(viewportOrigin.col) + ', row ' + Math.floor(viewportOrigin.row)"
           @wheel="onWheel"
           @mousemove="onViewportMouseMove"
           @mouseleave="hoveredCoord = null"
           @pointerdown="onViewportPointerDown"
           @pointermove="onViewportPointerMove"
           @pointerup="onViewportPointerUp"
           @pointercancel="onViewportPointerUp"
           @keydown="onKeydown">
        <div class="worker-grid-corner" :style="cornerStyle"></div>
        <div class="worker-grid-column-headers" :style="columnHeaderAreaStyle" @pointerdown.stop>
          <div v-for="c in visibleColumns" :key="c.col"
               class="worker-grid-column-header"
               :class="{ 'is-origin': c.col === 0 }"
               :style="{ left: c.x + 'px', width: columnWidth + 'px' }">
            <span class="worker-grid-header-label">{{ c.label }}</span>
            <div class="worker-grid-column-resize"
                 :class="{ active: columnResize }"
                 title="Drag to resize columns"
                 @pointerdown="onColumnResizeDown"
                 @pointermove="onColumnResizeMove"
                 @pointerup="onColumnResizeUp"
                 @pointercancel="onColumnResizeUp"
                 @click.stop
                 @dblclick.stop="resetColumnWidth"></div>
          </div>
        </div>
        <div class="worker-grid-row-headers" :style="rowHeaderAreaStyle" @pointerdown.stop>
          <div v-for="r in visibleRows" :key="r.row"
               class="worker-grid-row-header"
               :class="{ 'is-origin': r.row === 0 }"
               :style="{ top: r.y + 'px', height: rowHeight + 'px' }">
            <span class="worker-grid-header-label">{{ r.label }}</span>
          </div>
        </div>
        <div class="worker-grid-canvas" :style="canvasStyle"
             @dragover="onCanvasDragOver"
             @drop.prevent="onCanvasDrop">
          <WorkerCard
            v-for="item in visibleWorkers"
            :key="item.slotIndex"
            :ref="el => setWorkerRef(el, item.slotIndex)"
            :style="cardStyle(item)"
            :class="{ selected: isSelected(item.coord) }"
            :worker="item.worker"
            :slot-index="item.slotIndex"
            :tasks="tasks"
            :output-lines="$root.outputBuffers?.[item.slotIndex] || []"
            :multiple-workspaces="multipleWorkspaces"
            :neighbor-slots="neighborSlotsMap[item.slotIndex]"
            :layout-mode="layoutMode"
            :aria-rowindex="ariaRowIndex(item.coord)"
            :aria-colindex="ariaColIndex(item.coord)"
            :aria-label="'Worker ' + item.worker.name + ' at column ' + item.coord.col + ', row ' + item.coord.row"
            @click.capture="onWorkerClick($event, item)"
            @configure="$emit('configure-worker', $event)"
            @select-task="$emit('select-task', $event)"
            @open-focus="$emit('open-focus', $event)"
            @transfer="$emit('transfer-worker', $event)"
            @copy-worker="copyWorker"
          />

          <div v-if="ghostCell"
               class="grid-slot empty-slot worker-grid-ghost-cell"
               :class="{ selected: isSelected(ghostCell) }"
               :style="ghostStyle"
               role="gridcell"
               tabindex="-1"
               :aria-rowindex="ariaRowIndex(ghostCell)"
               :aria-colindex="ariaColIndex(ghostCell)"
               :aria-label="'Empty cell at column ' + ghostCell.col + ', row ' + ghostCell.row"
               @click.stop="openEmptyMenu(ghostCell, $event)"
               @dragover.prevent
               @drop.stop.prevent="onDropOnEmpty($event, ghostCell)">
            <button class="empty-slot-menu-btn" title="Empty cell actions" @click.stop="openEmptyMenu(ghostCell, $event)">&hellip;</button>
          </div>
          <div v-if="ghostCell && emptyMenuOpenFor(ghostCell)"
               class="worker-menu empty-slot-menu"
               :style="emptyMenuStyle"
               @click.stop>
            <button class="worker-menu-item" @click="openLibraryForCoord(ghostCell)">Add Worker</button>
            <button class="worker-menu-item" :disabled="!canPasteAt(ghostCell)" @click="pasteWorker(ghostCell)">Paste Worker</button>
          </div>
        </div>

        <div class="worker-minimap" :class="{ collapsed: minimapCollapsed }">
          <button class="worker-minimap-toggle" @click="minimapCollapsed = !minimapCollapsed" title="Toggle minimap">▣</button>
          <template v-if="!minimapCollapsed">
            <div class="worker-minimap-map" ref="minimap" @click="onMinimapClick">
              <div v-for="dot in minimapDots" :key="dot.key" class="worker-minimap-dot" :class="'status-' + dot.state" :style="dot.style"></div>
              <div class="worker-minimap-viewport" :style="minimapViewportStyle"></div>
            </div>
            <div class="worker-minimap-arrows" aria-label="Pan worker grid">
              <button @click="nudge(0, -1)" title="Pan up">↑</button>
              <button @click="nudge(-1, 0)" title="Pan left">←</button>
              <button @click="nudge(1, 0)" title="Pan right">→</button>
              <button @click="nudge(0, 1)" title="Pan down">↓</button>
            </div>
          </template>
        </div>

        <div class="sr-only" aria-live="polite">{{ liveMessage }}</div>
      </div>

      <div
        v-if="showLibrary"
        class="modal-overlay"
        @click.self="closeLibrary"
        @keydown.escape="closeLibrary"
        tabindex="0"
        ref="libraryOverlay"
      >
        <div class="modal">
          <div class="modal-header">
            <h2>Add Worker</h2>
            <button class="btn btn-icon" @click="closeLibrary">&times;</button>
          </div>
          <div class="modal-body profile-library">
            <div v-for="p in sortedProfiles" :key="p.id"
                 class="profile-item"
                 @click="addFromLibrary(p.id)">
              <span class="profile-name">{{ p.name }}</span>
              <span class="profile-agent">{{ p.default_agent }}/{{ p.default_model }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  computed: {
    gridConfig() { return this.config?.grid || {}; },
    legacyCols() {
      const n = Number(this.gridConfig.cols);
      return Number.isFinite(n) && n > 0 ? Math.floor(n) : 4;
    },
    layoutMode() {
      return ['small', 'medium', 'large'].includes(this.gridConfig.layout) ? this.gridConfig.layout : 'medium';
    },
    columnWidth() {
      if (this.draggingColumnWidth !== null) {
        return Math.max(140, Math.min(480, Math.round(this.draggingColumnWidth)));
      }
      const raw = Number(this.gridConfig.columnWidth);
      const n = Number.isFinite(raw) ? raw : 220;
      return Math.max(140, Math.min(480, Math.round(n / 20) * 20));
    },
    headerWidth() { return this.$options.HEADER_WIDTH; },
    headerHeight() { return this.$options.HEADER_HEIGHT; },
    rowHeight() {
      return { small: 32, medium: 140, large: 280 }[this.layoutMode] || 140;
    },
    cardSize() {
      return { width: this.columnWidth, height: this.rowHeight };
    },
    workerItems() {
      const slots = this.layout?.slots || [];
      return slots.map((worker, slotIndex) => {
        if (!worker) return null;
        return { worker, slotIndex, coord: this.coordForSlot(worker, slotIndex) };
      }).filter(Boolean);
    },
    occupiedMap() {
      const map = {};
      for (const item of this.workerItems) map[GridGeometry.coordKey(item.coord.col, item.coord.row)] = item;
      return map;
    },
    visibleRange() {
      const range = GridGeometry.visibleRange(this.viewportOrigin, this.viewportPx, this.cardSize);
      return GridGeometry.overscanRange(range, 2);
    },
    visibleWorkers() {
      const r = this.visibleRange;
      return this.workerItems.filter(item =>
        item.coord.col >= r.colStart && item.coord.col <= r.colEnd &&
        item.coord.row >= r.rowStart && item.coord.row <= r.rowEnd
      );
    },
    canvasStyle() {
      const x = -((this.viewportOrigin.col % 1) * this.columnWidth);
      const y = -((this.viewportOrigin.row % 1) * this.rowHeight);
      return {
        '--worker-col-width': this.columnWidth + 'px',
        '--worker-row-height': this.rowHeight + 'px',
        left: this.headerWidth + 'px',
        top: this.headerHeight + 'px',
        backgroundPosition: `${x}px ${y}px`,
      };
    },
    cornerStyle() {
      return {
        width: this.headerWidth + 'px',
        height: this.headerHeight + 'px',
      };
    },
    columnHeaderAreaStyle() {
      return {
        left: this.headerWidth + 'px',
        height: this.headerHeight + 'px',
      };
    },
    rowHeaderAreaStyle() {
      return {
        top: this.headerHeight + 'px',
        width: this.headerWidth + 'px',
      };
    },
    visibleColumns() {
      const r = this.visibleRange;
      const out = [];
      for (let c = r.colStart; c <= r.colEnd; c++) {
        out.push({
          col: c,
          label: this.colLabel(c),
          x: (c - this.viewportOrigin.col) * this.columnWidth,
        });
      }
      return out;
    },
    visibleRows() {
      const r = this.visibleRange;
      const out = [];
      for (let rr = r.rowStart; rr <= r.rowEnd; rr++) {
        out.push({
          row: rr,
          label: this.rowLabel(rr),
          y: (rr - this.viewportOrigin.row) * this.rowHeight,
        });
      }
      return out;
    },
    ghostCell() {
      const coord = this.emptyMenuCoord || this.selectedCell || this.hoveredCoord;
      if (!coord || !this.isWritableCoord(coord) || this.itemAtCoord(coord)) return null;
      const r = this.visibleRange;
      if (coord.col < r.colStart || coord.col > r.colEnd || coord.row < r.rowStart || coord.row > r.rowEnd) return null;
      return coord;
    },
    ghostStyle() {
      if (!this.ghostCell) return {};
      const p = GridGeometry.coordToPixel(this.ghostCell.col, this.ghostCell.row, this.viewportOrigin, this.cardSize);
      return {
        left: p.x + 'px',
        top: p.y + 'px',
        width: this.columnWidth + 'px',
        height: this.rowHeight + 'px',
      };
    },
    emptyMenuStyle() {
      if (this.emptyMenuPos) {
        return { position: 'fixed', top: this.emptyMenuPos.y + 'px', left: this.emptyMenuPos.x + 'px' };
      }
      if (!this.ghostCell) return {};
      const p = GridGeometry.coordToPixel(this.ghostCell.col, this.ghostCell.row, this.viewportOrigin, this.cardSize);
      const rect = this.$refs.viewport?.getBoundingClientRect();
      const x = (rect?.left || 0) + this.headerWidth + p.x + this.columnWidth / 2;
      const y = (rect?.top || 0) + this.headerHeight + p.y + this.rowHeight / 2;
      return { position: 'fixed', top: y + 'px', left: x + 'px' };
    },
    sortedProfiles() {
      const pin = this.$options.UNCONFIGURED_PROFILE_ID;
      return (this.profiles || []).slice().sort((a, b) => {
        if (a?.id === pin && b?.id !== pin) return -1;
        if (b?.id === pin && a?.id !== pin) return 1;
        return (a?.name || '').localeCompare(b?.name || '');
      });
    },
    neighborSlotsMap() {
      const map = {};
      for (const item of this.workerItems) {
        const c = item.coord;
        map[item.slotIndex] = {
          up: this.itemAtCoord({ col: c.col, row: c.row - 1 })?.slotIndex ?? null,
          down: this.itemAtCoord({ col: c.col, row: c.row + 1 })?.slotIndex ?? null,
          left: this.itemAtCoord({ col: c.col - 1, row: c.row })?.slotIndex ?? null,
          right: this.itemAtCoord({ col: c.col + 1, row: c.row })?.slotIndex ?? null,
        };
      }
      return map;
    },
    occupiedBounds() {
      return GridGeometry.occupiedBounds(this.workerItems.map(item => item.coord));
    },
    minimapBounds() {
      const b = this.occupiedBounds;
      const visible = GridGeometry.visibleRange(this.viewportOrigin, this.viewportPx, this.cardSize);
      const colMin = Math.min(b?.colMin ?? 0, visible.colStart) - 2;
      const colMax = Math.max(b?.colMax ?? 3, visible.colEnd) + 2;
      const rowMin = Math.min(b?.rowMin ?? 0, visible.rowStart) - 2;
      const rowMax = Math.max(b?.rowMax ?? 4, visible.rowEnd) + 2;
      return { colMin, colMax, rowMin, rowMax };
    },
    minimapScale() {
      const b = this.minimapBounds;
      return Math.min(160 / Math.max(1, b.colMax - b.colMin + 1), 120 / Math.max(1, b.rowMax - b.rowMin + 1));
    },
    minimapDots() {
      const b = this.minimapBounds;
      const scale = this.minimapScale;
      return this.workerItems.map(item => ({
        key: item.slotIndex,
        state: item.worker.state || 'idle',
        style: {
          left: ((item.coord.col - b.colMin) * scale) + 'px',
          top: ((item.coord.row - b.rowMin) * scale) + 'px',
          width: Math.max(1, Math.min(3, scale)) + 'px',
          height: Math.max(1, Math.min(3, scale)) + 'px',
        },
      }));
    },
    minimapViewportStyle() {
      const b = this.minimapBounds;
      const scale = this.minimapScale;
      return {
        left: ((this.viewportOrigin.col - b.colMin) * scale) + 'px',
        top: ((this.viewportOrigin.row - b.rowMin) * scale) + 'px',
        width: Math.max(2, (this.viewportPx.width / this.columnWidth) * scale) + 'px',
        height: Math.max(2, (this.viewportPx.height / this.rowHeight) * scale) + 'px',
      };
    },
  },
  watch: {
    'config.grid.viewportOrigin': {
      immediate: true,
      deep: true,
      handler(value) {
        this.viewportOrigin = this.clampedOrigin({
          col: Number.isFinite(Number(value?.col)) ? Number(value.col) : 0,
          row: Number.isFinite(Number(value?.row)) ? Number(value.row) : 0,
        });
      },
    },
  },
  mounted() {
    this.updateViewportSize();
    this._resizeObserver = new ResizeObserver(() => this.updateViewportSize());
    if (this.$refs.viewport) this._resizeObserver.observe(this.$refs.viewport);
  },
  beforeUnmount() {
    this._resizeObserver?.disconnect();
    if (this._persistTimer) clearTimeout(this._persistTimer);
  },
  methods: {
    coordForSlot(worker, slotIndex) {
      const col = Number(worker?.col);
      const row = Number(worker?.row);
      if (Number.isFinite(col) && Number.isFinite(row)) return { col: Math.trunc(col), row: Math.trunc(row) };
      return GridGeometry.indexToCoord(slotIndex, this.legacyCols);
    },
    itemAtCoord(coord) {
      return this.occupiedMap[GridGeometry.coordKey(coord.col, coord.row)] || null;
    },
    isWritableCoord(coord) {
      const limit = GridGeometry.DEFAULT_COORD_LIMIT;
      return coord && coord.col >= -limit && coord.col <= limit && coord.row >= -limit && coord.row <= limit;
    },
    clampedOrigin(origin) {
      return GridGeometry.clampOriginToBounds(origin, this.viewportPx, this.cardSize);
    },
    updateViewportSize() {
      const el = this.$refs.viewport;
      if (!el) return;
      this.viewportPx = {
        width: Math.max(0, el.clientWidth - this.headerWidth),
        height: Math.max(0, el.clientHeight - this.headerHeight),
      };
      this.viewportOrigin = this.clampedOrigin(this.viewportOrigin);
    },
    persistGrid(partial = {}) {
      const grid = {
        ...(this.config?.grid || {}),
        layout: this.layoutMode,
        columnWidth: this.columnWidth,
        viewportOrigin: this.viewportOrigin,
        ...partial,
      };
      this.$root.updateConfig({ grid });
    },
    persistOriginSoon() {
      if (this._persistTimer) clearTimeout(this._persistTimer);
      this._persistTimer = setTimeout(() => this.persistGrid({ viewportOrigin: this.viewportOrigin }), 120);
    },
    cardStyle(item) {
      const p = GridGeometry.coordToPixel(item.coord.col, item.coord.row, this.viewportOrigin, this.cardSize);
      return {
        position: 'absolute',
        left: p.x + 'px',
        top: p.y + 'px',
        width: this.columnWidth + 'px',
        height: this.rowHeight + 'px',
      };
    },
    setLayoutMode(mode) {
      this.persistGrid({ layout: mode });
    },
    onWidthChange(e) {
      const raw = Number(e.target.value);
      const width = Math.max(140, Math.min(480, Math.round((Number.isFinite(raw) ? raw : 220) / 20) * 20));
      e.target.value = width;
      this.persistGrid({ columnWidth: width });
    },
    setOrigin(origin, persist = true) {
      this.viewportOrigin = this.clampedOrigin(origin);
      if (persist) this.persistOriginSoon();
    },
    nudge(dc, dr) {
      this.setOrigin({ col: this.viewportOrigin.col + dc, row: this.viewportOrigin.row + dr });
    },
    jumpHome() {
      this.setOrigin({ col: 0, row: 0 });
    },
    fitOccupied() {
      const b = this.occupiedBounds;
      if (!b) {
        this.jumpHome();
        return;
      }
      this.setOrigin({ col: b.colMin - 1, row: b.rowMin - 1 });
    },
    onWheel(e) {
      e.preventDefault();
      e.stopPropagation();
      const dx = e.shiftKey ? e.deltaY : e.deltaX;
      const dy = e.shiftKey ? 0 : e.deltaY;
      this.setOrigin({
        col: this.viewportOrigin.col + dx / this.columnWidth,
        row: this.viewportOrigin.row + dy / this.rowHeight,
      });
    },
    coordFromEvent(e) {
      const rect = this.$refs.viewport.getBoundingClientRect();
      const x = e.clientX - rect.left - this.headerWidth;
      const y = e.clientY - rect.top - this.headerHeight;
      return GridGeometry.pixelToCoord(x, y, this.viewportOrigin, this.cardSize);
    },
    onViewportMouseMove(e) {
      if (this.isPanning) return;
      const coord = this.coordFromEvent(e);
      this.hoveredCoord = this.itemAtCoord(coord) ? null : coord;
    },
    onViewportPointerDown(e) {
      if (e.button !== 0 && e.button !== 1) return;
      if (e.target.closest('.worker-card, .worker-menu, button, input')) return;
      this.dragStart = {
        x: e.clientX,
        y: e.clientY,
        button: e.button,
        origin: { ...this.viewportOrigin },
        coord: this.coordFromEvent(e),
      };
      this.$refs.viewport.setPointerCapture?.(e.pointerId);
    },
    onViewportPointerMove(e) {
      if (!this.dragStart) return;
      const dx = e.clientX - this.dragStart.x;
      const dy = e.clientY - this.dragStart.y;
      if (!this.isPanning && Math.hypot(dx, dy) <= 5) return;
      this.isPanning = true;
      this.setOrigin({
        col: this.dragStart.origin.col - dx / this.columnWidth,
        row: this.dragStart.origin.row - dy / this.rowHeight,
      });
    },
    onViewportPointerUp(e) {
      if (!this.dragStart) return;
      const wasPanning = this.isPanning;
      const coord = this.dragStart.coord;
      this.dragStart = null;
      this.isPanning = false;
      this.$refs.viewport.releasePointerCapture?.(e.pointerId);
      if (!wasPanning && !this.itemAtCoord(coord)) {
        this.selectedCell = null;
        this.emptyMenuCoord = null;
      }
    },
    selectWorker(item) {
      this.selectedCell = item.coord;
      this.emptyMenuCoord = null;
      this.liveMessage = `Selected worker ${item.worker.name} at column ${item.coord.col}, row ${item.coord.row}`;
    },
    onWorkerClick(e, item) {
      if (e.target.closest('.connect-handle, .status-pill, .worker-card-token-meta, .worker-menu-btn, .worker-menu, button, input, select, textarea')) {
        return;
      }
      this.selectWorker(item);
    },
    isSelected(coord) {
      return !!(this.selectedCell && coord && this.selectedCell.col === coord.col && this.selectedCell.row === coord.row);
    },
    onKeydown(e) {
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        const step = {
          ArrowUp: { dc: 0, dr: -1, dir: 'up' },
          ArrowDown: { dc: 0, dr: 1, dir: 'down' },
          ArrowLeft: { dc: -1, dr: 0, dir: 'left' },
          ArrowRight: { dc: 1, dr: 0, dir: 'right' },
        }[e.key];
        const origin = this.selectedCell || {
          col: Math.floor(this.viewportOrigin.col + (this.viewportPx.width / this.columnWidth) / 2),
          row: Math.floor(this.viewportOrigin.row + (this.viewportPx.height / this.rowHeight) / 2),
        };
        const next = { col: origin.col + step.dc, row: origin.row + step.dr };
        if (!this.isWritableCoord(next)) {
          this.flashBoundary(step.dir);
          return;
        }
        e.preventDefault();
        const item = this.itemAtCoord(next);
        if (item) {
          this.selectWorker(item);
        } else {
          this.selectedCell = next;
          this.emptyMenuCoord = null;
          this.emptyMenuPos = null;
          this.liveMessage = `Empty cell at column ${next.col}, row ${next.row}`;
        }
        this.ensureCoordVisible(next);
        return;
      }
      if (e.key === 'Home') {
        e.preventDefault();
        this.jumpHome();
      } else if (e.key.toLowerCase() === 'f') {
        e.preventDefault();
        this.fitOccupied();
      } else if (e.key === 'Escape') {
        if (this.emptyMenuCoord) this.emptyMenuCoord = null;
        else this.selectedCell = null;
      } else if (e.key === 'Enter' && this.selectedCell) {
        const item = this.itemAtCoord(this.selectedCell);
        if (item) {
          e.preventDefault();
          const card = this.workerRefs && this.workerRefs[item.slotIndex];
          if (card && typeof card.openMenuAndFocus === 'function') {
            card.openMenuAndFocus();
          }
        } else {
          e.preventDefault();
          this.openEmptyMenu(this.selectedCell);
        }
      }
    },
    setWorkerRef(el, slotIndex) {
      if (!this.workerRefs) this.workerRefs = {};
      if (el) {
        this.workerRefs[slotIndex] = el;
      } else {
        delete this.workerRefs[slotIndex];
      }
    },
    ensureCoordVisible(coord) {
      let col = this.viewportOrigin.col;
      let row = this.viewportOrigin.row;
      const visibleCols = this.viewportPx.width / this.columnWidth;
      const visibleRows = this.viewportPx.height / this.rowHeight;
      if (coord.col < col) col = coord.col;
      if (coord.row < row) row = coord.row;
      if (coord.col + 1 > col + visibleCols) col = coord.col + 1 - visibleCols;
      if (coord.row + 1 > row + visibleRows) row = coord.row + 1 - visibleRows;
      this.setOrigin({ col, row });
    },
    flashBoundary(dir) {
      const el = this.$refs.viewport;
      if (!el) return;
      el.classList.remove('boundary-up', 'boundary-down', 'boundary-left', 'boundary-right');
      void el.offsetWidth;
      el.classList.add('boundary-' + dir);
      setTimeout(() => el.classList.remove('boundary-' + dir), 260);
    },
    ariaRowIndex(coord) {
      return Math.max(1, Math.floor(coord.row - this.visibleRange.rowStart + 1));
    },
    ariaColIndex(coord) {
      return Math.max(1, Math.floor(coord.col - this.visibleRange.colStart + 1));
    },
    openEmptyMenu(coord, e) {
      if (!this.isWritableCoord(coord) || this.itemAtCoord(coord)) return;
      this.selectedCell = { ...coord };
      this.emptyMenuCoord = { ...coord };
      if (e && Number.isFinite(e.clientX) && Number.isFinite(e.clientY)) {
        this.emptyMenuPos = { x: e.clientX, y: e.clientY };
      } else {
        this.emptyMenuPos = null;
      }
      this.liveMessage = `Empty cell at column ${coord.col}, row ${coord.row}`;
    },
    emptyMenuOpenFor(coord) {
      return !!(this.emptyMenuCoord && coord && this.emptyMenuCoord.col === coord.col && this.emptyMenuCoord.row === coord.row);
    },
    openLibraryForCoord(coord) {
      this.selectedAddCoord = { ...coord };
      this.showLibrary = true;
      this.emptyMenuCoord = null;
      this.$nextTick(() => this.$refs.libraryOverlay?.focus());
    },
    closeLibrary() {
      this.showLibrary = false;
      this.selectedAddCoord = null;
    },
    addFromLibrary(profileId) {
      this.$emit('add-worker', { coord: this.selectedAddCoord, profile: profileId });
      this.closeLibrary();
    },
    copyWorker(slot) {
      const worker = this.layout?.slots?.[slot];
      if (!worker) return;
      const fields = ['profile', 'name', 'agent', 'model', 'activation', 'disposition', 'watch_column', 'expertise_prompt',
        'max_retries', 'use_worktree', 'auto_commit', 'auto_pr', 'trigger_time', 'trigger_interval_minutes',
        'trigger_every_day', 'icon', 'color', 'avatar'];
      const copy = {};
      for (const key of fields) {
        if (worker[key] !== undefined) copy[key] = worker[key];
      }
      this.clipboardWorker = copy;
      this.liveMessage = `Copied worker ${worker.name}`;
    },
    canPasteAt(coord) {
      return !!(this.clipboardWorker && coord && !this.itemAtCoord(coord) && this.isWritableCoord(coord));
    },
    pasteWorker(coord) {
      if (!this.canPasteAt(coord)) return;
      this.$root.pasteWorkerConfig({ coord, worker: this.clipboardWorker });
      this.emptyMenuCoord = null;
    },
    onDropOnEmpty(e, coord) {
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      if (fromSlot !== '') {
        this.$root.moveWorker(Number(fromSlot), coord);
      }
    },
    onCanvasDragOver(e) {
      if (!e.dataTransfer.types.includes('application/x-worker-slot')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const coord = this.coordFromEvent(e);
      if (coord && this.isWritableCoord(coord) && !this.itemAtCoord(coord)) {
        this.hoveredCoord = coord;
      } else {
        this.hoveredCoord = null;
      }
    },
    onCanvasDrop(e) {
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      if (fromSlot === '') return;
      const src = Number(fromSlot);
      const coord = this.coordFromEvent(e);
      this.hoveredCoord = null;
      if (!coord || !this.isWritableCoord(coord)) return;
      const existing = this.itemAtCoord(coord);
      if (existing) {
        if (existing.slotIndex === src) return;
        this.$root.moveWorker(src, existing.slotIndex);
        return;
      }
      this.$root.moveWorker(src, coord);
    },
    colLabel(col) {
      if (!Number.isFinite(col)) return '';
      if (col < 0) return '-' + this.colLabel(-col - 1);
      let s = '';
      let n = Math.floor(col);
      while (true) {
        s = String.fromCharCode(65 + (n % 26)) + s;
        n = Math.floor(n / 26) - 1;
        if (n < 0) break;
      }
      return s;
    },
    rowLabel(row) {
      if (!Number.isFinite(row)) return '';
      return String(Math.floor(row) + 1);
    },
    onColumnResizeDown(e) {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      e.currentTarget.setPointerCapture?.(e.pointerId);
      this.columnResize = {
        startX: e.clientX,
        startWidth: this.columnWidth,
        pointerId: e.pointerId,
      };
      this.draggingColumnWidth = this.columnWidth;
    },
    onColumnResizeMove(e) {
      if (!this.columnResize) return;
      const dx = e.clientX - this.columnResize.startX;
      const next = this.columnResize.startWidth + dx;
      this.draggingColumnWidth = Math.max(140, Math.min(480, Math.round(next)));
    },
    onColumnResizeUp(e) {
      if (!this.columnResize) return;
      e.currentTarget.releasePointerCapture?.(this.columnResize.pointerId);
      const dragged = this.draggingColumnWidth;
      this.columnResize = null;
      this.draggingColumnWidth = null;
      if (dragged != null) {
        const final = Math.max(140, Math.min(480, Math.round(dragged / 20) * 20));
        this.persistGrid({ columnWidth: final });
      }
    },
    resetColumnWidth() {
      this.columnResize = null;
      this.draggingColumnWidth = null;
      this.persistGrid({ columnWidth: 220 });
    },
    onMinimapClick(e) {
      const rect = e.currentTarget.getBoundingClientRect();
      const b = this.minimapBounds;
      const scale = this.minimapScale;
      const col = b.colMin + (e.clientX - rect.left) / scale;
      const row = b.rowMin + (e.clientY - rect.top) / scale;
      this.setOrigin({
        col: col - (this.viewportPx.width / this.columnWidth) / 2,
        row: row - (this.viewportPx.height / this.rowHeight) / 2,
      });
    },
  }
};
