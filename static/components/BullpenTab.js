const BullpenTab = {
  UNCONFIGURED_PROFILE_ID: 'unconfigured-worker',
  HEADER_WIDTH: 40,
  HEADER_HEIGHT: 24,
  MINIMAP_HEADER_PX: 30,
  props: ['layout', 'config', 'profiles', 'tasks', 'workspace', 'multipleWorkspaces'],
  emits: ['add-worker', 'configure-worker', 'select-task', 'open-focus', 'transfer-worker'],
  components: { WorkerCard },
  data() {
    return {
      showLibrary: false,
      selectedAddCoord: null,
      hoveredCoord: null,
      selectedCell: null,
      dragOverCoord: null,
      dropTargetCoords: [],
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
      rowResize: null,
      draggingRowHeight: null,
      resizeTooltip: null,
    };
  },
  template: `
    <div class="bullpen-grid-container">
      <Teleport to="#worker-tab-toolbar-slot">
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
               :class="{
                 'is-origin': c.col === 0,
                 'is-selected': selectedCell && c.col === selectedCell.col,
               }"
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
               :class="{
                 'is-origin': r.row === 0,
                 'is-selected': selectedCell && r.row === selectedCell.row,
               }"
               :style="{ top: r.y + 'px', height: rowHeight + 'px' }">
            <span class="worker-grid-header-label">{{ r.label }}</span>
            <div class="worker-grid-row-resize"
                 :class="{ active: rowResize }"
                 title="Drag to resize rows"
                 @pointerdown="onRowResizeDown"
                 @pointermove="onRowResizeMove"
                 @pointerup="onRowResizeUp"
                 @pointercancel="onRowResizeUp"
                 @click.stop
                 @dblclick.stop="resetRowHeight"></div>
          </div>
        </div>
        <div class="worker-grid-canvas" :style="canvasStyle"
             @dragover="onCanvasDragOver"
             @dragleave="onCanvasDragLeave"
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
            :build-worker-drag-payload="buildWorkerDragPayload"
            :build-worker-drag-image="buildWorkerDragImage"
            :can-drop-worker-at-slot="canDropWorkerAtSlot"
            :drop-worker-on-slot="dropWorkerOnSlot"
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

          <div v-for="cell in visibleDropTargetOverlays"
               :key="'drop-' + cell.col + '-' + cell.row"
               class="worker-grid-drop-target-overlay"
               :style="cell.style"
               aria-hidden="true"></div>

          <div v-if="ghostCell"
               class="grid-slot empty-slot worker-grid-ghost-cell"
               :class="{ selected: isSelected(ghostCell), 'drag-over': isDragOverGhost(ghostCell) }"
               :style="ghostStyle"
               role="gridcell"
               tabindex="-1"
               :aria-rowindex="ariaRowIndex(ghostCell)"
               :aria-colindex="ariaColIndex(ghostCell)"
               :aria-label="'Empty cell at column ' + ghostCell.col + ', row ' + ghostCell.row"
               @click.stop="openEmptyMenu(ghostCell, $event)"
               @dragover="onEmptyDragOver($event, ghostCell)"
               @drop.stop.prevent="onDropOnEmpty($event, ghostCell)">
            <button class="empty-slot-menu-btn" title="Empty cell actions" @click.stop="openEmptyMenu(ghostCell, $event)">&hellip;</button>
          </div>
          <div v-if="ghostCell && emptyMenuOpenFor(ghostCell)"
               class="worker-menu empty-slot-menu"
               :style="emptyMenuStyle"
               ref="emptyMenu"
               tabindex="-1"
               @keydown="onEmptyMenuKeydown"
               @click.stop>
            <button class="worker-menu-item" @click="openLibraryForCoord(ghostCell)"><i class="menu-item-icon" data-lucide="user-plus" aria-hidden="true"></i><span class="menu-item-label">Add Worker</span></button>
            <button class="worker-menu-item" :disabled="!canPasteAt(ghostCell)" @click="pasteWorker(ghostCell)"><i class="menu-item-icon" data-lucide="clipboard" aria-hidden="true"></i><span class="menu-item-label">Paste Worker</span></button>
          </div>
        </div>

        <div class="worker-minimap" :class="{ collapsed: minimapCollapsed }">
          <button class="worker-minimap-toggle" @click="minimapCollapsed = !minimapCollapsed" title="Toggle minimap">▣</button>
          <template v-if="!minimapCollapsed">
            <div class="worker-minimap-map" ref="minimap" @click="onMinimapClick">
              <div v-for="dot in minimapDots" :key="dot.key" class="worker-minimap-dot" :style="dot.style"></div>
              <div class="worker-minimap-viewport" :style="minimapViewportStyle"></div>
            </div>
            <div class="worker-minimap-arrows" aria-label="Pan worker grid">
              <button class="minimap-arrow minimap-arrow-up" @click="nudge(0, -1)" title="Pan up">↑</button>
              <button class="minimap-arrow minimap-arrow-left" @click="nudge(-1, 0)" title="Pan left">←</button>
              <button class="minimap-arrow minimap-arrow-right" @click="nudge(1, 0)" title="Pan right">→</button>
              <button class="minimap-arrow minimap-arrow-down" @click="nudge(0, 1)" title="Pan down">↓</button>
            </div>
          </template>
        </div>

        <div class="sr-only" aria-live="polite">{{ liveMessage }}</div>
      </div>

      <div v-if="resizeTooltip"
           class="worker-grid-resize-tooltip"
           :style="{ left: resizeTooltip.x + 'px', top: resizeTooltip.y + 'px' }">
        {{ resizeTooltip.text }}
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
      return this.rowHeight < 80 ? 'small' : 'medium';
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
      if (this.draggingRowHeight !== null) {
        return Math.max(32, Math.min(480, Math.round(this.draggingRowHeight)));
      }
      const raw = Number(this.gridConfig.rowHeight);
      if (Number.isFinite(raw)) {
        return Math.max(32, Math.min(480, Math.round(raw)));
      }
      return 140;
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
    workerItemBySlot() {
      const map = {};
      for (const item of this.workerItems) map[item.slotIndex] = item;
      return map;
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
      for (let c = Math.max(0, r.colStart); c <= r.colEnd; c++) {
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
      for (let rr = Math.max(0, r.rowStart); rr <= r.rowEnd; rr++) {
        out.push({
          row: rr,
          label: this.rowLabel(rr),
          y: (rr - this.viewportOrigin.row) * this.rowHeight,
        });
      }
      return out;
    },
    ghostCell() {
      const coord = this.dragOverCoord || this.emptyMenuCoord || this.selectedCell || this.hoveredCoord;
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
    visibleDropTargetOverlays() {
      const coords = this.dropTargetCoords;
      if (!coords || !coords.length) return [];
      const r = this.visibleRange;
      const out = [];
      for (const c of coords) {
        if (!c) continue;
        if (c.col < r.colStart || c.col > r.colEnd || c.row < r.rowStart || c.row > r.rowEnd) continue;
        const p = GridGeometry.coordToPixel(c.col, c.row, this.viewportOrigin, this.cardSize);
        out.push({
          col: c.col,
          row: c.row,
          style: {
            left: p.x + 'px',
            top: p.y + 'px',
            width: this.columnWidth + 'px',
            height: this.rowHeight + 'px',
          },
        });
      }
      return out;
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
      const colMin = Math.max(0, Math.min(b?.colMin ?? 0, visible.colStart) - 2);
      const colMax = Math.max(b?.colMax ?? 3, visible.colEnd) + 2;
      const rowMin = Math.max(0, Math.min(b?.rowMin ?? 0, visible.rowStart) - 2);
      const rowMax = Math.max(b?.rowMax ?? 4, visible.rowEnd) + 2;
      return { colMin, colMax, rowMin, rowMax };
    },
    minimapScale() {
      const b = this.minimapBounds;
      const cols = Math.max(1, b.colMax - b.colMin + 1);
      const rows = Math.max(1, b.rowMax - b.rowMin + 1);
      const headerFrac = this.$options.MINIMAP_HEADER_PX / Math.max(1, this.columnWidth);
      const scaleX = Math.min(160 / cols, 120 / (rows * headerFrac));
      const scaleY = scaleX * headerFrac;
      return { x: scaleX, y: scaleY };
    },
    minimapDots() {
      const b = this.minimapBounds;
      const scale = this.minimapScale;
      const dotSize = Math.max(1, Math.min(3, scale.x)) + 'px';
      return this.workerItems.map(item => ({
        key: item.slotIndex,
        style: {
          left: ((item.coord.col - b.colMin) * scale.x) + 'px',
          top: ((item.coord.row - b.rowMin) * scale.y) + 'px',
          width: dotSize,
          height: dotSize,
          background: agentColor(item.worker?.agent),
        },
      }));
    },
    minimapViewportStyle() {
      const b = this.minimapBounds;
      const scale = this.minimapScale;
      return {
        left: ((this.viewportOrigin.col - b.colMin) * scale.x) + 'px',
        top: ((this.viewportOrigin.row - b.rowMin) * scale.y) + 'px',
        width: Math.max(2, (this.viewportPx.width / this.columnWidth) * scale.x) + 'px',
        height: Math.max(2, (this.viewportPx.height / this.rowHeight) * scale.y) + 'px',
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
    workspace: {
      handler() {
        this.selectA1();
      },
    },
  },
  mounted() {
    this.updateViewportSize();
    this._resizeObserver = new ResizeObserver(() => this.updateViewportSize());
    if (this.$refs.viewport) this._resizeObserver.observe(this.$refs.viewport);
    this.selectA1();
    renderLucideIcons(this.$el);
  },
  updated() {
    renderLucideIcons(this.$el);
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
      return coord && coord.col >= 0 && coord.col <= limit && coord.row >= 0 && coord.row <= limit;
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
        columnWidth: this.columnWidth,
        rowHeight: this.rowHeight,
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
      if (!wasPanning && !this.itemAtCoord(coord) && this.isWritableCoord(coord)) {
        this.selectedCell = { ...coord };
        this.emptyMenuCoord = null;
        this.emptyMenuPos = null;
        this.liveMessage = `Empty cell at column ${coord.col}, row ${coord.row}`;
      }
    },
    selectWorker(item) {
      this.selectedCell = item.coord;
      this.emptyMenuCoord = null;
      this.liveMessage = `Selected worker ${item.worker.name} at column ${item.coord.col}, row ${item.coord.row}`;
    },
    selectA1() {
      this.selectedCell = { col: 0, row: 0 };
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      this.$nextTick(() => this.$refs.viewport?.focus());
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
    isDragOverGhost(coord) {
      return !!(this.dragOverCoord && coord &&
        this.dragOverCoord.col === coord.col &&
        this.dragOverCoord.row === coord.row);
    },
    onKeydown(e) {
      const t = e.target;
      const inTextInput = t && (t.isContentEditable || (typeof t.matches === 'function' && t.matches('input, textarea, select')));
      if (this.emptyMenuCoord && !inTextInput && !e.metaKey && !e.ctrlKey && !e.altKey) {
        if (['ArrowUp', 'ArrowDown', 'Home', 'End', 'Escape'].includes(e.key)) {
          this.onEmptyMenuKeydown(e);
          return;
        }
      }
      if (!inTextInput && (e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'c') {
        if (!this.selectedCell) return;
        const item = this.itemAtCoord(this.selectedCell);
        if (!item) return;
        e.preventDefault();
        this.copyWorker(item.slotIndex);
        return;
      }
      if (!inTextInput && (e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'v') {
        if (!this.selectedCell || !this.clipboardWorker || !this.isWritableCoord(this.selectedCell)) return;
        e.preventDefault();
        this.pasteWorker(this.selectedCell, { allowReplaceSingle: true });
        return;
      }
      if (!inTextInput && !e.metaKey && !e.ctrlKey && (e.key === 'Delete' || e.key === 'Backspace')) {
        if (!this.selectedCell) return;
        const item = this.itemAtCoord(this.selectedCell);
        if (!item) return;
        e.preventDefault();
        this.$root.removeWorker(item.slotIndex);
        return;
      }
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
        if (this.emptyMenuCoord) {
          e.preventDefault();
          this.closeEmptyMenu({ focusViewport: true });
        }
      } else if (e.key === 'Enter') {
        const coord = this.selectedCell || this.ghostCell;
        if (!coord) return;
        const item = this.itemAtCoord(coord);
        if (item) {
          e.preventDefault();
          const card = this.workerRefs && this.workerRefs[item.slotIndex];
          if (card && typeof card.openMenuAndFocus === 'function') {
            card.openMenuAndFocus();
          }
        } else {
          e.preventDefault();
          this.openEmptyMenu(coord);
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
    emptyMenuItems() {
      const menu = this.$refs.emptyMenu;
      if (!menu || typeof menu.querySelectorAll !== 'function') return [];
      return Array.from(menu.querySelectorAll('.worker-menu-item:not([disabled])'));
    },
    closeEmptyMenu(options = {}) {
      const focusViewport = options && options.focusViewport === true;
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      if (focusViewport) {
        this.$nextTick(() => this.$refs.viewport?.focus());
      }
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
      this.$nextTick(() => {
        const menu = this.$refs.emptyMenu;
        if (menu && typeof menu.focus === 'function') menu.focus();
        const [first] = this.emptyMenuItems();
        if (first && typeof first.focus === 'function') first.focus();
      });
    },
    onEmptyMenuKeydown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.closeEmptyMenu({ focusViewport: true });
        return;
      }
      const items = this.emptyMenuItems();
      if (!items.length) return;
      const currentIdx = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        items[(currentIdx + 1) % items.length].focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        items[currentIdx <= 0 ? items.length - 1 : currentIdx - 1].focus();
      } else if (e.key === 'Home') {
        e.preventDefault();
        e.stopPropagation();
        items[0].focus();
      } else if (e.key === 'End') {
        e.preventDefault();
        e.stopPropagation();
        items[items.length - 1].focus();
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.stopPropagation();
      }
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
    workerFieldsForClipboard(worker) {
      const fields = ['profile', 'name', 'agent', 'model', 'activation', 'disposition', 'watch_column', 'expertise_prompt',
        'max_retries', 'use_worktree', 'auto_commit', 'auto_pr', 'trigger_time', 'trigger_interval_minutes',
        'trigger_every_day', 'icon', 'color', 'avatar'];
      const copy = {};
      for (const key of fields) {
        if (worker[key] !== undefined) copy[key] = worker[key];
      }
      return copy;
    },
    passTargetsForSlot(slotIndex) {
      const item = this.workerItemBySlot[slotIndex];
      if (!item) return [];
      const disposition = String(item.worker?.disposition || '');
      if (!disposition.startsWith('pass:')) return [];
      const passDir = disposition.slice(5);
      const neighbors = this.neighborSlotsMap[slotIndex] || {};
      if (['up', 'down', 'left', 'right'].includes(passDir)) {
        const target = neighbors[passDir];
        return Number.isInteger(target) ? [target] : [];
      }
      if (passDir === 'random') {
        const out = [];
        for (const dir of ['up', 'down', 'left', 'right']) {
          const target = neighbors[dir];
          if (Number.isInteger(target) && !out.includes(target)) out.push(target);
        }
        return out;
      }
      return [];
    },
    passSourcesForSlot(slotIndex) {
      const target = Number(slotIndex);
      if (!Number.isInteger(target) || !this.workerItemBySlot[target]) return [];
      const sources = [];
      for (const item of this.workerItems) {
        if (this.passTargetsForSlot(item.slotIndex).includes(target)) {
          sources.push(item.slotIndex);
        }
      }
      return sources;
    },
    workerGroupSlots(startSlot) {
      const root = Number(startSlot);
      if (!Number.isInteger(root) || !this.workerItemBySlot[root]) return [];
      const visited = new Set();
      const stack = [root];
      const group = [];
      while (stack.length) {
        const slot = stack.pop();
        if (visited.has(slot)) continue;
        if (!this.workerItemBySlot[slot]) continue;
        visited.add(slot);
        group.push(slot);
        const neighbors = new Set([...this.passTargetsForSlot(slot), ...this.passSourcesForSlot(slot)]);
        for (const next of neighbors) {
          if (!visited.has(next)) stack.push(next);
        }
      }
      return group;
    },
    buildWorkerDragPayload(slotIndex) {
      const source = Number(slotIndex);
      const group = this.workerGroupSlots(source);
      return { source, group: group.length ? group : [source] };
    },
    buildWorkerDragImage(slotIndex, pointer = {}) {
      const source = Number(slotIndex);
      const sourceItem = this.workerItemBySlot[source];
      if (!sourceItem) return null;
      const slots = this.workerGroupSlots(source);
      if (!slots.length) return null;
      const items = slots.map(slot => this.workerItemBySlot[slot]).filter(Boolean);
      if (!items.length) return null;
      const cols = items.map(item => item.coord.col);
      const rows = items.map(item => item.coord.row);
      const minCol = Math.min(...cols);
      const maxCol = Math.max(...cols);
      const minRow = Math.min(...rows);
      const maxRow = Math.max(...rows);
      const width = (maxCol - minCol + 1) * this.columnWidth;
      const height = (maxRow - minRow + 1) * this.rowHeight;
      const root = document.createElement('div');
      root.className = 'worker-group-drag-image';
      root.style.width = `${width}px`;
      root.style.height = `${height}px`;
      const sourceDx = (sourceItem.coord.col - minCol) * this.columnWidth;
      const sourceDy = (sourceItem.coord.row - minRow) * this.rowHeight;
      for (const item of items) {
        const slot = item.slotIndex;
        const left = (item.coord.col - minCol) * this.columnWidth;
        const top = (item.coord.row - minRow) * this.rowHeight;
        const cardEl = this.workerElementForSlot(slot);
        const node = cardEl ? cardEl.cloneNode(true) : document.createElement('div');
        if (!cardEl) {
          node.className = 'worker-card worker-card-drag-placeholder';
          node.textContent = item.worker?.name || `Slot ${slot + 1}`;
        }
        node.classList.add('worker-card-drag-clone');
        node.style.position = 'absolute';
        node.style.left = `${left}px`;
        node.style.top = `${top}px`;
        node.style.width = `${this.columnWidth}px`;
        node.style.height = `${this.rowHeight}px`;
        node.style.margin = '0';
        root.appendChild(node);
      }
      document.body.appendChild(root);
      const sourceEl = this.workerElementForSlot(source);
      let pointerDx = this.columnWidth / 2;
      let pointerDy = this.rowHeight / 2;
      if (sourceEl && Number.isFinite(Number(pointer.clientX)) && Number.isFinite(Number(pointer.clientY))) {
        const rect = sourceEl.getBoundingClientRect();
        pointerDx = Math.max(0, Math.min(rect.width, Number(pointer.clientX) - rect.left));
        pointerDy = Math.max(0, Math.min(rect.height, Number(pointer.clientY) - rect.top));
      }
      return {
        element: root,
        offsetX: sourceDx + pointerDx,
        offsetY: sourceDy + pointerDy,
      };
    },
    workerElementForSlot(slotIndex) {
      const ref = this.workerRefs?.[slotIndex];
      if (!ref) return null;
      if (ref.$el) return ref.$el;
      return typeof ref.getBoundingClientRect === 'function' ? ref : null;
    },
    _workerDragSource(e) {
      const raw = e?.dataTransfer?.getData?.('application/x-worker-slot');
      if (raw !== '' && raw != null) {
        const source = Number(raw);
        if (Number.isInteger(source)) return source;
      }
      const fallback = Number(window._bullpenWorkerDrag?.source);
      return Number.isInteger(fallback) ? fallback : null;
    },
    _isWorkerDrag(e) {
      const types = Array.from(e?.dataTransfer?.types || []);
      return types.includes('application/x-worker-slot') || types.includes('application/x-worker-group');
    },
    buildGroupMovePlan(sourceSlot, destinationCoord) {
      const source = Number(sourceSlot);
      if (!Number.isInteger(source) || !destinationCoord || !this.isWritableCoord(destinationCoord)) return null;
      const anchor = this.workerItemBySlot[source];
      if (!anchor) return null;
      const slots = this.workerGroupSlots(source);
      if (!slots.length) return null;
      const groupSet = new Set(slots);
      const deltaCol = destinationCoord.col - anchor.coord.col;
      const deltaRow = destinationCoord.row - anchor.coord.row;
      const coordKeys = new Set();
      const moves = [];
      for (const slot of slots) {
        const item = this.workerItemBySlot[slot];
        if (!item) return null;
        const target = { col: item.coord.col + deltaCol, row: item.coord.row + deltaRow };
        if (!this.isWritableCoord(target)) return null;
        const key = GridGeometry.coordKey(target.col, target.row);
        if (coordKeys.has(key)) return null;
        coordKeys.add(key);
        const occupied = this.itemAtCoord(target);
        if (occupied && !groupSet.has(occupied.slotIndex)) return null;
        moves.push({ slot, to_coord: target });
      }
      return { source, slots, moves };
    },
    canDropWorkerAtSlot(sourceSlot, targetSlot) {
      const target = this.workerItemBySlot[targetSlot];
      if (!target) return false;
      return !!this.buildGroupMovePlan(sourceSlot, target.coord);
    },
    canDropWorkerAtCoord(sourceSlot, coord) {
      return !!this.buildGroupMovePlan(sourceSlot, coord);
    },
    dropWorkerOnSlot(sourceSlot, targetSlot) {
      this._clearDropTarget();
      const target = this.workerItemBySlot[targetSlot];
      if (!target) return;
      this.moveWorkerGroupToCoord(sourceSlot, target.coord);
    },
    moveWorkerGroupToCoord(sourceSlot, coord) {
      const plan = this.buildGroupMovePlan(sourceSlot, coord);
      if (!plan || !plan.moves.length) return false;
      const changed = plan.moves.some(move => {
        const item = this.workerItemBySlot[move.slot];
        return item && (item.coord.col !== move.to_coord.col || item.coord.row !== move.to_coord.row);
      });
      if (!changed) return true;
      if (typeof this.$root.moveWorkerGroup === 'function') {
        this.$root.moveWorkerGroup(plan.moves);
      } else if (plan.moves.length === 1) {
        this.$root.moveWorker(plan.moves[0].slot, plan.moves[0].to_coord);
      } else {
        for (const move of plan.moves) this.$root.moveWorker(move.slot, move.to_coord);
      }
      this.hoveredCoord = null;
      this.emptyMenuCoord = null;
      return true;
    },
    copyWorker(slot) {
      const source = this.workerItemBySlot[slot];
      if (!source) return;
      const workers = this.workerGroupSlots(slot).map(memberSlot => {
        const item = this.workerItemBySlot[memberSlot];
        if (!item) return null;
        return {
          offset: {
            col: item.coord.col - source.coord.col,
            row: item.coord.row - source.coord.row,
          },
          worker: this.workerFieldsForClipboard(item.worker),
        };
      }).filter(Boolean);
      if (!workers.length) return;
      this.clipboardWorker = {
        anchor: { ...source.coord },
        workers,
      };
      this.liveMessage = workers.length > 1
        ? `Copied worker group (${workers.length}) from ${source.worker.name}`
        : `Copied worker ${source.worker.name}`;
    },
    clipboardTargetsForCoord(coord) {
      if (!this.clipboardWorker || !Array.isArray(this.clipboardWorker.workers)) return [];
      return this.clipboardWorker.workers.map(entry => ({
        coord: {
          col: coord.col + Number(entry?.offset?.col || 0),
          row: coord.row + Number(entry?.offset?.row || 0),
        },
        worker: entry?.worker || {},
      }));
    },
    canPasteAt(coord) {
      if (!this.clipboardWorker || !coord || !this.isWritableCoord(coord)) return false;
      const targets = this.clipboardTargetsForCoord(coord);
      if (!targets.length) return false;
      const seen = new Set();
      for (const target of targets) {
        if (!this.isWritableCoord(target.coord)) return false;
        const key = GridGeometry.coordKey(target.coord.col, target.coord.row);
        if (seen.has(key)) return false;
        seen.add(key);
        if (this.itemAtCoord(target.coord)) return false;
      }
      return true;
    },
    pasteWorker(coord, options = {}) {
      if (!this.clipboardWorker || !coord || !this.isWritableCoord(coord)) return;
      const targets = this.clipboardTargetsForCoord(coord);
      if (!targets.length) return;
      const single = targets.length === 1 ? targets[0] : null;
      if (single && options.allowReplaceSingle) {
        const existing = this.itemAtCoord(single.coord);
        if (existing) {
          const existingName = existing.worker?.name || `Slot ${existing.slotIndex + 1}`;
          const pasteName = single.worker?.name || 'pasted worker';
          if (!confirm(`Replace worker "${existingName}" with "${pasteName}"?`)) return;
          this.$root.pasteWorkerConfig({ coord: single.coord, worker: single.worker, replace: true });
          this.emptyMenuCoord = null;
          return;
        }
      }
      const blocked = targets.find(target => !this.isWritableCoord(target.coord) || this.itemAtCoord(target.coord));
      if (blocked) {
        this.liveMessage = 'Cannot paste worker group here';
        return;
      }
      if (targets.length === 1) {
        this.$root.pasteWorkerConfig({ coord: targets[0].coord, worker: targets[0].worker });
      } else if (typeof this.$root.pasteWorkerGroup === 'function') {
        this.$root.pasteWorkerGroup(targets);
      } else {
        for (const target of targets) {
          this.$root.pasteWorkerConfig({ coord: target.coord, worker: target.worker });
        }
      }
      this.emptyMenuCoord = null;
    },
    _setDropTarget(source, coord) {
      const plan = this.buildGroupMovePlan(source, coord);
      if (!plan) {
        this.dragOverCoord = null;
        this.dropTargetCoords = [];
        return false;
      }
      this.dragOverCoord = { ...coord };
      this.dropTargetCoords = plan.moves.map(m => ({ col: m.to_coord.col, row: m.to_coord.row }));
      return true;
    },
    _clearDropTarget() {
      this.dragOverCoord = null;
      this.dropTargetCoords = [];
    },
    onEmptyDragOver(e, coord) {
      if (!this._isWorkerDrag(e)) return;
      const source = this._workerDragSource(e);
      if (Number.isInteger(source) && this._setDropTarget(source, coord)) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      } else {
        e.dataTransfer.dropEffect = 'none';
        this._clearDropTarget();
      }
    },
    onDropOnEmpty(e, coord) {
      const source = this._workerDragSource(e);
      this._clearDropTarget();
      if (!Number.isInteger(source)) return;
      this.moveWorkerGroupToCoord(source, coord);
    },
    onCanvasDragOver(e) {
      if (!this._isWorkerDrag(e)) return;
      const source = this._workerDragSource(e);
      const coord = this.coordFromEvent(e);
      if (Number.isInteger(source) && coord && this._setDropTarget(source, coord)) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        this.hoveredCoord = coord;
      } else {
        e.dataTransfer.dropEffect = 'none';
        this.hoveredCoord = null;
        this._clearDropTarget();
      }
    },
    onCanvasDrop(e) {
      if (!this._isWorkerDrag(e)) return;
      const src = this._workerDragSource(e);
      const coord = this.coordFromEvent(e);
      this.hoveredCoord = null;
      this._clearDropTarget();
      if (!Number.isInteger(src) || !coord) return;
      this.moveWorkerGroupToCoord(src, coord);
    },
    onCanvasDragLeave(e) {
      const related = e && e.relatedTarget;
      const canvas = e && e.currentTarget;
      if (related && canvas && typeof canvas.contains === 'function' && canvas.contains(related)) return;
      this._clearDropTarget();
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
      this.updateResizeTooltip(e, `${this.columnWidth}px wide`);
    },
    onColumnResizeMove(e) {
      if (!this.columnResize) return;
      const dx = e.clientX - this.columnResize.startX;
      const next = this.columnResize.startWidth + dx;
      this.draggingColumnWidth = Math.max(140, Math.min(480, Math.round(next)));
      this.updateResizeTooltip(e, `${this.draggingColumnWidth}px wide`);
    },
    onColumnResizeUp(e) {
      if (!this.columnResize) return;
      e.currentTarget.releasePointerCapture?.(this.columnResize.pointerId);
      const dragged = this.draggingColumnWidth;
      this.columnResize = null;
      this.draggingColumnWidth = null;
      this.resizeTooltip = null;
      if (dragged != null) {
        const final = Math.max(140, Math.min(480, Math.round(dragged / 20) * 20));
        this.persistGrid({ columnWidth: final });
      }
    },
    resetColumnWidth() {
      this.columnResize = null;
      this.draggingColumnWidth = null;
      this.resizeTooltip = null;
      this.persistGrid({ columnWidth: 220 });
    },
    onRowResizeDown(e) {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      e.currentTarget.setPointerCapture?.(e.pointerId);
      this.rowResize = {
        startY: e.clientY,
        startHeight: this.rowHeight,
        pointerId: e.pointerId,
      };
      this.draggingRowHeight = this.rowHeight;
      this.updateResizeTooltip(e, `${this.rowHeight}px tall`);
    },
    onRowResizeMove(e) {
      if (!this.rowResize) return;
      const dy = e.clientY - this.rowResize.startY;
      const next = this.rowResize.startHeight + dy;
      this.draggingRowHeight = Math.max(32, Math.min(480, Math.round(next)));
      this.updateResizeTooltip(e, `${this.draggingRowHeight}px tall`);
    },
    onRowResizeUp(e) {
      if (!this.rowResize) return;
      e.currentTarget.releasePointerCapture?.(this.rowResize.pointerId);
      const dragged = this.draggingRowHeight;
      this.rowResize = null;
      this.draggingRowHeight = null;
      this.resizeTooltip = null;
      if (dragged != null) {
        const final = Math.max(32, Math.min(480, Math.round(dragged)));
        this.persistGrid({ rowHeight: final });
      }
    },
    resetRowHeight() {
      this.rowResize = null;
      this.draggingRowHeight = null;
      this.resizeTooltip = null;
      this.persistGrid({ rowHeight: 140 });
    },
    updateResizeTooltip(e, text) {
      this.resizeTooltip = { x: e.clientX + 14, y: e.clientY + 14, text };
    },
    onMinimapClick(e) {
      const rect = e.currentTarget.getBoundingClientRect();
      const b = this.minimapBounds;
      const scale = this.minimapScale;
      const col = b.colMin + (e.clientX - rect.left) / scale.x;
      const row = b.rowMin + (e.clientY - rect.top) / scale.y;
      this.setOrigin({
        col: col - (this.viewportPx.width / this.columnWidth) / 2,
        row: row - (this.viewportPx.height / this.rowHeight) / 2,
      });
    },
  }
};
