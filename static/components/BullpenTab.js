const WORKER_GRID_VIEWPORT_STORAGE_KEY = 'bullpen.workerGridViewportOrigins';

function normalizeStoredViewportOrigin(value) {
  if (!value || typeof value !== 'object') return null;
  const col = Number(value.col);
  const row = Number(value.row);
  if (!Number.isFinite(col) || !Number.isFinite(row)) return null;
  return { col, row };
}

function loadStoredWorkerGridViewportOrigins() {
  try {
    const parsed = JSON.parse(localStorage.getItem(WORKER_GRID_VIEWPORT_STORAGE_KEY) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out = {};
    for (const [key, value] of Object.entries(parsed)) {
      const origin = normalizeStoredViewportOrigin(value);
      if (origin) out[key] = origin;
    }
    return out;
  } catch (_err) {
    return {};
  }
}

function saveStoredWorkerGridViewportOrigins(origins) {
  try {
    localStorage.setItem(WORKER_GRID_VIEWPORT_STORAGE_KEY, JSON.stringify(origins || {}));
  } catch (_err) { /* ignore */ }
}

const BullpenTab = {
  UNCONFIGURED_PROFILE_ID: 'unconfigured-worker',
  HEADER_WIDTH: 40,
  HEADER_HEIGHT: 24,
  MINIMAP_HEADER_PX: 30,
  props: ['layout', 'config', 'profiles', 'tasks', 'taskById', 'workspace', 'workspaceId', 'multipleWorkspaces', 'minimapCollapsed'],
  emits: ['add-worker', 'configure-worker', 'select-task', 'open-focus', 'transfer-worker', 'set-minimap-collapsed'],
  components: { WorkerCard },
  data() {
    return {
      showLibrary: false,
      libraryMode: 'ai',
      shellExamples: [],
      shellExamplesLoaded: false,
      showGoTo: false,
      goToInput: '',
      goToWorkerSlot: '',
      goToError: '',
      showHelp: false,
      selectedAddCoord: null,
      pendingWorkerAdd: null,
      pendingWorkerAddTimer: null,
      hoveredCoord: null,
      selectedCell: null,
      selectionAnchor: null,
      selectedWorkerSlots: [],
      selectedWorkerScope: 'none',
      dragOverCoord: null,
      dropTargetCoords: [],
      emptyMenuCoord: null,
      emptyMenuPos: null,
      emptyMenuAnchorPos: null,
      clipboardWorker: null,
      viewportOrigin: { col: 0, row: 0 },
      viewportPx: { width: 0, height: 0 },
      dragStart: null,
      isPanning: false,
      liveMessage: '',
      valueShortcutEditor: null,
      columnResize: null,
      draggingColumnWidth: null,
      pendingColumnWidth: null,
      rowResize: null,
      draggingRowHeight: null,
      pendingRowHeight: null,
      pendingRowHeights: null,
      cardVerticalResize: null,
      expandedWorkerCardSlot: null,
      expandedWorkerCardDelta: 0,
      resizeTooltip: null,
      dragViewportRect: null,
      lastDropTargetKey: '',
      workspaceViewportOrigins: loadStoredWorkerGridViewportOrigins(),
    };
  },
  template: `
    <div class="bullpen-grid-container">
      <Teleport to="#worker-tab-toolbar-slot">
        <button class="btn btn-sm" @click="jumpHome">Home</button>
        <button class="btn btn-sm" @click="resetRowsSmall" title="Reset all row heights to small">Small Rows</button>
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
           @dblclick="onViewportDblClick"
           @paste="onPaste"
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
               :style="{ top: r.y + 'px', height: r.height + 'px' }">
            <span class="worker-grid-header-label">{{ r.label }}</span>
            <div class="worker-grid-row-resize"
                 :class="{ active: rowResize }"
                 title="Drag to resize this row; hold Shift for all rows"
                 @pointerdown="onRowResizeDown(r.row, $event)"
                 @click.stop
                 @dblclick.stop="resetRowHeight(r.row, $event)"></div>
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
            :class="{ selected: isSelected(item.coord), 'worker-card--expanded': cardHeightForSlot(item.slotIndex) > rowHeightForRow(item.coord.row) }"
            :worker="item.worker"
            :slot-index="item.slotIndex"
            :tasks="tasks"
            :task-by-id="taskById"
            :output-lines="$root.outputLinesForSlot(item.slotIndex, workspaceId)"
            :multiple-workspaces="multipleWorkspaces"
            :neighbor-slots="neighborSlotsMap[item.slotIndex]"
            :all-workers="layout.slots"
            :layout-mode="layoutMode"
            :card-height="cardHeightForSlot(item.slotIndex)"
            :is-selected="isSelected(item.coord)"
            :multiple-selection-active="isMultipleSelectionActive"
            :menu-context="workerMenuContext(item.slotIndex)"
            :is-vertical-resizing="cardVerticalResize && cardVerticalResize.slotIndex === item.slotIndex"
            :workspace-id="workspaceId"
            :request-output-catchup="$root.requestOutputCatchup"
            :build-worker-drag-payload="buildWorkerDragPayload"
            :build-worker-drag-image="buildWorkerDragImage"
            :can-drop-worker-at-slot="canDropWorkerAtSlot"
            :drop-worker-on-slot="dropWorkerOnSlot"
            :update-singleton-worker-drag="updateSingletonWorkerDrag"
            :end-singleton-worker-drag="endSingletonWorkerDrag"
            :cancel-singleton-worker-drag="cancelSingletonWorkerDrag"
            :aria-rowindex="ariaRowIndex(item.coord)"
            :aria-colindex="ariaColIndex(item.coord)"
            :aria-label="'Worker ' + item.worker.name + ' at column ' + item.coord.col + ', row ' + item.coord.row"
            @click.capture="onWorkerClick($event, item)"
            @configure="$emit('configure-worker', $event)"
            @select-task="$emit('select-task', $event)"
            @open-focus="$emit('open-focus', $event)"
            @transfer="$emit('transfer-worker', $event)"
            @copy-worker="copyWorker"
            @delete-worker="deleteWorkerFromMenu"
            @worker-scope-action="handleWorkerScopeAction"
            @vertical-resize-start="onCardVerticalResizeStart(item, $event)"
            @menu-opened="selectWorker(item, { preserveMultiple: true })"
            @menu-closed="focusViewport"
            @value-edit-ended="onValueEditEnded(item)"
          />

          <div class="worker-pass-connector-layer" aria-hidden="true">
            <span v-for="connector in visiblePassConnectors"
                  :key="'pass-' + connector.slotIndex + '-' + connector.dir"
                  class="worker-pass-connector"
                  :class="'worker-pass-connector-' + connector.dir"
                  :style="connector.style">{{ connector.arrow }}</span>
          </div>

          <div v-for="cell in visibleDropTargetOverlays"
               :key="'drop-' + cell.col + '-' + cell.row"
               class="worker-grid-drop-target-overlay"
               :style="cell.style"
               aria-hidden="true"></div>

          <div v-if="ghostCell"
               class="grid-slot empty-slot worker-grid-ghost-cell"
               :class="{
                 selected: isSelected(ghostCell),
                 'drag-over': isDragOverGhost(ghostCell),
                 'menu-open': emptyMenuOpenFor(ghostCell),
               }"
               :style="ghostStyle"
               role="gridcell"
               tabindex="-1"
               :aria-rowindex="ariaRowIndex(ghostCell)"
               :aria-colindex="ariaColIndex(ghostCell)"
               :aria-label="'Empty cell at column ' + ghostCell.col + ', row ' + ghostCell.row"
               @click.stop="openEmptyMenu(ghostCell, $event)"
               @dblclick.stop="openAddWorkerForEmptyCell(ghostCell)"
               @dragover="onEmptyDragOver($event, ghostCell)"
               @drop.stop.prevent="onDropOnEmpty($event, ghostCell)">
            <button class="empty-slot-menu-btn" draggable="false" title="Empty cell actions" @click.stop="openEmptyMenu(ghostCell, $event)">&hellip;</button>
          </div>
          <div v-if="valueShortcutEditor"
               class="value-shortcut-editor"
               :style="valueShortcutEditorStyle"
               @click.stop>
            <input class="value-shortcut-input"
                   ref="valueShortcutInput"
                   v-model="valueShortcutEditor.text"
                   @keydown.stop="onValueShortcutKeydown"
                   aria-label="Create value worker">
            <div v-if="valueShortcutEditor.error" class="value-shortcut-error">{{ valueShortcutEditor.error }}</div>
          </div>
          <div v-if="ghostCell && emptyMenuOpenFor(ghostCell)"
               class="worker-menu empty-slot-menu"
               :style="emptyMenuStyle"
               ref="emptyMenu"
               tabindex="-1"
               @keydown="onEmptyMenuKeydown"
               @click.stop>
            <button class="worker-menu-item" @click="openLibraryForCoord(ghostCell)"><i class="menu-item-icon" data-lucide="user-plus" aria-hidden="true"></i><span class="menu-item-label">Add Worker</span></button>
            <button class="worker-menu-item" :disabled="!canPasteAt(ghostCell)" @click="pasteWorkerFromMenu(ghostCell)"><i class="menu-item-icon" data-lucide="clipboard" aria-hidden="true"></i><span class="menu-item-label">Paste Worker</span></button>
          </div>
        </div>

        <div class="worker-minimap" :class="{ collapsed: minimapCollapsed }" @pointerdown.stop>
          <button
            class="worker-minimap-toggle"
            @click="toggleMinimap"
            :title="minimapCollapsed ? 'Show minimap' : 'Hide minimap'"
            :aria-label="minimapCollapsed ? 'Show minimap' : 'Hide minimap'"
          >▣</button>
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
        v-if="showGoTo"
        class="modal-overlay"
        @click.self="closeGoTo"
        @keydown.escape="closeGoTo"
        tabindex="0"
      >
        <div class="modal" style="min-width: 320px;">
          <div class="modal-header">
            <h2>Go to</h2>
            <button class="btn btn-icon" @click="closeGoTo">&times;</button>
          </div>
          <div class="modal-body">
            <form @submit.prevent="submitGoTo">
              <label class="form-label">
                Cell address
                <input
                  ref="goToInputEl"
                  type="text"
                  v-model="goToInput"
                  class="form-input"
                  placeholder="AA122"
                  style="width: 100%; box-sizing: border-box;"
                  @input="onGoToCellInput"
                  @keydown.escape.stop="closeGoTo"
                />
              </label>
              <label class="form-label" style="margin-top: 10px;">
                Worker
                <select
                  v-model="goToWorkerSlot"
                  class="form-select"
                  style="width: 100%; box-sizing: border-box;"
                  @change="onGoToWorkerSelect"
                >
                  <option value="">Select a worker</option>
                  <option
                    v-for="item in goToWorkerOptions"
                    :key="item.slotIndex"
                    :value="String(item.slotIndex)"
                  >
                    {{ item.label }}
                  </option>
                </select>
              </label>
              <div v-if="goToError" style="color: var(--color-danger, #c33); margin-top: 6px; font-size: 12px;">
                {{ goToError }}
              </div>
              <div style="margin-top: 10px; display: flex; gap: 8px; justify-content: flex-end;">
                <button type="button" class="btn btn-sm" @click="closeGoTo">Cancel</button>
                <button type="submit" class="btn btn-sm btn-primary">Go</button>
              </div>
            </form>
          </div>
        </div>
      </div>

      <div
        v-if="showHelp"
        class="modal-overlay"
        @click.self="closeHelp"
        @keydown.escape="closeHelp"
        tabindex="0"
        ref="helpOverlay"
      >
        <div class="modal" style="min-width: 420px;">
          <div class="modal-header">
            <h2>Keyboard shortcuts</h2>
            <button class="btn btn-icon" @click="closeHelp">&times;</button>
          </div>
          <div class="modal-body">
            <table style="width: 100%; border-collapse: collapse;">
              <tbody>
                <tr v-for="row in helpShortcuts" :key="row.keys">
                  <td style="padding: 4px 12px 4px 0; white-space: nowrap; font-family: monospace;">{{ row.keys }}</td>
                  <td style="padding: 4px 0;">{{ row.desc }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div
        v-if="showLibrary"
        class="modal-overlay"
        @click.self="closeLibrary"
        @keydown.escape="closeLibrary"
        tabindex="0"
        ref="libraryOverlay"
      >
        <div class="modal worker-library-modal">
          <div class="modal-header">
            <h2>Add Worker</h2>
            <button class="btn btn-icon" @click="closeLibrary">&times;</button>
          </div>
          <div class="worker-type-tabs" role="tablist" aria-label="Worker type">
            <button class="worker-type-tab" :class="{ active: libraryMode === 'ai' }"
                    role="tab" :aria-selected="libraryMode === 'ai'"
                    @click="libraryMode = 'ai'">
              <i data-lucide="bot" aria-hidden="true"></i>
              <span>AI</span>
            </button>
            <button class="worker-type-tab" :class="{ active: libraryMode === 'shell' }"
                    role="tab" :aria-selected="libraryMode === 'shell'"
                    @click="libraryMode = 'shell'">
              <i data-lucide="terminal" aria-hidden="true"></i>
              <span>Shell</span>
            </button>
            <button class="worker-type-tab" :class="{ active: libraryMode === 'service' }"
                    role="tab" :aria-selected="libraryMode === 'service'"
                    @click="libraryMode = 'service'">
              <i data-lucide="server-cog" aria-hidden="true"></i>
              <span>Service</span>
            </button>
            <button class="worker-type-tab" :class="{ active: libraryMode === 'marker' }"
                    role="tab" :aria-selected="libraryMode === 'marker'"
                    @click="libraryMode = 'marker'">
              <i data-lucide="square-dot" aria-hidden="true"></i>
              <span>Marker</span>
            </button>
            <button class="worker-type-tab" :class="{ active: libraryMode === 'notification' }"
                    role="tab" :aria-selected="libraryMode === 'notification'"
                    @click="libraryMode = 'notification'">
              <i data-lucide="bell-ring" aria-hidden="true"></i>
              <span>Notification</span>
            </button>
            <button class="worker-type-tab" :class="{ active: libraryMode === 'value' }"
                    role="tab" :aria-selected="libraryMode === 'value'"
                    @click="libraryMode = 'value'">
              <i data-lucide="equal" aria-hidden="true"></i>
              <span>Value</span>
            </button>
          </div>
          <div v-if="libraryMode === 'ai'" class="modal-body profile-library">
            <div v-for="p in sortedProfiles" :key="p.id"
                 class="profile-item"
                 @click="addFromLibrary(p.id)">
              <span class="profile-name">{{ p.name }}</span>
              <span class="profile-agent">{{ p.default_agent }}/{{ p.default_model }}</span>
            </div>
          </div>
          <div v-else-if="libraryMode === 'shell'" class="modal-body profile-library">
            <div class="profile-item profile-item--blank"
                 @click="addShellWorker()">
              <span class="profile-name">Blank shell worker</span>
              <span class="profile-agent">configure from scratch</span>
            </div>
            <div v-for="ex in platformShellExamples" :key="ex.id"
                 class="profile-item"
                 :title="ex.description"
                 @click="addShellWorker(ex)">
              <span class="profile-name">{{ ex.name }}</span>
              <span class="profile-agent">{{ ex.description }}</span>
            </div>
          </div>
          <div v-else-if="libraryMode === 'service'" class="modal-body profile-library">
            <div class="profile-item profile-item--blank"
                 @click="addServiceWorker()">
              <span class="profile-name">Blank service worker</span>
              <span class="profile-agent">long-running process</span>
            </div>
          </div>
          <div v-else-if="libraryMode === 'marker'" class="modal-body profile-library">
            <div class="profile-item profile-item--blank"
                 @click="addMarkerWorker()">
              <span class="profile-name">Blank marker worker</span>
              <span class="profile-agent">label, jump target, pass-through</span>
            </div>
          </div>
          <div v-else-if="libraryMode === 'notification'" class="modal-body profile-library">
            <div class="profile-item profile-item--blank"
                 @click="addNotificationWorker()">
              <span class="profile-name">Blank notification worker</span>
              <span class="profile-agent">toast, speech, sound, flash</span>
            </div>
          </div>
          <div v-else-if="libraryMode === 'value'" class="modal-body profile-library">
            <div class="profile-item profile-item--blank"
                 @click="addValueWorker()">
              <span class="profile-name">Blank value worker</span>
              <span class="profile-agent">named spreadsheet value</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  computed: {
    helpShortcuts() {
      const mod = (navigator.platform || '').toLowerCase().includes('mac') ? '⌘' : 'Ctrl';
      return [
        { keys: '?', desc: 'Show this help' },
        { keys: 'Arrow keys', desc: 'Move selection between cells' },
        { keys: 'Enter', desc: 'Open worker menu (or empty-cell menu)' },
        { keys: 'Delete / Backspace', desc: 'Remove selected worker' },
        { keys: 'Home', desc: 'Jump to origin (A1)' },
        { keys: 'F', desc: 'Fit view to occupied cells' },
        { keys: `${mod}+G`, desc: 'Go to worker or cell (e.g. AA122)' },
        { keys: `${mod}+C`, desc: 'Copy selected worker' },
        { keys: `${mod}+V`, desc: 'Paste clipboard values into selected cell' },
        { keys: 'Escape', desc: 'Close open menu or modal' },
      ];
    },
    gridConfig() { return this.config?.grid || {}; },
    legacyCols() {
      const n = Number(this.gridConfig.cols);
      return Number.isFinite(n) && n > 0 ? Math.floor(n) : 4;
    },
    layoutMode() {
      return this.rowHeight < 40 ? 'small' : 'medium';
    },
    columnWidth() {
      if (this.draggingColumnWidth !== null) {
        return this.clampColumnWidth(this.draggingColumnWidth);
      }
      if (this.pendingColumnWidth !== null) {
        return this.clampColumnWidth(this.pendingColumnWidth);
      }
      const raw = Number(this.gridConfig.columnWidth);
      const n = Number.isFinite(raw) ? raw : 220;
      return this.clampColumnWidth(n);
    },
    headerWidth() { return this.$options.HEADER_WIDTH; },
    headerHeight() { return this.$options.HEADER_HEIGHT; },
    rowHeight() {
      if (
        this.draggingRowHeight !== null &&
        (this.rowResize?.mode === 'global' || this.cardVerticalResize?.mode === 'global')
      ) {
        return this.clampRowHeight(this.draggingRowHeight);
      }
      if (this.pendingRowHeight !== null) {
        return this.clampRowHeight(this.pendingRowHeight);
      }
      const raw = Number(this.gridConfig.rowHeight);
      if (Number.isFinite(raw)) {
        return this.clampRowHeight(raw);
      }
      return 140;
    },
    rowHeightOverrides() {
      if (this.pendingRowHeights && typeof this.pendingRowHeights === 'object') {
        return this.pendingRowHeights;
      }
      return this.normalizeRowHeights(this.gridConfig.rowHeights);
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
    goToWorkerOptions() {
      return this.workerItems.map(item => ({
        slotIndex: item.slotIndex,
        label: `${item.worker?.name || `Slot ${item.slotIndex + 1}`} (${this.colLabel(item.coord.col)}${this.rowLabel(item.coord.row)})`,
      }));
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
      const colRange = GridGeometry.visibleRange(this.viewportOrigin, this.viewportPx, this.cardSize);
      const rowStart = Math.max(0, this.rowFromPixel(0) - 2);
      const rowEnd = Math.max(rowStart, this.rowFromPixel(this.viewportPx.height) + 2);
      return {
        colStart: Math.max(0, colRange.colStart - 2),
        colEnd: colRange.colEnd + 2,
        rowStart,
        rowEnd,
      };
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
          y: this.rowPixelTop(rr),
          height: this.rowHeightForRow(rr),
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
      const p = this.coordPixel(this.ghostCell);
      return this.insetBoxStyle(p.x, p.y, this.columnWidth, this.rowHeightForRow(this.ghostCell.row));
    },
    valueShortcutEditorStyle() {
      const coord = this.valueShortcutEditor?.coord;
      if (!coord) return {};
      const p = this.coordPixel(coord);
      return this.insetBoxStyle(p.x, p.y, this.columnWidth, this.rowHeightForRow(coord.row));
    },
    visibleDropTargetOverlays() {
      const coords = this.dropTargetCoords;
      if (!coords || !coords.length) return [];
      const r = this.visibleRange;
      const out = [];
      for (const c of coords) {
        if (!c) continue;
        if (c.col < r.colStart || c.col > r.colEnd || c.row < r.rowStart || c.row > r.rowEnd) continue;
        const p = this.coordPixel(c);
        out.push({
          col: c.col,
          row: c.row,
          style: this.insetBoxStyle(p.x, p.y, this.columnWidth, this.rowHeightForRow(c.row)),
        });
      }
      return out;
    },
    visiblePassConnectors() {
      const r = this.visibleRange;
      const out = [];
      for (const item of this.workerItems) {
        if (
          item.coord.col < r.colStart || item.coord.col > r.colEnd ||
          item.coord.row < r.rowStart || item.coord.row > r.rowEnd
        ) continue;
        const disposition = String(item.worker?.disposition || '');
        if (!disposition.startsWith('pass:')) continue;
        const dir = disposition.slice(5);
        if (!['up', 'down', 'left', 'right'].includes(dir)) continue;
        const target = this.neighborSlotsMap[item.slotIndex]?.[dir];
        if (!Number.isInteger(target)) continue;
        out.push({
          slotIndex: item.slotIndex,
          dir,
          arrow: this.passConnectorArrow(dir),
          style: this.passConnectorStyle(item, dir),
        });
      }
      return out;
    },
    emptyMenuStyle() {
      if (this.emptyMenuPos) {
        return { position: 'fixed', top: this.emptyMenuPos.y + 'px', left: this.emptyMenuPos.x + 'px' };
      }
      if (!this.ghostCell) return {};
      const p = this.coordPixel(this.ghostCell);
      const rect = this.$refs.viewport?.getBoundingClientRect();
      const x = (rect?.left || 0) + this.headerWidth + p.x + this.columnWidth / 2;
      const y = (rect?.top || 0) + this.headerHeight + p.y + this.rowHeightForRow(this.ghostCell.row) / 2;
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
    platformShellExamples() {
      const isWin = (navigator.platform || '').toLowerCase().includes('win');
      const current = isWin ? 'windows' : 'posix';
      return (this.shellExamples || []).filter(ex => !ex.platforms || ex.platforms.includes(current));
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
    passTargetsBySlot() {
      const map = {};
      for (const item of this.workerItems) {
        const disposition = String(item.worker?.disposition || '');
        if (!disposition.startsWith('pass:')) {
          map[item.slotIndex] = [];
          continue;
        }
        const passDir = disposition.slice(5);
        const neighbors = this.neighborSlotsMap[item.slotIndex] || {};
        if (['up', 'down', 'left', 'right'].includes(passDir)) {
          const target = neighbors[passDir];
          map[item.slotIndex] = Number.isInteger(target) ? [target] : [];
          continue;
        }
        if (passDir === 'random') {
          const out = [];
          for (const dir of ['up', 'down', 'left', 'right']) {
            const target = neighbors[dir];
            if (Number.isInteger(target) && !out.includes(target)) out.push(target);
          }
          map[item.slotIndex] = out;
          continue;
        }
        map[item.slotIndex] = [];
      }
      return map;
    },
    passSourcesBySlot() {
      const map = {};
      for (const item of this.workerItems) map[item.slotIndex] = [];
      for (const item of this.workerItems) {
        for (const target of this.passTargetsBySlot[item.slotIndex] || []) {
          if (!map[target]) map[target] = [];
          if (!map[target].includes(item.slotIndex)) map[target].push(item.slotIndex);
        }
      }
      return map;
    },
    selectedWorkerSlot() {
      const coord = this.selectedCell;
      return coord ? this.itemAtCoord(coord)?.slotIndex ?? null : null;
    },
    isMultipleSelectionActive() {
      return Array.isArray(this.selectedWorkerSlots) && this.selectedWorkerSlots.length > 1;
    },
    isExplicitSelectionActive() {
      return this.isMultipleSelectionActive && this.selectedWorkerScope === 'selection';
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
      const { x: sx, y: sy } = this.minimapScale;
      const w = Math.max(2, sx - 0.5);
      const h = Math.max(2, sy - 0.5);
      const radius = Math.max(1, Math.min(2, Math.min(w, h) * 0.3));
      return this.workerItems.map(item => ({
        key: item.slotIndex,
        style: {
          left: ((item.coord.col - b.colMin) * sx) + 'px',
          top: ((item.coord.row - b.rowMin) * sy) + 'px',
          width: w + 'px',
          height: h + 'px',
          borderRadius: radius + 'px',
          background: workerColor(item.worker),
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
    minimapVisibleCells() {
      return {
        cols: this.viewportPx.width / this.columnWidth,
        rows: this.viewportPx.height / this.rowHeight,
      };
    },
  },
  watch: {
    rowHeight(next) {
      const clamped = Math.max(0, Math.min(this.expandedWorkerCardDelta, Math.max(0, 480 - next)));
      if (clamped !== this.expandedWorkerCardDelta) this.expandedWorkerCardDelta = clamped;
      if (clamped === 0 && this.expandedWorkerCardSlot !== null && !this.cardVerticalResize) {
        this.expandedWorkerCardSlot = null;
      }
    },
    selectedWorkerSlot(next) {
      if (next === this.expandedWorkerCardSlot) return;
      if (this.cardVerticalResize) return;
      this.clearExpandedWorkerCard();
    },
    emptyMenuCoord(next) {
      if (next) return;
      this.emptyMenuPos = null;
      this.emptyMenuAnchorPos = null;
    },
    workspaceId() {
      this.restoreWorkspaceViewportOrigin();
    },
    workspace: {
      handler() {
        this.selectA1();
      },
    },
    gridConfig: {
      deep: true,
      handler() {
        this.reconcilePendingGridSize();
      },
    },
    layout: {
      deep: true,
      handler() {
        this.resolvePendingWorkerAdd();
      },
    },
  },
  mounted() {
    this.updateViewportSize();
    this.restoreWorkspaceViewportOrigin();
    this._resizeObserver = new ResizeObserver(() => this.updateViewportSize());
    if (this.$refs.viewport) this._resizeObserver.observe(this.$refs.viewport);
    this.selectA1();
    renderLucideIcons(this.$el);
    window.addEventListener('resize', this.repositionEmptyMenuWithinViewport);
    window.addEventListener('scroll', this.repositionEmptyMenuWithinViewport, true);
  },
  updated() {
    this.$nextTick(() => renderLucideIcons(this.$el));
  },
  beforeUnmount() {
    this._resizeObserver?.disconnect();
    this._teardownColumnResizeListeners?.();
    this._teardownRowResizeListeners?.();
    this._teardownCardVerticalResizeListeners?.();
    window.removeEventListener('resize', this.repositionEmptyMenuWithinViewport);
    window.removeEventListener('scroll', this.repositionEmptyMenuWithinViewport, true);
    if (this.pendingWorkerAddTimer) clearTimeout(this.pendingWorkerAddTimer);
  },
  methods: {
    clampColumnWidth(value) {
      const n = Number(value);
      const base = Number.isFinite(n) ? n : 220;
      return Math.max(140, Math.min(480, Math.round(base / 20) * 20));
    },
    clampRowHeight(value) {
      const n = Number(value);
      const base = Number.isFinite(n) ? n : 140;
      return Math.max(32, Math.min(480, Math.round(base)));
    },
    normalizeRowHeights(value, baseHeight = this.rowHeight) {
      const out = {};
      if (!value || typeof value !== 'object' || Array.isArray(value)) return out;
      const globalHeight = this.clampRowHeight(baseHeight);
      for (const [key, rawValue] of Object.entries(value)) {
        const row = Number(key);
        const height = Number(rawValue);
        if (!Number.isInteger(row) || row < 0 || !Number.isFinite(height)) continue;
        const clamped = this.clampRowHeight(height);
        if (clamped !== globalHeight) out[String(row)] = clamped;
      }
      return out;
    },
    rowHeightForRow(row) {
      const rowIndex = Math.max(0, Math.trunc(Number(row) || 0));
      const globalResize = this.rowResize?.mode === 'global'
        ? this.rowResize
        : (this.cardVerticalResize?.mode === 'global' ? this.cardVerticalResize : null);
      if (globalResize && this.draggingRowHeight !== null) {
        const startOverride = Number(globalResize.startRowHeights?.[String(rowIndex)]);
        if (Number.isFinite(startOverride)) {
          const delta = this.clampRowHeight(this.draggingRowHeight) - this.clampRowHeight(globalResize.startGlobalHeight);
          return this.clampRowHeight(startOverride + delta);
        }
      }
      if (this.rowResize?.mode === 'single' && this.rowResize.row === rowIndex && this.draggingRowHeight !== null) {
        return this.clampRowHeight(this.draggingRowHeight);
      }
      if (this.cardVerticalResize?.mode === 'single' && this.cardVerticalResize.row === rowIndex && this.draggingRowHeight !== null) {
        return this.clampRowHeight(this.draggingRowHeight);
      }
      const override = Number(this.rowHeightOverrides[String(rowIndex)]);
      return Number.isFinite(override) ? this.clampRowHeight(override) : this.rowHeight;
    },
    rowPixelTop(row) {
      const target = Math.max(0, Math.trunc(Number(row) || 0));
      const origin = Math.max(0, Number(this.viewportOrigin.row) || 0);
      const originRow = Math.floor(origin);
      const fraction = origin - originRow;
      let y = -(fraction * this.rowHeightForRow(originRow));
      if (target >= originRow) {
        for (let rr = originRow; rr < target; rr++) y += this.rowHeightForRow(rr);
      } else {
        for (let rr = originRow - 1; rr >= target; rr--) y -= this.rowHeightForRow(rr);
      }
      return y;
    },
    rowFromPixel(y) {
      const targetY = Number(y) || 0;
      const origin = Math.max(0, Number(this.viewportOrigin.row) || 0);
      const originRow = Math.floor(origin);
      const fraction = origin - originRow;
      let row = originRow;
      let top = -(fraction * this.rowHeightForRow(row));
      if (targetY < top) {
        while (row > 0) {
          row -= 1;
          top -= this.rowHeightForRow(row);
          if (targetY >= top) return row;
        }
        return 0;
      }
      let guard = 0;
      while (guard < 1000) {
        const height = this.rowHeightForRow(row);
        if (targetY < top + height) return row;
        top += height;
        row += 1;
        guard += 1;
      }
      return row;
    },
    coordPixel(coord) {
      return {
        x: (Number(coord.col) - this.viewportOrigin.col) * this.columnWidth,
        y: this.rowPixelTop(coord.row),
      };
    },
    rowSpanHeight(startRow, endRow) {
      let height = 0;
      for (let row = startRow; row <= endRow; row++) height += this.rowHeightForRow(row);
      return height;
    },
    rowOffsetBetween(startRow, targetRow) {
      let offset = 0;
      for (let row = startRow; row < targetRow; row++) offset += this.rowHeightForRow(row);
      return offset;
    },
    adjustedGlobalRowHeights(resize, finalHeight) {
      const rowHeights = {};
      const final = this.clampRowHeight(finalHeight);
      const startGlobal = this.clampRowHeight(resize?.startGlobalHeight);
      const delta = final - startGlobal;
      const startRowHeights = resize?.startRowHeights || {};
      for (const [row, height] of Object.entries(startRowHeights)) {
        const adjusted = this.clampRowHeight(Number(height) + delta);
        if (adjusted !== final) rowHeights[row] = adjusted;
      }
      return rowHeights;
    },
    reconcilePendingGridSize() {
      if (this.pendingColumnWidth !== null) {
        const raw = Number(this.gridConfig.columnWidth);
        if (Number.isFinite(raw) && this.clampColumnWidth(raw) === this.clampColumnWidth(this.pendingColumnWidth)) {
          this.pendingColumnWidth = null;
        }
      }
      if (this.pendingRowHeight !== null) {
        const raw = Number(this.gridConfig.rowHeight);
        if (Number.isFinite(raw) && this.clampRowHeight(raw) === this.clampRowHeight(this.pendingRowHeight)) {
          this.pendingRowHeight = null;
        }
      }
      if (this.pendingRowHeights !== null) {
        const current = JSON.stringify(this.normalizeRowHeights(this.gridConfig.rowHeights));
        const pending = JSON.stringify(this.normalizeRowHeights(this.pendingRowHeights));
        if (current === pending) this.pendingRowHeights = null;
      }
    },
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
    viewportOriginFromConfig() {
      const value = this.config?.grid?.viewportOrigin;
      return this.clampedOrigin({
        col: Number.isFinite(Number(value?.col)) ? Number(value.col) : 0,
        row: Number.isFinite(Number(value?.row)) ? Number(value.row) : 0,
      });
    },
    restoreWorkspaceViewportOrigin() {
      const key = this.workspaceId || '__default__';
      const cached = this.workspaceViewportOrigins[key];
      this.viewportOrigin = cached
        ? this.clampedOrigin(cached)
        : this.viewportOriginFromConfig();
    },
    rememberWorkspaceViewportOrigin() {
      const key = this.workspaceId || '__default__';
      this.workspaceViewportOrigins[key] = { ...this.viewportOrigin };
      saveStoredWorkerGridViewportOrigins(this.workspaceViewportOrigins);
    },
    persistGrid(partial = {}) {
      const grid = {
        ...(this.config?.grid || {}),
        columnWidth: this.columnWidth,
        rowHeight: this.rowHeight,
        ...partial,
      };
      delete grid.viewportOrigin;
      this.$root.updateConfig({ grid });
    },
    cardExpansionLimit(slotIndex = null) {
      const item = slotIndex === null ? null : this.workerItemBySlot[slotIndex];
      const baseHeight = item ? this.rowHeightForRow(item.coord.row) : this.rowHeight;
      return Math.max(0, 480 - baseHeight);
    },
    cardExpansionDeltaForSlot(slotIndex) {
      if (this.expandedWorkerCardSlot !== slotIndex) return 0;
      return Math.max(0, Math.min(this.expandedWorkerCardDelta, this.cardExpansionLimit(slotIndex)));
    },
    cardHeightForSlot(slotIndex) {
      const item = this.workerItemBySlot[slotIndex];
      const baseHeight = item ? this.rowHeightForRow(item.coord.row) : this.rowHeight;
      return baseHeight + this.cardExpansionDeltaForSlot(slotIndex);
    },
    insetBoxStyle(x, y, width, height) {
      const minWidth = 64;
      const minHeight = 24;
      const insetX = Math.min(1, Math.max(0, (width - minWidth) / 2));
      const insetY = Math.min(1, Math.max(0, (height - minHeight) / 2));
      return {
        left: (x + insetX) + 'px',
        top: (y + insetY) + 'px',
        width: Math.max(minWidth, width - insetX * 2) + 'px',
        height: Math.max(minHeight, height - insetY * 2) + 'px',
      };
    },
    cardStyle(item) {
      const p = this.coordPixel(item.coord);
      const expanded = this.cardExpansionDeltaForSlot(item.slotIndex);
      return {
        position: 'absolute',
        ...this.insetBoxStyle(p.x, p.y, this.columnWidth, this.cardHeightForSlot(item.slotIndex)),
        zIndex: expanded > 0 ? 6 : null,
      };
    },
    passConnectorArrow(dir) {
      return {
        up: '\u25B2',
        down: '\u25BC',
        left: '\u25C0',
        right: '\u25B6',
      }[dir] || '';
    },
    passConnectorStyle(item, dir) {
      const p = this.coordPixel(item.coord);
      const box = this.insetBoxStyle(p.x, p.y, this.columnWidth, this.cardHeightForSlot(item.slotIndex));
      const left = parseFloat(box.left);
      const top = parseFloat(box.top);
      const width = parseFloat(box.width);
      const height = parseFloat(box.height);
      const positions = {
        up: { left: left + width / 2, top },
        down: { left: left + width / 2, top: top + height },
        left: { left, top: top + height / 2 },
        right: { left: left + width, top: top + height / 2 },
      };
      const pos = positions[dir] || { left, top };
      return {
        left: pos.left + 'px',
        top: pos.top + 'px',
      };
    },
    setOrigin(origin, persist = true) {
      this.viewportOrigin = this.clampedOrigin(origin);
      if (persist) this.rememberWorkspaceViewportOrigin();
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
      const rect = this.dragViewportRect || this.$refs.viewport.getBoundingClientRect();
      const x = e.clientX - rect.left - this.headerWidth;
      const y = e.clientY - rect.top - this.headerHeight;
      return {
        col: Math.floor((Number(this.viewportOrigin.col) || 0) + (Number(x) || 0) / this.columnWidth),
        row: this.rowFromPixel(y),
      };
    },
    onViewportMouseMove(e) {
      if (this.isPanning) return;
      const coord = this.coordFromEvent(e);
      this.hoveredCoord = this.itemAtCoord(coord) ? null : coord;
    },
    onViewportPointerDown(e) {
      if (e.button !== 0 && e.button !== 1) return;
      if (e.target.closest('.worker-menu, button, input, select, textarea')) return;
      if (e.target.closest('.worker-card') && e.pointerType !== 'touch') return;
      const coord = this.coordFromEvent(e);
      const isTouch = e.pointerType === 'touch';
      this.dragStart = {
        x: e.clientX,
        y: e.clientY,
        button: e.button,
        selection: e.button === 0 && !isTouch,
        selectionMoved: false,
        origin: { ...this.viewportOrigin },
        coord,
      };
      if (this.dragStart.selection) {
        this.selectionAnchor = e.shiftKey && this.selectionAnchor ? { ...this.selectionAnchor } : { ...coord };
        this.updateRangeSelection(this.selectionAnchor, coord);
      }
      this.$refs.viewport.setPointerCapture?.(e.pointerId);
    },
    onViewportPointerMove(e) {
      if (!this.dragStart) return;
      const dx = e.clientX - this.dragStart.x;
      const dy = e.clientY - this.dragStart.y;
      if (!this.isPanning && Math.hypot(dx, dy) <= 5) return;
      if (this.dragStart.selection) {
        const coord = this.coordFromEvent(e);
        this.dragStart.selectionMoved = true;
        this.updateRangeSelection(this.selectionAnchor || this.dragStart.coord, coord);
        this.ensureCoordVisible(coord);
        return;
      }
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
      const selectionMoved = this.dragStart.selectionMoved;
      this.dragStart = null;
      this.isPanning = false;
      this.$refs.viewport.releasePointerCapture?.(e.pointerId);
      if (wasPanning) {
        window._bullpenSuppressWorkerClickUntil = Date.now() + 250;
      }
      if (selectionMoved) {
        this.focusViewport();
        return;
      }
      if (!wasPanning && !this.itemAtCoord(coord) && this.isWritableCoord(coord)) {
        this.selectCell(coord);
        this.focusViewport();
      }
    },
    onViewportDblClick(e) {
      if (e.target.closest('.worker-menu, button, input, select, textarea, .worker-card')) return;
      const coord = this.coordFromEvent(e);
      if (!this.isWritableCoord(coord) || this.itemAtCoord(coord)) return;
      e.preventDefault();
      this.openAddWorkerForEmptyCell(coord);
    },
    selectWorker(item, options = {}) {
      this.selectedCell = item.coord;
      this.selectionAnchor = { ...item.coord };
      if (!(options && options.preserveMultiple && this.selectedWorkerSlots.includes(item.slotIndex))) {
        this.selectedWorkerSlots = this.expandSelectionSlots([item.slotIndex]);
        this.selectedWorkerScope = this.selectedWorkerSlots.length > 1 ? 'connected-group' : 'item';
      }
      this.emptyMenuCoord = null;
      this.liveMessage = `Selected worker ${item.worker.name} at column ${item.coord.col}, row ${item.coord.row}`;
    },
    selectCell(coord) {
      this.selectedCell = { ...coord };
      this.selectionAnchor = { ...coord };
      const item = this.itemAtCoord(coord);
      this.selectedWorkerSlots = item ? this.expandSelectionSlots([item.slotIndex]) : [];
      this.selectedWorkerScope = this.selectedWorkerSlots.length > 1 ? 'connected-group' : (this.selectedWorkerSlots.length === 1 ? 'item' : 'none');
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      this.liveMessage = item
        ? `Selected worker ${item.worker.name} at column ${coord.col}, row ${coord.row}`
        : `Empty cell at column ${coord.col}, row ${coord.row}`;
    },
    selectA1() {
      this.selectedCell = { col: 0, row: 0 };
      this.selectionAnchor = { col: 0, row: 0 };
      this.selectedWorkerSlots = [];
      this.selectedWorkerScope = 'none';
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      this.focusViewport();
    },
    onWorkerClick(e, item) {
      if (window._bullpenSuppressWorkerClickUntil && Date.now() < window._bullpenSuppressWorkerClickUntil) return;
      if (e.target.closest('.card-height-resize-handle, .connect-handle, .status-pill, .worker-menu-btn, .worker-menu, button, input, select, textarea')) {
        return;
      }
      if (e.shiftKey) {
        const anchor = this.selectionAnchor || this.selectedCell || item.coord;
        this.updateRangeSelection(anchor, item.coord);
      } else if (e.metaKey || e.ctrlKey) {
        this.toggleWorkerSelection(item);
      } else {
        this.selectWorker(item);
      }
      this.focusViewport();
    },
    onValueEditEnded(item) {
      if (item?.coord) this.selectWorker(item, { preserveMultiple: true });
      this.focusViewport();
    },
    clearExpandedWorkerCard() {
      this.expandedWorkerCardSlot = null;
      this.expandedWorkerCardDelta = 0;
    },
    focusViewport() {
      this.$nextTick(() => {
        const el = this.$refs.viewport;
        if (el && document.activeElement !== el) el.focus({ preventScroll: true });
      });
    },
    isSelected(coord) {
      if (!coord) return false;
      const item = this.itemAtCoord(coord);
      if (item && this.selectedWorkerSlots.includes(item.slotIndex)) return true;
      return !!(this.selectedCell && this.selectedCell.col === coord.col && this.selectedCell.row === coord.row);
    },
    expandSelectionSlots(slots) {
      const out = new Set();
      for (const raw of slots || []) {
        const slot = Number(raw);
        if (!Number.isInteger(slot) || !this.workerItemBySlot[slot]) continue;
        for (const member of this.workerGroupSlots(slot)) out.add(member);
      }
      return Array.from(out);
    },
    slotsInRange(a, b) {
      if (!a || !b) return [];
      const colMin = Math.min(a.col, b.col);
      const colMax = Math.max(a.col, b.col);
      const rowMin = Math.min(a.row, b.row);
      const rowMax = Math.max(a.row, b.row);
      return this.workerItems
        .filter(item => item.coord.col >= colMin && item.coord.col <= colMax && item.coord.row >= rowMin && item.coord.row <= rowMax)
        .map(item => item.slotIndex);
    },
    updateRangeSelection(anchor, active) {
      if (!anchor || !active || !this.isWritableCoord(active)) return;
      this.selectionAnchor = { ...anchor };
      this.selectedCell = { ...active };
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      this.selectedWorkerSlots = this.expandSelectionSlots(this.slotsInRange(anchor, active));
      this.selectedWorkerScope = this.selectedWorkerSlots.length > 1 ? 'selection' : (this.selectedWorkerSlots.length === 1 ? 'item' : 'none');
      const count = this.selectedWorkerSlots.length;
      this.liveMessage = count > 1
        ? `Selected ${count} workers`
        : `Selected range ending at column ${active.col}, row ${active.row}`;
    },
    toggleWorkerSelection(item) {
      const current = new Set(this.selectedWorkerSlots);
      const group = this.workerGroupSlots(item.slotIndex);
      const selected = group.some(slot => current.has(slot));
      for (const slot of group) {
        if (selected) current.delete(slot);
        else current.add(slot);
      }
      this.selectedCell = { ...item.coord };
      this.selectionAnchor = { ...item.coord };
      this.selectedWorkerSlots = Array.from(current);
      this.selectedWorkerScope = this.selectedWorkerSlots.length > 1 ? 'selection' : (this.selectedWorkerSlots.length === 1 ? 'item' : 'none');
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      this.liveMessage = this.selectedWorkerSlots.length > 1
        ? `Selected ${this.selectedWorkerSlots.length} workers`
        : `Selected worker ${item.worker.name} at column ${item.coord.col}, row ${item.coord.row}`;
    },
    topLeftCoordForSlots(slots) {
      let coord = null;
      for (const rawSlot of slots || []) {
        const slot = Number(rawSlot);
        const item = Number.isInteger(slot) ? this.workerItemBySlot[slot] : null;
        if (!item?.coord) continue;
        coord = coord
          ? {
              col: Math.min(coord.col, item.coord.col),
              row: Math.min(coord.row, item.coord.row),
            }
          : { ...item.coord };
      }
      return coord;
    },
    moveCursorToDeletedWorkerRegion(slots) {
      const coord = this.topLeftCoordForSlots(slots);
      if (!coord || !this.isWritableCoord(coord)) return;
      this.selectedCell = { ...coord };
      this.selectionAnchor = { ...coord };
      this.selectedWorkerSlots = [];
      this.selectedWorkerScope = 'none';
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      this.liveMessage = `Empty cell at column ${coord.col}, row ${coord.row}`;
      this.ensureCoordVisible(coord);
      this.focusViewport();
    },
    isDragOverGhost(coord) {
      return !!(this.dragOverCoord && coord &&
        this.dragOverCoord.col === coord.col &&
        this.dragOverCoord.row === coord.row);
    },
    printableValueShortcutKey(e) {
      if (!e || e.metaKey || e.ctrlKey || e.altKey) return '';
      if (e.key && e.key.length === 1) return e.key;
      return '';
    },
    valueShortcutTargetCoord() {
      const coord = this.selectedCell || this.ghostCell;
      if (coord && this.isWritableCoord(coord) && !this.itemAtCoord(coord)) return coord;
      return null;
    },
    parseValueShortcutText(text) {
      const raw = String(text || '');
      if (!raw.trim()) return { error: 'Enter a value.' };
      let name = '';
      let unit = '';
      let value = raw.trim();
      // Formula source owns every character after the leading =, including
      // range and string-literal colons.  The apostrophe form is the matching
      // literal escape and must follow the same no-splitting rule.
      if (value.startsWith('=') || value.startsWith("'=")) {
        return {
          fields: {
            name,
            unit,
            value,
            value_type: 'auto',
            format: { kind: 'general' },
          },
        };
      }
      const colon = raw.indexOf(':');
      if (colon >= 0) {
        const label = raw.slice(0, colon).trim();
        const slash = label.lastIndexOf('/');
        name = (slash >= 0 ? label.slice(0, slash) : label).trim();
        unit = slash >= 0 ? label.slice(slash + 1).trim() : '';
        value = raw.slice(colon + 1).trim() || null;
      }
      if (value === '') return { error: 'Enter a value.' };
      return {
        fields: {
          name,
          unit,
          value,
          value_type: 'auto',
          format: { kind: 'general' },
        },
      };
    },
    parseWorksheetClipboardText(text) {
      const raw = String(text ?? '');
      if (!raw) return null;
      const rows = [];
      let row = [];
      let cell = '';
      let inQuotes = false;
      for (let i = 0; i < raw.length; i++) {
        const ch = raw[i];
        if (inQuotes) {
          if (ch === '"') {
            if (raw[i + 1] === '"') {
              cell += '"';
              i += 1;
            } else {
              inQuotes = false;
            }
          } else {
            cell += ch;
          }
          continue;
        }
        if (ch === '"' && cell === '') {
          inQuotes = true;
        } else if (ch === '\t') {
          row.push(cell);
          cell = '';
        } else if (ch === '\n' || ch === '\r') {
          row.push(cell);
          cell = '';
          rows.push(row);
          row = [];
          if (ch === '\r' && raw[i + 1] === '\n') i += 1;
        } else {
          cell += ch;
        }
      }
      row.push(cell);
      rows.push(row);
      while (rows.length && rows[rows.length - 1].length === 1 && rows[rows.length - 1][0] === '') {
        rows.pop();
      }
      if (!rows.length) return null;
      const width = Math.max(...rows.map(r => r.length));
      if (width <= 0) return null;
      return rows.map(r => {
        const normalized = r.slice();
        while (normalized.length < width) normalized.push('');
        return normalized;
      });
    },
    worksheetPasteTargetsForCoord(coord, text) {
      const rows = this.parseWorksheetClipboardText(text);
      if (!rows || !coord || !this.isWritableCoord(coord)) return [];
      const targets = [];
      for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
        for (let colIndex = 0; colIndex < rows[rowIndex].length; colIndex++) {
          if (!String(rows[rowIndex][colIndex] ?? '').trim()) continue;
          targets.push({
            coord: {
              col: coord.col + colIndex,
              row: coord.row + rowIndex,
            },
            worker: {
              type: 'value',
              name: '',
              unit: '',
              value: rows[rowIndex][colIndex],
              value_type: 'auto',
              format: { kind: 'general' },
              _raw_value_input: true,
            },
          });
        }
      }
      return targets;
    },
    validateWorksheetPasteTargets(targets) {
      if (!targets.length) return 'Clipboard does not contain worksheet values';
      const seen = new Set();
      const outside = [];
      const occupied = [];
      for (const target of targets) {
        const label = GridGeometry.coordToCellRef?.(target.coord) || `(${target.coord.col}, ${target.coord.row})`;
        if (!this.isWritableCoord(target.coord)) {
          outside.push(label);
          continue;
        }
        const key = GridGeometry.coordKey(target.coord.col, target.coord.row);
        if (seen.has(key)) return 'Worksheet paste contains duplicate target cells';
        seen.add(key);
        if (this.itemAtCoord(target.coord)) occupied.push(label);
      }
      if (outside.length) return `Cannot paste: ${outside.join(', ')} ${outside.length === 1 ? 'is' : 'are'} outside the grid`;
      if (occupied.length) return `Cannot paste: ${occupied.join(', ')} ${occupied.length === 1 ? 'is' : 'are'} occupied`;
      return '';
    },
    showPasteError(message) {
      if (typeof this.$root?.addToast === 'function') {
        this.$root.addToast(message, 'error');
      }
      this.liveMessage = message;
    },
    showPasteSuccess(message) {
      if (typeof this.$root?.addToast === 'function') {
        this.$root.addToast(message, 'success');
      }
      this.liveMessage = message;
    },
    pasteWorksheetCells(coord, text) {
      const rows = this.parseWorksheetClipboardText(text);
      if (!rows) {
        this.showPasteError('Clipboard does not contain worksheet values');
        return false;
      }
      const targets = this.worksheetPasteTargetsForCoord(coord, text);
      const error = this.validateWorksheetPasteTargets(targets);
      if (error) {
        this.showPasteError(error);
        return false;
      }
      if (typeof this.$root.pasteWorkerGroup === 'function') {
        this.$root.pasteWorkerGroup(targets);
      } else {
        for (const target of targets) {
          this.$root.pasteWorkerConfig({ coord: target.coord, worker: target.worker });
        }
      }
      const rowCount = rows.length;
      const colCount = Math.max(...rows.map(row => row.length));
      const blankCount = (rowCount * colCount) - targets.length;
      const countLabel = `${targets.length} ${targets.length === 1 ? 'Value' : 'Values'} created`;
      const blankLabel = blankCount ? `, ${blankCount} blank ${blankCount === 1 ? 'cell' : 'cells'} skipped` : '';
      this.showPasteSuccess(`Pasted ${rowCount}×${colCount} range: ${countLabel}${blankLabel}`);
      this.emptyMenuCoord = null;
      return true;
    },
    onPaste(e) {
      const target = e?.target;
      if (target && (target.isContentEditable || target.matches?.('input, textarea, select'))) return;
      const coord = this.selectedCell;
      if (!coord || !this.isWritableCoord(coord)) return;
      const text = e?.clipboardData?.getData?.('text/plain');
      if (typeof text !== 'string' || !text) return;
      e.preventDefault?.();
      this.pasteWorksheetCells(coord, text);
    },
    openValueShortcutEditor(coord, initialText = '') {
      if (!coord || !this.isWritableCoord(coord) || this.itemAtCoord(coord)) return;
      this.closeEmptyMenu();
      this.valueShortcutEditor = {
        coord: { ...coord },
        text: initialText,
        error: '',
      };
      this.selectedCell = { ...coord };
      this.$nextTick(() => {
        const input = this.$refs.valueShortcutInput;
        if (input && typeof input.focus === 'function') {
          input.focus();
          const end = input.value.length;
          input.setSelectionRange?.(end, end);
        }
      });
    },
    closeValueShortcutEditor({ focusViewport = true } = {}) {
      this.valueShortcutEditor = null;
      if (focusViewport) this.$nextTick(() => this.$refs.viewport?.focus());
    },
    commitValueShortcutEditor({ openModal = false } = {}) {
      const editor = this.valueShortcutEditor;
      if (!editor?.coord) return;
      const parsed = this.parseValueShortcutText(editor.text);
      if (parsed.error) {
        editor.error = parsed.error;
        return;
      }
      if (openModal) {
        this.selectedAddCoord = { ...editor.coord };
        this.closeValueShortcutEditor({ focusViewport: false });
        this.createWorkerAndOpenConfig({ type: 'value', fields: parsed.fields });
        return;
      }
      this.$emit('add-worker', {
        coord: { ...editor.coord },
        type: 'value',
        fields: parsed.fields,
      });
      this.closeValueShortcutEditor();
    },
    onValueShortcutKeydown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.closeValueShortcutEditor();
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        this.commitValueShortcutEditor({ openModal: e.metaKey || e.ctrlKey });
      }
    },
    onKeydown(e) {
      const t = e.target;
      const inTextInput = t && (t.isContentEditable || (typeof t.matches === 'function' && t.matches('input, textarea, select')));
      const valueShortcutTarget = (!inTextInput && !this.emptyMenuCoord && !this.showLibrary && !this.showGoTo && !this.showHelp)
        ? this.valueShortcutTargetCoord()
        : null;
      if (this.emptyMenuCoord && !inTextInput && !e.metaKey && !e.ctrlKey && !e.altKey) {
        if (['ArrowUp', 'ArrowDown', 'Home', 'End', 'Escape'].includes(e.key)) {
          this.onEmptyMenuKeydown(e);
          return;
        }
      }
      if (!inTextInput && !e.metaKey && !e.ctrlKey && !e.altKey && e.key === '?') {
        e.preventDefault();
        this.openHelp();
        return;
      }
      if (!inTextInput && (e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'g') {
        e.preventDefault();
        this.openGoTo();
        return;
      }
      if (!inTextInput && (e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'c') {
        const item = this.isExplicitSelectionActive
          ? this.workerItemBySlot[this.selectedWorkerSlots[0]]
          : this.itemAtCoord(this.selectedCell);
        if (!item) return;
        e.preventDefault();
        this.copyWorker(item.slotIndex, this.isExplicitSelectionActive ? 'selection' : 'item');
        return;
      }
      if (!inTextInput && !e.metaKey && !e.ctrlKey && (e.key === 'Delete' || e.key === 'Backspace')) {
        if (this.isExplicitSelectionActive) {
          e.preventDefault();
          const slots = this.selectedWorkerSlots.slice();
          if (this.$root.removeWorkers(slots) === true) this.moveCursorToDeletedWorkerRegion(slots);
          return;
        }
        if (!this.selectedCell) return;
        const item = this.itemAtCoord(this.selectedCell);
        if (!item) return;
        e.preventDefault();
        if (this.$root.removeWorker(item.slotIndex) === true) this.moveCursorToDeletedWorkerRegion([item.slotIndex]);
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
        if (e.shiftKey) {
          const anchor = this.selectionAnchor || origin;
          this.updateRangeSelection(anchor, next);
          this.ensureCoordVisible(next);
          return;
        }
        const item = this.itemAtCoord(next);
        if (item) {
          this.selectWorker(item);
        } else {
          this.selectCell(next);
        }
        this.ensureCoordVisible(next);
        return;
      }
      if (e.key === 'Home') {
        e.preventDefault();
        this.jumpHome();
      } else if (e.key.toLowerCase() === 'f' && !valueShortcutTarget) {
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
      if (e.defaultPrevented) return;
      const shortcutKey = this.printableValueShortcutKey(e);
      if (shortcutKey && valueShortcutTarget) {
        e.preventDefault();
        this.openValueShortcutEditor(valueShortcutTarget, shortcutKey);
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
    openGoTo() {
      this.showGoTo = true;
      this.goToInput = '';
      this.goToWorkerSlot = '';
      this.goToError = '';
      this.$nextTick(() => this.$refs.goToInputEl?.focus());
    },
    closeGoTo() {
      this.showGoTo = false;
      this.goToWorkerSlot = '';
      this.goToError = '';
      this.$nextTick(() => this.$refs.viewport?.focus());
    },
    onGoToCellInput() {
      this.goToError = '';
      if ((this.goToInput || '').trim()) this.goToWorkerSlot = '';
    },
    onGoToWorkerSelect() {
      this.goToError = '';
      if (this.goToWorkerSlot) this.goToInput = '';
    },
    openHelp() {
      this.showHelp = true;
    },
    closeHelp() {
      this.showHelp = false;
      this.$nextTick(() => this.$refs.viewport?.focus());
    },
    openHelp() {
      this.showHelp = true;
      this.$nextTick(() => this.$refs.helpOverlay?.focus());
    },
    closeHelp() {
      this.showHelp = false;
      this.$nextTick(() => this.$refs.viewport?.focus());
    },
    parseCellRef(text) {
      return GridGeometry.parseCellRef(text);
    },
    goToCoord(coord) {
      const visibleCols = this.viewportPx.width / this.columnWidth;
      const visibleRows = this.viewportPx.height / this.rowHeight;
      const isVisible =
        coord.col + 1 > this.viewportOrigin.col &&
        coord.col < this.viewportOrigin.col + visibleCols &&
        coord.row + 1 > this.viewportOrigin.row &&
        coord.row < this.viewportOrigin.row + visibleRows;
      if (!isVisible) {
        this.setOrigin({ col: coord.col, row: coord.row });
      }
      const item = this.itemAtCoord(coord);
      if (item) {
        this.selectWorker(item);
      } else {
        this.selectedCell = { ...coord };
        this.emptyMenuCoord = null;
        this.emptyMenuPos = null;
      }
    },
    submitGoTo() {
      if (this.goToWorkerSlot !== '') {
        const slot = Number.parseInt(this.goToWorkerSlot, 10);
        const selected = this.workerItemBySlot[slot];
        if (selected) {
          this.goToCoord(selected.coord);
          this.closeGoTo();
          return;
        }
      }
      const text = (this.goToInput || '').trim();
      if (!text) { this.closeGoTo(); return; }
      const cellRef = this.parseCellRef(text);
      if (cellRef && this.isWritableCoord(cellRef)) {
        this.goToCoord(cellRef);
        this.closeGoTo();
        return;
      }
      const needle = text.toLowerCase();
      let match = this.workerItems.find(it => (it.worker?.name || '').toLowerCase() === needle);
      if (!match) {
        match = this.workerItems.find(it => (it.worker?.name || '').toLowerCase().startsWith(needle));
      }
      if (!match) {
        match = this.workerItems.find(it => (it.worker?.name || '').toLowerCase().includes(needle));
      }
      if (match) {
        this.goToCoord(match.coord);
        this.closeGoTo();
        return;
      }
      this.goToError = `No worker or cell matches "${text}"`;
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
      this.emptyMenuAnchorPos = null;
      if (focusViewport) {
        this.$nextTick(() => this.$refs.viewport?.focus());
      }
    },
    openEmptyMenu(coord, e) {
      if (!this.isWritableCoord(coord) || this.itemAtCoord(coord)) return;
      this.selectedCell = { ...coord };
      this.emptyMenuCoord = { ...coord };
      if (e && Number.isFinite(e.clientX) && Number.isFinite(e.clientY)) {
        this.emptyMenuAnchorPos = { x: e.clientX, y: e.clientY };
        this.emptyMenuPos = { ...this.emptyMenuAnchorPos };
      } else {
        this.emptyMenuAnchorPos = null;
        this.emptyMenuPos = null;
      }
      this.liveMessage = `Empty cell at column ${coord.col}, row ${coord.row}`;
      this.$nextTick(() => {
        this.repositionEmptyMenuWithinViewport();
        const menu = this.$refs.emptyMenu;
        if (menu && typeof menu.focus === 'function') menu.focus();
        const [first] = this.emptyMenuItems();
        if (first && typeof first.focus === 'function') first.focus();
      });
    },
    repositionEmptyMenuWithinViewport() {
      if (!this.emptyMenuCoord) return;
      const menu = this.$refs.emptyMenu;
      if (!menu || typeof menu.getBoundingClientRect !== 'function') return;
      let anchor = this.emptyMenuAnchorPos;
      if (!anchor && this.emptyMenuPos) anchor = this.emptyMenuPos;
      if (!anchor) {
        const rect = menu.getBoundingClientRect();
        anchor = { x: rect.left, y: rect.top };
        this.emptyMenuAnchorPos = anchor;
      }
      const margin = 8;
      const rect = menu.getBoundingClientRect();
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
      const maxX = Math.max(margin, viewportWidth - rect.width - margin);
      const maxY = Math.max(margin, viewportHeight - rect.height - margin);
      const x = Math.min(Math.max(anchor.x, margin), maxX);
      const y = Math.min(Math.max(anchor.y, margin), maxY);
      if (!this.emptyMenuPos || x !== this.emptyMenuPos.x || y !== this.emptyMenuPos.y) {
        this.emptyMenuPos = { x, y };
      }
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
      this.libraryMode = 'ai';
      this.showLibrary = true;
      this.emptyMenuCoord = null;
      this.emptyMenuPos = null;
      this.loadShellExamples();
      this.$nextTick(() => this.$refs.libraryOverlay?.focus());
    },
    openAddWorkerForEmptyCell(coord) {
      if (!this.isWritableCoord(coord) || this.itemAtCoord(coord)) return;
      this.selectCell(coord);
      this.openLibraryForCoord(coord);
    },
    async loadShellExamples() {
      if (this.shellExamplesLoaded) return;
      this.shellExamplesLoaded = true;
      try {
        const res = await fetch('/shell_worker_examples.json', { credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        this.shellExamples = Array.isArray(data?.examples) ? data.examples : [];
      } catch (_err) {
        this.shellExamplesLoaded = false;
      }
    },
    closeLibrary() {
      this.showLibrary = false;
      this.selectedAddCoord = null;
      this.$nextTick(() => this.$refs.viewport?.focus());
    },
    clearPendingWorkerAdd() {
      if (this.pendingWorkerAddTimer) {
        clearTimeout(this.pendingWorkerAddTimer);
        this.pendingWorkerAddTimer = null;
      }
      this.pendingWorkerAdd = null;
    },
    resolvePendingWorkerAdd() {
      const pending = this.pendingWorkerAdd;
      if (!pending?.coord) return;
      const item = this.itemAtCoord(pending.coord);
      if (!item) return;
      if (pending.type && item.worker?.type !== pending.type) return;
      this.clearPendingWorkerAdd();
      this.$emit('configure-worker', item.slotIndex);
    },
    createWorkerAndOpenConfig({ type, profile, fields }) {
      if (this.pendingWorkerAdd) return;
      const coord = this.selectedAddCoord ? { ...this.selectedAddCoord } : null;
      this.pendingWorkerAdd = { coord, type };
      if (this.pendingWorkerAddTimer) clearTimeout(this.pendingWorkerAddTimer);
      this.pendingWorkerAddTimer = setTimeout(() => {
        this.pendingWorkerAddTimer = null;
        this.pendingWorkerAdd = null;
      }, 5000);
      this.$emit('add-worker', {
        coord,
        profile,
        type,
        fields,
      });
      this.closeLibrary();
    },
    addFromLibrary(profileId) {
      this.createWorkerAndOpenConfig({ profile: profileId, type: 'ai' });
    },
    addShellWorker(example) {
      const fields = { name: 'Shell worker', activation: 'on_drop' };
      if (example && typeof example === 'object') {
        if (example.name) fields.name = example.name;
        if (example.command) fields.command = example.command;
        if (example.ticket_delivery) fields.ticket_delivery = example.ticket_delivery;
        if (example.disposition) fields.disposition = example.disposition;
        if (Number.isFinite(example.max_retries)) fields.max_retries = example.max_retries;
        if (Array.isArray(example.env)) {
          fields.env = example.env
            .filter(e => e && e.key)
            .map(e => ({ key: String(e.key), value: String(e.value || '') }));
        }
      }
      this.createWorkerAndOpenConfig({
        type: 'shell',
        fields,
      });
    },
    addServiceWorker() {
      this.createWorkerAndOpenConfig({
        type: 'service',
        fields: {
          name: 'Service worker',
          activation: 'manual',
          ticket_action: 'start-if-stopped-else-restart',
        },
      });
    },
    addMarkerWorker() {
      this.createWorkerAndOpenConfig({
        type: 'marker',
        fields: {
          name: 'Marker',
          note: '',
          activation: 'on_drop',
          disposition: 'review',
        },
      });
    },
    addNotificationWorker() {
      this.createWorkerAndOpenConfig({
        type: 'notification',
        fields: {
          name: 'Notification worker',
          activation: 'on_drop',
          disposition: 'review',
        },
      });
    },
    addValueWorker() {
      this.createWorkerAndOpenConfig({
        type: 'value',
        fields: {
          name: '',
          unit: '',
          value: '',
          value_type: 'auto',
          format: { kind: 'general' },
          save_history: true,
        },
      });
    },
    nextEmptySlotIndex() {
      const slots = this.layout?.slots || [];
      const idx = slots.findIndex(slot => !slot);
      return idx >= 0 ? idx : slots.length;
    },
    workerFieldsForClipboard(worker) {
      const fields = ['type', 'profile', 'name', 'note', 'agent', 'model', 'activation', 'disposition', 'watch_column', 'expertise_prompt', 'trust_mode',
        'max_retries', 'use_worktree', 'auto_commit', 'auto_pr', 'trigger_time', 'trigger_interval_minutes',
        'trigger_every_day', 'command', 'cwd', 'timeout_seconds', 'ticket_delivery', 'env',
        'pre_start', 'ticket_action', 'startup_grace_seconds', 'startup_timeout_seconds',
        'health_type', 'health_url', 'health_command', 'health_interval_seconds',
        'health_timeout_seconds', 'health_failure_threshold', 'on_crash',
        'stop_timeout_seconds', 'log_max_bytes', 'color', 'avatar'];
      fields.push('value', 'value_type', 'resolved_value_type', 'unit', 'format', 'save_history', 'icon', 'updated_at');
      fields.push('notification');
      const copy = {};
      for (const key of fields) {
        if (worker[key] !== undefined) copy[key] = JSON.parse(JSON.stringify(worker[key]));
      }
      return copy;
    },
    passTargetsForSlot(slotIndex) {
      const item = this.workerItemBySlot[slotIndex];
      if (!item) return [];
      return this.passTargetsBySlot[slotIndex] || [];
    },
    passSourcesForSlot(slotIndex) {
      const target = Number(slotIndex);
      if (!Number.isInteger(target) || !this.workerItemBySlot[target]) return [];
      return this.passSourcesBySlot[target] || [];
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
    workerMenuContext(slotIndex) {
      const slot = Number(slotIndex);
      if (!Number.isInteger(slot) || !this.workerItemBySlot[slot]) {
        return {
          itemSlot: null,
          connectedGroupSlots: [],
          selectionSlots: [],
          hasConnectedGroup: false,
          hasSelection: false,
        };
      }
      const connectedGroupSlots = this.workerGroupSlots(slot);
      const selectionSlots = this.isExplicitSelectionActive && this.selectedWorkerSlots.includes(slot)
        ? this.expandSelectionSlots(this.selectedWorkerSlots)
        : [];
      return {
        itemSlot: slot,
        connectedGroupSlots,
        selectionSlots,
        hasConnectedGroup: connectedGroupSlots.length > 1,
        hasSelection: selectionSlots.length > 1,
      };
    },
    slotsForMenuScope(slotIndex, scope) {
      const ctx = this.workerMenuContext(slotIndex);
      if (scope === 'connected-group') return ctx.connectedGroupSlots.slice();
      if (scope === 'selection') return ctx.selectionSlots.slice();
      return Number.isInteger(ctx.itemSlot) ? [ctx.itemSlot] : [];
    },
    buildWorkerDragPayload(slotIndex, options = {}) {
      const source = Number(slotIndex);
      const pointerOffset = this._workerDragPointerOffset(source, options);
      if (options.singleton) return { source, group: [source], pointerOffset, singleton: true };
      const group = this.selectedWorkerSlots.includes(source)
        ? this.expandSelectionSlots(this.selectedWorkerSlots)
        : this.workerGroupSlots(source);
      return { source, group: group.length ? group : [source], pointerOffset, singleton: false };
    },
    buildWorkerDragImage(slotIndex, pointer = {}, options = {}) {
      const source = Number(slotIndex);
      const sourceItem = this.workerItemBySlot[source];
      if (!sourceItem) return null;
      const slots = options.singleton
        ? [source]
        : (this.selectedWorkerSlots.includes(source) ? this.expandSelectionSlots(this.selectedWorkerSlots) : this.workerGroupSlots(source));
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
      const height = this.rowSpanHeight(minRow, maxRow);
      const root = document.createElement('div');
      root.className = 'worker-group-drag-image';
      root.style.width = `${width}px`;
      root.style.height = `${height}px`;
      const sourceDx = (sourceItem.coord.col - minCol) * this.columnWidth;
      const sourceDy = this.rowOffsetBetween(minRow, sourceItem.coord.row);
      for (const item of items) {
        const slot = item.slotIndex;
        const left = (item.coord.col - minCol) * this.columnWidth;
        const top = this.rowOffsetBetween(minRow, item.coord.row);
        const height = this.rowHeightForRow(item.coord.row);
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
        node.style.height = `${height}px`;
        node.style.margin = '0';
        root.appendChild(node);
      }
      document.body.appendChild(root);
      const pointerOffset = this._workerDragPointerOffset(source, pointer);
      const pointerDx = pointerOffset.x;
      const pointerDy = pointerOffset.y;
      return {
        element: root,
        offsetX: sourceDx + pointerDx,
        offsetY: sourceDy + pointerDy,
      };
    },
    _workerDragPointerOffset(slotIndex, pointer = {}) {
      const source = Number(slotIndex);
      const sourceEl = this.workerElementForSlot(source);
      let x = this.columnWidth / 2;
      const sourceItem = this.workerItemBySlot[source];
      let y = (sourceItem ? this.rowHeightForRow(sourceItem.coord.row) : this.rowHeight) / 2;
      if (sourceEl && Number.isFinite(Number(pointer.clientX)) && Number.isFinite(Number(pointer.clientY))) {
        const rect = sourceEl.getBoundingClientRect();
        x = Math.max(0, Math.min(rect.width, Number(pointer.clientX) - rect.left));
        y = Math.max(0, Math.min(rect.height, Number(pointer.clientY) - rect.top));
      }
      return { x, y };
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
    _dragGroupSlots() {
      const payload = window._bullpenWorkerDrag;
      return Array.isArray(payload?.group) ? payload.group : null;
    },
    _isSingletonWorkerDrag() {
      return window._bullpenWorkerDrag?.singleton === true;
    },
    _isWorkerDrag(e) {
      const types = Array.from(e?.dataTransfer?.types || []);
      return !!window._bullpenWorkerDrag || types.includes('application/x-worker-slot') || types.includes('application/x-worker-group');
    },
    _workerDragCoordFromEvent(e) {
      const offset = window._bullpenWorkerDrag?.pointerOffset;
      const offsetX = Number(offset?.x);
      const offsetY = Number(offset?.y);
      if (!Number.isFinite(offsetX) || !Number.isFinite(offsetY)) return this.coordFromEvent(e);
      const rect = this.dragViewportRect || this.$refs.viewport.getBoundingClientRect();
      const x = e.clientX - rect.left - this.headerWidth - offsetX;
      const y = e.clientY - rect.top - this.headerHeight - offsetY;
      return {
        col: Math.floor((Number(this.viewportOrigin.col) || 0) + (Number(x) || 0) / this.columnWidth),
        row: this.rowFromPixel(y),
      };
    },
    buildGroupMovePlan(sourceSlot, destinationCoord, overrideSlots) {
      const source = Number(sourceSlot);
      if (!Number.isInteger(source) || !destinationCoord || !this.isWritableCoord(destinationCoord)) return null;
      const anchor = this.workerItemBySlot[source];
      if (!anchor) return null;
      const slots = overrideSlots || this.workerGroupSlots(source);
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
    canDropWorkerAtSlot(sourceSlot, targetSlot, e) {
      if (e && !this.dragViewportRect) this.dragViewportRect = this.$refs.viewport.getBoundingClientRect();
      const coord = e ? this._workerDragCoordFromEvent(e) : null;
      if (coord) return this._setDropTarget(sourceSlot, coord);
      const target = this.workerItemBySlot[targetSlot];
      if (!target) return false;
      return this._setDropTarget(sourceSlot, target.coord);
    },
    canDropWorkerAtCoord(sourceSlot, coord) {
      if (this._isSingletonWorkerDrag()) {
        const source = Number(sourceSlot);
        return Number.isInteger(source) && !!this.workerItemBySlot[source] && !!coord && this.isWritableCoord(coord);
      }
      return !!this.buildGroupMovePlan(sourceSlot, coord, this._dragGroupSlots());
    },
    dropWorkerOnSlot(sourceSlot, targetSlot, e) {
      const coord = e ? this._workerDragCoordFromEvent(e) : null;
      this._clearDropTarget();
      this.dragViewportRect = null;
      if (coord) return this.moveWorkerDragToCoord(sourceSlot, coord);
      const target = this.workerItemBySlot[targetSlot];
      if (!target) return false;
      return this.moveWorkerDragToCoord(sourceSlot, target.coord);
    },
    updateSingletonWorkerDrag(sourceSlot, e) {
      if (e && !this.dragViewportRect) this.dragViewportRect = this.$refs.viewport.getBoundingClientRect();
      const source = Number(sourceSlot);
      const coord = this._workerDragCoordFromEvent(e);
      if (Number.isInteger(source) && coord && this._setDropTarget(source, coord)) {
        this.hoveredCoord = coord;
        return true;
      }
      this.hoveredCoord = null;
      this._clearDropTarget();
      return false;
    },
    endSingletonWorkerDrag(sourceSlot, e) {
      const source = Number(sourceSlot);
      const coord = this._workerDragCoordFromEvent(e);
      this.hoveredCoord = null;
      this._clearDropTarget();
      this.dragViewportRect = null;
      if (!Number.isInteger(source) || !coord) return false;
      return this.moveSingleWorkerToCoord(source, coord);
    },
    cancelSingletonWorkerDrag() {
      this.hoveredCoord = null;
      this._clearDropTarget();
      this.dragViewportRect = null;
    },
    moveWorkerDragToCoord(sourceSlot, coord) {
      if (this._isSingletonWorkerDrag()) {
        return this.moveSingleWorkerToCoord(sourceSlot, coord);
      }
      return this.moveWorkerGroupToCoord(sourceSlot, coord);
    },
    moveSingleWorkerToCoord(sourceSlot, coord) {
      const source = Number(sourceSlot);
      const sourceItem = this.workerItemBySlot[source];
      if (!Number.isInteger(source) || !sourceItem || !coord || !this.isWritableCoord(coord)) return false;
      const occupied = this.itemAtCoord(coord);
      if (occupied && occupied.slotIndex === source) return true;
      if (occupied) {
        this.$root.moveWorker(source, occupied.slotIndex);
      } else {
        this.$root.moveWorker(source, coord);
      }
      this.hoveredCoord = null;
      this.emptyMenuCoord = null;
      this.selectedCell = { ...coord };
      this.selectionAnchor = { ...coord };
      this.selectedWorkerSlots = [source];
      this.selectedWorkerScope = 'item';
      return true;
    },
    moveWorkerGroupToCoord(sourceSlot, coord) {
      const plan = this.buildGroupMovePlan(sourceSlot, coord, this._dragGroupSlots());
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
      const sourceMove = plan.moves.find(m => Number(m.slot) === Number(sourceSlot));
      if (sourceMove && sourceMove.to_coord) {
        this.selectedCell = { ...sourceMove.to_coord };
      } else {
        this.selectedCell = { ...coord };
      }
      this.selectionAnchor = { ...this.selectedCell };
      this.selectedWorkerSlots = plan.slots.slice();
      this.selectedWorkerScope = plan.slots.length > 1 ? 'connected-group' : 'item';
      return true;
    },
    handleWorkerScopeAction(payload) {
      const slot = Number(payload?.slot);
      const scope = payload?.scope || 'item';
      const action = payload?.action || '';
      const slots = this.slotsForMenuScope(slot, scope);
      if (!slots.length) return;
      if (action === 'pause' || action === 'unpause') {
        const paused = action === 'pause';
        if (slots.length === 1) this.$root.saveWorkerConfig({ slot: slots[0], fields: { paused } });
        else this.$root.saveWorkersConfig({ slots, fields: { paused } });
        this.liveMessage = `${paused ? 'Paused' : 'Unpaused'} ${scope === 'item' ? 'worker' : `${slots.length} workers`}`;
        return;
      }
      if (action === 'stop') {
        if (slots.length === 1) this.$root.stopWorkerSlot(slots[0]);
        else this.$root.stopWorkerSlots(slots);
        this.liveMessage = `Stop requested for ${slots.length} worker${slots.length === 1 ? '' : 's'}`;
        return;
      }
      if (action === 'copy') {
        this.copyWorker(slot, scope);
        return;
      }
      if (action === 'duplicate') {
        if (slots.length === 1) this.$root.duplicateWorker(slots[0]);
        else this.$root.duplicateWorkers(slots);
        return;
      }
      if (action === 'export') {
        this.$root.exportWorkerGroup(slots);
        return;
      }
      if (action === 'copy-to' || action === 'move-to') {
        this.$emit('transfer-worker', {
          slot,
          slots,
          mode: action === 'move-to' ? 'move' : 'copy',
        });
        return;
      }
      if (action === 'delete') {
        this.deleteWorkerFromMenu(slot, scope);
      }
    },
    copyWorker(slot, scope = 'item') {
      const source = this.workerItemBySlot[slot];
      if (!source) return;
      const slots = this.slotsForMenuScope(slot, scope);
      const workers = slots.map(memberSlot => {
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
    deleteWorkerFromMenu(slot, scope = 'item') {
      const source = Number(slot);
      if (!Number.isInteger(source) || !this.workerItemBySlot[source]) return;
      const slots = this.slotsForMenuScope(source, scope);
      let deleted = false;
      if (slots.length > 1 && typeof this.$root.removeWorkers === 'function') {
        deleted = this.$root.removeWorkers(slots) === true;
      } else {
        deleted = this.$root.removeWorker(source) === true;
      }
      if (deleted) this.moveCursorToDeletedWorkerRegion(slots.length ? slots : [source]);
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
    pasteWorkerFromMenu(coord) {
      this.pasteWorker(coord);
      this.closeEmptyMenu({ focusViewport: true });
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
      const singleton = this._isSingletonWorkerDrag();
      const key = `${singleton ? 'single' : 'group'}:${source}:${coord?.col},${coord?.row}`;
      if (coord && this.lastDropTargetKey === key) return true;
      if (this._isSingletonWorkerDrag()) {
        if (!this.canDropWorkerAtCoord(source, coord)) {
          this.dragOverCoord = null;
          this.dropTargetCoords = [];
          this.lastDropTargetKey = '';
          return false;
        }
        this.lastDropTargetKey = key;
        this.dragOverCoord = { ...coord };
        this.dropTargetCoords = [{ col: coord.col, row: coord.row }];
        return true;
      }
      const plan = this.buildGroupMovePlan(source, coord, this._dragGroupSlots());
      if (!plan) {
        this.dragOverCoord = null;
        this.dropTargetCoords = [];
        this.lastDropTargetKey = '';
        return false;
      }
      this.lastDropTargetKey = key;
      this.dragOverCoord = { ...coord };
      this.dropTargetCoords = plan.moves.map(m => ({ col: m.to_coord.col, row: m.to_coord.row }));
      return true;
    },
    _clearDropTarget() {
      this.dragOverCoord = null;
      this.dropTargetCoords = [];
      this.lastDropTargetKey = '';
    },
    onEmptyDragOver(e, coord) {
      if (!this._isWorkerDrag(e)) return;
      const source = this._workerDragSource(e);
      const dropCoord = this._workerDragCoordFromEvent(e) || coord;
      if (Number.isInteger(source) && this._setDropTarget(source, dropCoord)) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      } else {
        e.dataTransfer.dropEffect = 'none';
        this._clearDropTarget();
      }
    },
    onDropOnEmpty(e, coord) {
      const source = this._workerDragSource(e);
      const dropCoord = this._workerDragCoordFromEvent(e) || coord;
      this._clearDropTarget();
      this.dragViewportRect = null;
      if (!Number.isInteger(source)) return false;
      return this.moveWorkerDragToCoord(source, dropCoord);
    },
    onCanvasDragOver(e) {
      if (!this._isWorkerDrag(e)) return;
      if (!this.dragViewportRect) this.dragViewportRect = this.$refs.viewport.getBoundingClientRect();
      const source = this._workerDragSource(e);
      const coord = this._workerDragCoordFromEvent(e);
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
      const coord = this._workerDragCoordFromEvent(e);
      this.hoveredCoord = null;
      this._clearDropTarget();
      this.dragViewportRect = null;
      if (!Number.isInteger(src) || !coord) return;
      this.moveWorkerDragToCoord(src, coord);
    },
    onCanvasDragLeave(e) {
      const related = e && e.relatedTarget;
      const canvas = e && e.currentTarget;
      if (related && canvas && typeof canvas.contains === 'function' && canvas.contains(related)) return;
      this._clearDropTarget();
      this.dragViewportRect = null;
    },
    colLabel(col) {
      return GridGeometry.colLabel(col);
    },
    rowLabel(row) {
      return GridGeometry.rowLabel(row);
    },
    onColumnResizeDown(e) {
      if (e.button !== 0) return;
      if (this.columnResize) return;
      e.preventDefault();
      e.stopPropagation();
      this.columnResize = {
        startX: e.clientX,
        startWidth: this.columnWidth,
        pointerId: e.pointerId,
      };
      this.draggingColumnWidth = this.columnWidth;
      this.updateResizeTooltip(e, `${this.columnWidth}px wide`);
      this._colResizeMoveHandler = (ev) => this.onColumnResizeMove(ev);
      this._colResizeUpHandler = (ev) => this.onColumnResizeUp(ev);
      window.addEventListener('pointermove', this._colResizeMoveHandler);
      window.addEventListener('pointerup', this._colResizeUpHandler);
      window.addEventListener('pointercancel', this._colResizeUpHandler);
    },
    onColumnResizeMove(e) {
      if (!this.columnResize) return;
      if (e.pointerId !== this.columnResize.pointerId) return;
      const dx = e.clientX - this.columnResize.startX;
      const next = this.columnResize.startWidth + dx;
      this.draggingColumnWidth = Math.max(140, Math.min(480, Math.round(next)));
      this.updateResizeTooltip(e, `${this.draggingColumnWidth}px wide`);
    },
    onColumnResizeUp(e) {
      if (!this.columnResize) return;
      if (e && e.pointerId !== this.columnResize.pointerId) return;
      this._teardownColumnResizeListeners();
      const dragged = this.draggingColumnWidth;
      this.columnResize = null;
      this.draggingColumnWidth = null;
      this.resizeTooltip = null;
      if (dragged != null) {
        const final = this.clampColumnWidth(dragged);
        this.pendingColumnWidth = final;
        this.persistGrid({ columnWidth: final });
      }
    },
    _teardownColumnResizeListeners() {
      if (this._colResizeMoveHandler) {
        window.removeEventListener('pointermove', this._colResizeMoveHandler);
        window.removeEventListener('pointerup', this._colResizeUpHandler);
        window.removeEventListener('pointercancel', this._colResizeUpHandler);
        this._colResizeMoveHandler = null;
        this._colResizeUpHandler = null;
      }
    },
    resetColumnWidth() {
      this._teardownColumnResizeListeners();
      this.columnResize = null;
      this.draggingColumnWidth = null;
      this.pendingColumnWidth = 220;
      this.resizeTooltip = null;
      this.persistGrid({ columnWidth: 220 });
    },
    persistSingleRowHeight(row, height) {
      const rowIndex = Math.max(0, Math.trunc(Number(row) || 0));
      const final = this.clampRowHeight(height);
      const rowHeights = this.normalizeRowHeights(this.rowHeightOverrides);
      if (final === this.rowHeight) {
        delete rowHeights[String(rowIndex)];
      } else {
        rowHeights[String(rowIndex)] = final;
      }
      this.pendingRowHeights = rowHeights;
      this.persistGrid({ rowHeights });
    },
    onRowResizeDown(row, e) {
      if (e.button !== 0) return;
      if (this.rowResize) return;
      e.preventDefault();
      e.stopPropagation();
      const rowIndex = Math.max(0, Math.trunc(Number(row) || 0));
      const mode = e.shiftKey ? 'global' : 'single';
      const startHeight = mode === 'global' ? this.rowHeight : this.rowHeightForRow(rowIndex);
      this.rowResize = {
        mode,
        row: rowIndex,
        startY: e.clientY,
        startHeight,
        startGlobalHeight: this.rowHeight,
        startRowHeights: this.normalizeRowHeights(this.rowHeightOverrides),
        pointerId: e.pointerId,
      };
      this.draggingRowHeight = startHeight;
      this.updateResizeTooltip(e, mode === 'global' ? `${startHeight}px all rows` : `${startHeight}px row ${this.rowLabel(rowIndex)}`);
      this._rowResizeMoveHandler = (ev) => this.onRowResizeMove(ev);
      this._rowResizeUpHandler = (ev) => this.onRowResizeUp(ev);
      window.addEventListener('pointermove', this._rowResizeMoveHandler);
      window.addEventListener('pointerup', this._rowResizeUpHandler);
      window.addEventListener('pointercancel', this._rowResizeUpHandler);
    },
    onRowResizeMove(e) {
      if (!this.rowResize) return;
      if (e.pointerId !== this.rowResize.pointerId) return;
      const dy = e.clientY - this.rowResize.startY;
      const next = this.rowResize.startHeight + dy;
      this.draggingRowHeight = Math.max(32, Math.min(480, Math.round(next)));
      this.updateResizeTooltip(
        e,
        this.rowResize.mode === 'global'
          ? `${this.draggingRowHeight}px all rows`
          : `${this.draggingRowHeight}px row ${this.rowLabel(this.rowResize.row)}`
      );
    },
    onRowResizeUp(e) {
      if (!this.rowResize) return;
      if (e && e.pointerId !== this.rowResize.pointerId) return;
      this._teardownRowResizeListeners();
      const dragged = this.draggingRowHeight;
      const resize = this.rowResize;
      this.rowResize = null;
      this.draggingRowHeight = null;
      this.resizeTooltip = null;
      if (dragged != null) {
        const final = this.clampRowHeight(dragged);
        if (resize.mode === 'global') {
          const rowHeights = this.adjustedGlobalRowHeights(resize, final);
          this.pendingRowHeight = final;
          this.pendingRowHeights = rowHeights;
          this.persistGrid({ rowHeight: final, rowHeights });
        } else {
          this.persistSingleRowHeight(resize.row, final);
        }
      }
    },
    _teardownRowResizeListeners() {
      if (this._rowResizeMoveHandler) {
        window.removeEventListener('pointermove', this._rowResizeMoveHandler);
        window.removeEventListener('pointerup', this._rowResizeUpHandler);
        window.removeEventListener('pointercancel', this._rowResizeUpHandler);
        this._rowResizeMoveHandler = null;
        this._rowResizeUpHandler = null;
      }
    },
    resetRowHeight(row = null, e = null) {
      this._teardownRowResizeListeners();
      this.rowResize = null;
      this.draggingRowHeight = null;
      this.resizeTooltip = null;
      if (e?.shiftKey || row === null) {
        const rowHeights = {};
        this.pendingRowHeight = 140;
        this.pendingRowHeights = rowHeights;
        this.persistGrid({ rowHeight: 140, rowHeights });
        return;
      }
      const rowHeights = this.normalizeRowHeights(this.rowHeightOverrides);
      delete rowHeights[String(Math.max(0, Math.trunc(Number(row) || 0)))];
      this.pendingRowHeights = rowHeights;
      this.persistGrid({ rowHeights });
    },
    resetRowsSmall() {
      this._teardownRowResizeListeners();
      this._teardownCardVerticalResizeListeners();
      this.rowResize = null;
      this.cardVerticalResize = null;
      this.draggingRowHeight = null;
      this.pendingRowHeight = 32;
      this.pendingRowHeights = {};
      this.resizeTooltip = null;
      this.clearExpandedWorkerCard();
      this.persistGrid({ rowHeight: 32, rowHeights: {} });
    },
    onCardVerticalResizeStart(item, e) {
      if (!item || e.button !== 0) return;
      if (this.cardVerticalResize) return;
      this.selectWorker(item);
      this.clearExpandedWorkerCard();
      const row = Math.max(0, Math.trunc(Number(item.coord.row) || 0));
      const mode = e.shiftKey ? 'global' : 'single';
      const startHeight = mode === 'global' ? this.rowHeight : this.rowHeightForRow(row);
      this.cardVerticalResize = {
        mode,
        slotIndex: item.slotIndex,
        row,
        startY: e.clientY,
        startHeight,
        startGlobalHeight: this.rowHeight,
        startRowHeights: this.normalizeRowHeights(this.rowHeightOverrides),
        pointerId: e.pointerId,
      };
      this.draggingRowHeight = startHeight;
      this.updateResizeTooltip(e, mode === 'global' ? `${startHeight}px all rows` : `${startHeight}px row ${this.rowLabel(row)}`);
      this._cardResizeMoveHandler = (ev) => this.onCardVerticalResizeMove(ev);
      this._cardResizeUpHandler = (ev) => this.onCardVerticalResizeUp(ev);
      window.addEventListener('pointermove', this._cardResizeMoveHandler);
      window.addEventListener('pointerup', this._cardResizeUpHandler);
      window.addEventListener('pointercancel', this._cardResizeUpHandler);
    },
    onCardVerticalResizeMove(e) {
      if (!this.cardVerticalResize) return;
      if (e.pointerId !== this.cardVerticalResize.pointerId) return;
      const dy = e.clientY - this.cardVerticalResize.startY;
      const next = this.cardVerticalResize.startHeight + dy;
      this.draggingRowHeight = this.clampRowHeight(next);
      this.updateResizeTooltip(
        e,
        this.cardVerticalResize.mode === 'global'
          ? `${this.draggingRowHeight}px all rows`
          : `${this.draggingRowHeight}px row ${this.rowLabel(this.cardVerticalResize.row)}`
      );
    },
    onCardVerticalResizeUp(e) {
      if (!this.cardVerticalResize) return;
      if (e && e.pointerId !== this.cardVerticalResize.pointerId) return;
      this._teardownCardVerticalResizeListeners();
      const resize = this.cardVerticalResize;
      const dragged = this.draggingRowHeight;
      this.cardVerticalResize = null;
      this.draggingRowHeight = null;
      this.resizeTooltip = null;
      this.clearExpandedWorkerCard();
      if (dragged == null) return;
      const final = this.clampRowHeight(dragged);
      if (resize.mode === 'global') {
        const rowHeights = this.adjustedGlobalRowHeights(resize, final);
        this.pendingRowHeight = final;
        this.pendingRowHeights = rowHeights;
        this.persistGrid({ rowHeight: final, rowHeights });
      } else {
        this.persistSingleRowHeight(resize.row, final);
      }
    },
    _teardownCardVerticalResizeListeners() {
      if (this._cardResizeMoveHandler) {
        window.removeEventListener('pointermove', this._cardResizeMoveHandler);
        window.removeEventListener('pointerup', this._cardResizeUpHandler);
        window.removeEventListener('pointercancel', this._cardResizeUpHandler);
        this._cardResizeMoveHandler = null;
        this._cardResizeUpHandler = null;
      }
    },
    updateResizeTooltip(e, text) {
      this.resizeTooltip = { x: e.clientX + 14, y: e.clientY + 14, text };
    },
    toggleMinimap() {
      this.$emit('set-minimap-collapsed', !this.minimapCollapsed);
    },
    onMinimapClick(e) {
      const rect = e.currentTarget.getBoundingClientRect();
      const b = this.minimapBounds;
      const scale = this.minimapScale;
      const visible = this.minimapVisibleCells;
      const col = b.colMin + (e.clientX - rect.left) / scale.x;
      const row = b.rowMin + (e.clientY - rect.top) / scale.y;
      this.setOrigin({
        col: col - visible.cols / 2,
        row: row - visible.rows / 2,
      });
    },
  }
};
