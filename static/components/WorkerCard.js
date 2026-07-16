const VALUE_UNIT_LABELS = {
  celsius: { abbr: '°C', name: 'degree Celsius' },
  fahrenheit: { abbr: '°F', name: 'degree Fahrenheit' },
  kelvin: { abbr: 'K', name: 'kelvin' },
  meter: { abbr: 'm', name: 'meter' },
  kilometer: { abbr: 'km', name: 'kilometer' },
  centimeter: { abbr: 'cm', name: 'centimeter' },
  millimeter: { abbr: 'mm', name: 'millimeter' },
  inch: { abbr: 'in', name: 'inch' },
  foot: { abbr: 'ft', name: 'foot' },
  yard: { abbr: 'yd', name: 'yard' },
  mile: { abbr: 'mi', name: 'mile' },
  gram: { abbr: 'g', name: 'gram' },
  kilogram: { abbr: 'kg', name: 'kilogram' },
  pound: { abbr: 'lb', name: 'pound' },
  ounce: { abbr: 'oz', name: 'ounce' },
  second: { abbr: 's', name: 'second' },
  minute: { abbr: 'min', name: 'minute' },
  hour: { abbr: 'h', name: 'hour' },
  day: { abbr: 'd', name: 'day' },
  percent: { abbr: '%', name: 'percent' },
  dollar: { abbr: 'USD', name: 'US dollar' },
};

const WorkerCard = {
  props: ['worker', 'slotIndex', 'tasks', 'taskById', 'outputLines', 'multipleWorkspaces', 'neighborSlots', 'allWorkers', 'menuContext', 'layoutMode', 'cardHeight', 'isSelected', 'multipleSelectionActive', 'isVerticalResizing', 'workspaceId', 'requestOutputCatchup', 'buildWorkerDragPayload', 'buildWorkerDragImage', 'canDropWorkerAtSlot', 'dropWorkerOnSlot', 'updateSingletonWorkerDrag', 'endSingletonWorkerDrag', 'cancelSingletonWorkerDrag'],
  emits: ['configure', 'select-task', 'open-focus', 'transfer', 'copy-worker', 'delete-worker', 'worker-scope-action', 'menu-opened', 'menu-closed', 'vertical-resize-start', 'value-edit-ended'],
  template: `
    <div class="worker-card" :class="{ 'drag-over': dragOver, 'connect-target': connectTarget, 'worker-card--small': effectiveLayoutMode === 'small', 'is-dragging': isDragging, 'worker-card--disabled-type': isDisabledType }"
         :style="effectiveLayoutMode === 'small' ? { background: agentColor } : null"
         :aria-label="cardAriaLabel"
         draggable="true"
         @pointerdown="onPointerDown"
         @pointermove="onPointerMove"
         @pointerup="onPointerUp"
         @pointercancel="onPointerCancel"
         @lostpointercapture="onPointerLostCapture"
         @dragstart="onDragStart"
         @dragend="onDragEnd"
         @dragover="onDragOver"
         @dragleave="onDragLeave"
         @drop.prevent="onDrop"
         @mousemove="onCardMouseMove"
         @mouseleave="onCardMouseLeave"
>
      <div v-if="showsVerticalResizeControl"
           class="card-height-resize-handle"
           :class="{ 'card-height-resize-handle-active': showVerticalResizeHandle }"
           :style="verticalResizeHandleStyle"
           title="Drag to expand this card vertically"
           aria-label="Drag to expand this card vertically"
           @pointerdown.stop="onVerticalResizeHandleDown"></div>
      <template v-for="dir in ['up','down','left','right']" :key="'handle-' + dir">
        <div v-if="canConnect(dir)"
             class="connect-handle"
             :class="['connect-handle-' + dir, { 'connect-handle-active': hoveredHandle === dir }]"
             draggable="true"
             @dragstart.stop="onHandleDragStart(dir, $event)"
             @dragend.stop="onHandleDragEnd"
             :title="'Drag to pass output ' + dir"
             :aria-label="'Drag to pass output ' + dir">
          <span class="connect-handle-arrow" aria-hidden="true">{{ connectHandleArrow(dir) }}</span>
        </div>
      </template>
      <span v-if="passDir === 'up' && !passConnectsToNeighbor" class="pass-indicator pass-up" title="This worker passes tickets up" aria-label="This worker passes tickets up">&#x25B2;</span>
      <span v-if="passDir === 'down' && !passConnectsToNeighbor" class="pass-indicator pass-down" title="This worker passes tickets down" aria-label="This worker passes tickets down">&#x25BC;</span>
      <span v-if="passDir === 'left' && !passConnectsToNeighbor" class="pass-indicator pass-left" title="This worker passes tickets left" aria-label="This worker passes tickets left">&#x25C0;</span>
      <span v-if="passDir === 'right' && !passConnectsToNeighbor" class="pass-indicator pass-right" title="This worker passes tickets right" aria-label="This worker passes tickets right">&#x25B6;</span>
      <span v-if="passDir === 'random'" class="pass-indicator pass-random" title="This worker passes tickets in a random direction" aria-label="This worker passes tickets in a random direction">?</span>
      <div class="worker-card-header"
           :class="{ 'worker-card-header--value-editing': showCompactValue && valueEditing }"
           :style="{ background: agentColor }"
           @click="onHeaderClick"
           @dblclick="onHeaderDblClick">
        <input v-if="showCompactValue && valueEditing"
               class="worker-card-compact-value-editor"
               ref="valueEditInput"
               v-model="valueEditText"
               @keydown.stop
               @keydown.enter.prevent.stop="commitValueEdit"
               @keydown.escape.prevent.stop="cancelValueEdit({ restoreGridFocus: true })"
               @blur="cancelValueEdit"
               @click.stop
               @dblclick.stop
               aria-label="Edit name and value">
        <div v-else class="worker-card-identity">
          <div class="worker-card-title-row" ref="titleRow">
            <span :key="'worker-type-icon-' + workerIcon" class="worker-type-icon-host" aria-hidden="true">
              <i class="worker-type-icon worker-type-icon--card" :data-lucide="workerIcon" aria-hidden="true"></i>
            </span>
            <span class="worker-card-name" ref="nameLabel">{{ workerNameWithPort }}</span>
            <span class="worker-card-name worker-card-name--measure" ref="nameMeasure" aria-hidden="true"></span>
          </div>
        </div>
        <button v-if="showCompactValue && !valueEditing"
                type="button"
                class="worker-card-compact-value worker-card-compact-value-button"
                :title="valueDisplay || 'Empty'"
                @click.stop="startCompactValueEdit"
                @dblclick.stop
                aria-label="Edit name and value">
          {{ valueDisplay || 'Empty' }}
        </button>
        <div v-if="!showCompactValue || !valueEditing" class="worker-card-actions">
          <span class="worker-card-header-status">
            <span v-if="(workerState !== 'idle' || isPaused || isHeldQueue) && !pillInBody" class="status-pill" :class="['status-' + workerState, { 'status-pill-clickable': isWorking || isService }]" @click.stop="onStatusPillClick">
              {{ statusLabel }}
            </span>
          </span>
          <button class="worker-menu-btn" ref="menuBtn" @click.stop="toggleMenu" title="Actions">&hellip;</button>
        </div>
      </div>
      <Teleport to="body">
        <div v-if="showMenu" ref="menu" class="worker-menu" :style="menuStyle" @click.stop @keydown="onMenuKeydown">
          <div class="worker-menu-section-label">This Worker</div>
          <button v-if="canConfigure" class="worker-menu-item" @click="menuEdit"><i class="menu-item-icon" data-lucide="pencil" aria-hidden="true"></i><span class="menu-item-label">Edit</span></button>
          <button v-if="canStart && !isPaused" class="worker-menu-item" @click="menuRun"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">{{ runMenuLabel }}</span></button>
          <button v-if="canRestart" class="worker-menu-item" @click="menuRestart"><i class="menu-item-icon" data-lucide="rotate-cw" aria-hidden="true"></i><span class="menu-item-label">Restart</span></button>
          <button v-if="canWatch" class="worker-menu-item" @click="menuWatch"><i class="menu-item-icon" data-lucide="eye" aria-hidden="true"></i><span class="menu-item-label">Watch</span></button>
          <button v-if="isService" class="worker-menu-item" :disabled="!serviceSiteUrl" @click="menuOpenSite"><i class="menu-item-icon" data-lucide="external-link" aria-hidden="true"></i><span class="menu-item-label">Open site in browser</span></button>
          <button v-if="canStop" class="worker-menu-item" @click="menuStop"><i class="menu-item-icon" data-lucide="square" aria-hidden="true"></i><span class="menu-item-label">Stop</span></button>
          <button v-if="canPauseWorker && !isPaused" class="worker-menu-item" @click="menuPause"><i class="menu-item-icon" data-lucide="pause" aria-hidden="true"></i><span class="menu-item-label">Pause Worker</span></button>
          <button v-if="canPauseWorker && isPaused" class="worker-menu-item" @click="menuUnpause"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Unpause Worker</span></button>
          <button class="worker-menu-item" @click="menuDuplicate"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Duplicate</span></button>
          <button class="worker-menu-item" @click="menuCopyWorker"><i class="menu-item-icon" data-lucide="clipboard" aria-hidden="true"></i><span class="menu-item-label">Copy Worker</span></button>
          <button class="worker-menu-item" @click="menuExportWorker"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Worker</span></button>
          <button v-if="valueHistoryEnabled" class="worker-menu-item" @click="menuShowValueHistory"><i class="menu-item-icon" data-lucide="history" aria-hidden="true"></i><span class="menu-item-label">Show History</span></button>
          <button v-if="valueHistoryEnabled" class="worker-menu-item" @click="menuClearValueHistory"><i class="menu-item-icon" data-lucide="eraser" aria-hidden="true"></i><span class="menu-item-label">Clear History</span></button>
          <button v-if="multipleWorkspaces" class="worker-menu-item" @click="menuCopyTo"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Copy to workspace&hellip;</span></button>
          <button v-if="multipleWorkspaces && canMove" class="worker-menu-item" @click="menuMoveTo"><i class="menu-item-icon" data-lucide="arrow-right" aria-hidden="true"></i><span class="menu-item-label">Move to workspace&hellip;</span></button>
          <button class="worker-menu-item worker-menu-danger" @click="menuDelete"><i class="menu-item-icon" data-lucide="trash-2" aria-hidden="true"></i><span class="menu-item-label">Delete Worker&hellip;</span></button>
          <template v-if="hasConnectedGroup">
            <div class="worker-menu-divider"></div>
            <div class="worker-menu-section-label">Connected Group: {{ connectedGroupCount }} Workers</div>
            <button class="worker-menu-item" @click="menuScoped('pause', 'connected-group')"><i class="menu-item-icon" data-lucide="pause" aria-hidden="true"></i><span class="menu-item-label">Pause Group</span></button>
            <button class="worker-menu-item" @click="menuScoped('unpause', 'connected-group')"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Unpause Group</span></button>
            <button class="worker-menu-item" @click="menuScoped('stop', 'connected-group')"><i class="menu-item-icon" data-lucide="square" aria-hidden="true"></i><span class="menu-item-label">Stop Running Workers</span></button>
            <button class="worker-menu-item" @click="menuScoped('copy', 'connected-group')"><i class="menu-item-icon" data-lucide="clipboard" aria-hidden="true"></i><span class="menu-item-label">Copy Group</span></button>
            <button class="worker-menu-item" @click="menuScoped('duplicate', 'connected-group')"><i class="menu-item-icon" data-lucide="copy-plus" aria-hidden="true"></i><span class="menu-item-label">Duplicate Group</span></button>
            <button class="worker-menu-item" @click="menuScoped('export', 'connected-group')"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Group</span></button>
            <button v-if="multipleWorkspaces" class="worker-menu-item" @click="menuScoped('copy-to', 'connected-group')"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Copy Group to workspace&hellip;</span></button>
            <button v-if="multipleWorkspaces" class="worker-menu-item" @click="menuScoped('move-to', 'connected-group')"><i class="menu-item-icon" data-lucide="arrow-right" aria-hidden="true"></i><span class="menu-item-label">Move Group to workspace&hellip;</span></button>
            <button class="worker-menu-item worker-menu-danger" @click="menuScoped('delete', 'connected-group')"><i class="menu-item-icon" data-lucide="trash-2" aria-hidden="true"></i><span class="menu-item-label">Delete Group&hellip;</span></button>
          </template>
          <template v-if="hasSelection">
            <div class="worker-menu-divider"></div>
            <div class="worker-menu-section-label">Selected Workers: {{ selectionCount }}</div>
            <button class="worker-menu-item" @click="menuScoped('pause', 'selection')"><i class="menu-item-icon" data-lucide="pause" aria-hidden="true"></i><span class="menu-item-label">Pause Selected</span></button>
            <button class="worker-menu-item" @click="menuScoped('unpause', 'selection')"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Unpause Selected</span></button>
            <button class="worker-menu-item" @click="menuScoped('stop', 'selection')"><i class="menu-item-icon" data-lucide="square" aria-hidden="true"></i><span class="menu-item-label">Stop Running Workers</span></button>
            <button class="worker-menu-item" @click="menuScoped('copy', 'selection')"><i class="menu-item-icon" data-lucide="clipboard" aria-hidden="true"></i><span class="menu-item-label">Copy Selected</span></button>
            <button class="worker-menu-item" @click="menuScoped('duplicate', 'selection')"><i class="menu-item-icon" data-lucide="copy-plus" aria-hidden="true"></i><span class="menu-item-label">Duplicate Selected</span></button>
            <button class="worker-menu-item" @click="menuScoped('export', 'selection')"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Selected</span></button>
            <button v-if="multipleWorkspaces" class="worker-menu-item" @click="menuScoped('copy-to', 'selection')"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Copy Selected to workspace&hellip;</span></button>
            <button v-if="multipleWorkspaces" class="worker-menu-item" @click="menuScoped('move-to', 'selection')"><i class="menu-item-icon" data-lucide="arrow-right" aria-hidden="true"></i><span class="menu-item-label">Move Selected to workspace&hellip;</span></button>
            <button class="worker-menu-item worker-menu-danger" @click="menuScoped('delete', 'selection')"><i class="menu-item-icon" data-lucide="trash-2" aria-hidden="true"></i><span class="menu-item-label">Delete Selected&hellip;</span></button>
          </template>
        </div>
      </Teleport>
      <div v-if="effectiveLayoutMode !== 'small'" class="worker-card-body" @click.stop="onBodyClick" @dblclick.stop="onBodyDblClick">
        <div v-if="isDisabledType" class="worker-card-disabled-badge" :title="disabledTypeMessage">
          {{ disabledTypeMessage }}
        </div>
        <div v-if="showActiveOutputPane" class="worker-card-output">
          <pre>{{ lastOutput }}</pre>
        </div>
        <div class="worker-card-queue" v-else-if="effectiveLayoutMode !== 'small' && visibleQueuedTasks.length">
          <div v-for="t in visibleQueuedTasks" :key="t.id" class="worker-queue-item" :title="t.title"
               @click.stop="$emit('select-task', t.id)">
            <i class="ticket-type-icon ticket-type-icon--worker-queue" data-lucide="tag" aria-hidden="true"></i>
            <span class="worker-queue-title">{{ t.title }}</span>
          </div>
        </div>
        <div v-else-if="isMarker" class="worker-card-empty worker-card-empty--marker">
          <div v-if="markerNote" class="worker-card-note">{{ markerNote }}</div>
          <template v-else>{{ emptyLabel }}</template>
        </div>
        <div v-else-if="isValue" class="worker-card-value">
          <span v-if="isFormulaValue" class="worker-card-formula-badge" aria-label="Formula value">fx</span>
          <template v-if="valueEditing">
            <input class="worker-card-value-input"
                   ref="valueEditInput"
                   v-model="valueEditText"
                   @keydown.stop
                   @keydown.enter.prevent.stop="commitValueEdit"
                   @keydown.escape.prevent.stop="cancelValueEdit({ restoreGridFocus: true })"
                   @blur="cancelValueEdit"
                   @click.stop
                   aria-label="Edit value">
            <div v-if="valueEditError" class="worker-card-value-error">{{ valueEditError }}</div>
          </template>
          <button v-else class="worker-card-value-main worker-card-value-main--button"
                  :class="'worker-card-value-main--' + valueAlignment"
                  :title="valueDisplay"
                  @click.stop="startValueEdit">
            {{ valueDisplay || 'Empty' }}
          </button>
          <button v-if="hasNumericValueSparkline"
                  type="button"
                  class="worker-card-value-sparkline-button"
                  :title="valueSparklineTitle"
                  @click.stop="openValueGraph"
                  @dblclick.stop
                  aria-label="Open value history graph">
            <svg class="worker-card-value-sparkline" viewBox="0 0 120 32" preserveAspectRatio="none" aria-hidden="true">
              <line x1="0" y1="31" x2="120" y2="31" class="worker-card-value-sparkline-base"></line>
              <polyline v-if="valueSparklinePoints" :points="valueSparklinePoints" class="worker-card-value-sparkline-line"></polyline>
              <circle v-if="valueSparklineSinglePoint" :cx="valueSparklineSinglePoint.x" :cy="valueSparklineSinglePoint.y" r="2.2" class="worker-card-value-sparkline-dot"></circle>
            </svg>
          </button>
        </div>
        <div v-else-if="isNotification" class="worker-card-notification">
          <ul v-if="notificationSummaryItems.length" class="worker-card-notification-list">
            <li v-for="item in notificationSummaryItems" :key="item">{{ item }}</li>
          </ul>
          <div v-else class="worker-card-notification-empty">No notification modes enabled</div>
        </div>
        <div v-else class="worker-card-empty" :class="{ 'worker-card-empty--idle-detail': idleDetail }">
          <span v-if="pillInBody" class="status-pill" :class="['status-' + workerState, { 'status-pill-clickable': isWorking || isService }]" @click.stop="onStatusPillClick">
            {{ statusLabel }}
          </span>
          <div v-else-if="idleDetail"
               class="worker-card-idle-detail worker-card-idle-detail--clickable"
               :title="idleDetail"
               @click.stop="openConfigFromIdleDetail">{{ idleDetail }}</div>
          <template v-else>{{ emptyLabel }}</template>
        </div>
      </div>
      <Teleport to="body">
        <div v-if="valueGraphOpen" class="modal-overlay value-graph-overlay" @click.self="closeValueGraph" @keydown.escape="closeValueGraph" tabindex="0" ref="valueGraphOverlay">
          <div class="modal value-graph-modal">
            <div class="modal-header">
              <h2>{{ valueGraphTitle }}</h2>
              <div class="value-history-header-actions">
                <button class="btn btn-secondary" type="button" @click="exportValueHistoryCsv" :disabled="!valueHistoryRows.length">Export CSV</button>
                <button class="btn btn-secondary" type="button" @click="clearValueHistory" :disabled="!valueHistoryRows.length">Clear</button>
                <button class="btn btn-icon" type="button" @click="closeValueGraph">&times;</button>
              </div>
            </div>
            <div class="modal-body value-graph-body">
              <div class="value-graph-current">
                <span class="value-graph-current-label">{{ valueCellRef || 'Value' }}</span>
                <span class="value-graph-current-value">{{ valueDisplay || 'Empty' }}</span>
              </div>
              <svg v-if="hasNumericValueHistory" class="value-graph-chart" viewBox="0 0 640 260" preserveAspectRatio="none" role="img" :aria-label="valueGraphAriaLabel">
                <line v-for="tick in valueGraphYTicks" :key="'y-' + tick.y" x1="54" :y1="tick.y" x2="626" :y2="tick.y" class="value-graph-grid"></line>
                <line x1="54" y1="18" x2="54" y2="226" class="value-graph-axis"></line>
                <line x1="54" y1="226" x2="626" y2="226" class="value-graph-axis"></line>
                <polyline v-if="valueGraphPoints" :points="valueGraphPoints" class="value-graph-line"></polyline>
                <circle v-if="valueGraphSinglePoint" :cx="valueGraphSinglePoint.x" :cy="valueGraphSinglePoint.y" r="4" class="value-graph-dot"></circle>
                <text v-for="tick in valueGraphYTicks" :key="'label-' + tick.y" x="46" :y="tick.y + 4" class="value-graph-y-label">{{ tick.label }}</text>
              </svg>
              <div v-if="hasNumericValueHistory" class="value-graph-axis-labels">
                <span>{{ valueGraphStartLabel }}</span>
                <span>{{ valueGraphEndLabel }}</span>
              </div>
              <div class="value-history-pane" role="region" aria-label="Value history">
                <table v-if="valueHistoryRows.length" class="value-history-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Value</th>
                      <th class="value-history-action-header">Delete</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, index) in valueHistoryRows" :key="row.updatedAt + '-' + index">
                      <td :title="row.updatedAt">{{ row.displayTime }}</td>
                      <td :title="row.displayValue">{{ row.displayValue }}</td>
                      <td class="value-history-action-cell">
                        <button
                          class="value-history-delete-btn"
                          type="button"
                          title="Delete history row"
                          aria-label="Delete history row"
                          @click="deleteValueHistoryRow(index)">&times;</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="value-history-empty">No history recorded</div>
              </div>
            </div>
          </div>
        </div>
      </Teleport>
    </div>
  `,
  data() {
    return {
      dragOver: false,
      connectTarget: false,
      showMenu: false,
      menuPos: { top: 0, left: 0 },
      menuAnchorPos: null,
      elapsed: '0s',
      _timer: null,
      hoveredHandle: null,
      shiftDragIntent: false,
      isDragging: false,
      pointerWorkerDrag: null,
      showTitlePort: false,
      hoveredVerticalResize: false,
      verticalResizeX: 0,
      valueEditing: false,
      valueEditText: '',
      valueEditError: '',
      valueEditIncludesName: false,
      valueGraphOpen: false,
    };
  },
  mounted() {
    renderLucideIcons(this.$el);
    this.updateElapsed();
    this.syncElapsedTimer();
    this.recalculateTitlePortVisibility();
    this.ensureOutputCatchup();
    if (typeof ResizeObserver !== 'undefined') {
      this._titleResizeObserver = new ResizeObserver(() => this.recalculateTitlePortVisibility());
      if (this.$refs.titleRow) this._titleResizeObserver.observe(this.$refs.titleRow);
      if (this.$refs.nameLabel) this._titleResizeObserver.observe(this.$refs.nameLabel);
    }
    this._closeMenu = (e) => {
      const menu = this.$refs.menu;
      const clickedInsideMenu = menu && typeof menu.contains === 'function' && menu.contains(e.target);
      if (this.showMenu && !this.$el.contains(e.target) && !clickedInsideMenu) {
        this.showMenu = false;
      }
    };
    this._closeValueEdit = (e) => {
      if (!this.valueEditing) return;
      if (this.$el?.contains?.(e.target)) return;
      this.cancelValueEdit();
    };
    document.addEventListener('click', this._closeMenu);
    document.addEventListener('pointerdown', this._closeValueEdit, true);
    window.addEventListener('resize', this.repositionMenuWithinViewport);
    window.addEventListener('scroll', this.repositionMenuWithinViewport, true);
  },
  beforeUnmount() {
    if (this._timer) clearInterval(this._timer);
    if (this._titleResizeObserver) this._titleResizeObserver.disconnect();
    document.removeEventListener('click', this._closeMenu);
    document.removeEventListener('pointerdown', this._closeValueEdit, true);
    window.removeEventListener('resize', this.repositionMenuWithinViewport);
    window.removeEventListener('scroll', this.repositionMenuWithinViewport, true);
    document.body.classList.remove('worker-singleton-dragging');
    this.removeDragImage();
  },
  computed: {
    effectiveLayoutMode() {
      const rawHeight = Number(this.cardHeight);
      const height = Number.isFinite(rawHeight) ? rawHeight : (this.layoutMode === 'small' ? 32 : 140);
      return height < 40 ? 'small' : 'medium';
    },
    passDir() {
      const d = this.worker.disposition || '';
      return d.startsWith('pass:') ? d.slice(5) : null;
    },
    passConnectsToNeighbor() {
      return !!(this.passDir && this.neighborSlots && this.neighborSlots[this.passDir] != null);
    },
    workerState() { return this.worker.service_state?.state || this.worker.state || 'idle'; },
    isWorking() { return ['working', 'retrying', 'starting', 'running', 'healthy', 'unhealthy'].includes(this.workerState); },
    needsElapsedTimer() {
      return this.workerState === 'working' ||
        this.workerState === 'retrying' ||
        (this.isService && ['starting', 'running', 'healthy', 'unhealthy'].includes(this.workerState));
    },
    showOutputPane() {
      return this.effectiveLayoutMode !== 'small';
    },
    showActiveOutputPane() {
      return this.showOutputPane && (this.isWorking || this.isService) && !!this.lastOutput;
    },
    pillInBody() {
      return this.effectiveLayoutMode !== 'small' && this.isService && (this.workerState !== 'idle' || this.isPaused);
    },
    statusLabel() {
      if (this.isPaused) return 'PAUSED';
      if (this.isHeldQueue) return 'WAITING FOR RUN';
      if (this.workerState === 'retrying') {
        return `RETRY${this.retryAttemptLabel}${this.retryCountdownLabel}`;
      }
      if (this.isService && this.workerState === 'running') return `RUNNING ${this.elapsed}`;
      if (this.isService && this.workerState === 'starting') return `STARTING ${this.elapsed}`;
      if (this.isService && this.workerState === 'healthy') return `HEALTHY ${this.elapsed}`;
      if (this.isService && this.workerState === 'unhealthy') return `UNHEALTHY ${this.elapsed}`;
      if (this.isWorking) return `BUSY ${this.elapsed}`;
      return this.workerState.toUpperCase();
    },
    retryAttemptLabel() {
      if (this.workerState !== 'retrying') return '';
      const attempt = Number(this.worker?.retry_attempt || 0);
      const max = Number(this.worker?.retry_max || 0);
      if (!attempt || !max) return '';
      return ` ${attempt}/${max}`;
    },
    retryCountdownLabel() {
      if (this.workerState !== 'retrying') return '';
      const retryAt = this.worker?.retry_at ? new Date(this.worker.retry_at).getTime() : NaN;
      if (!Number.isFinite(retryAt)) return '';
      const remaining = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
      return ` ${remaining}s`;
    },
    taskQueueCount() {
      return Array.isArray(this.worker?.task_queue) ? this.worker.task_queue.length : 0;
    },
    workerNameLabel() {
      const name = this.worker?.name || (this.isValue ? this.valueCellRef || 'Value' : '');
      return this.taskQueueCount > 0 ? `${name} (${this.taskQueueCount})` : name;
    },
    titlePortCandidate() {
      if (!this.isService) return '';
      const port = this.worker?.port;
      return port ? `:${port}` : '';
    },
    workerNameWithPort() {
      return this.showTitlePort && this.titlePortCandidate
        ? `${this.workerNameLabel}${this.titlePortCandidate}`
        : this.workerNameLabel;
    },
    canStart() {
      if (this.isService) return ['idle', 'stopped', 'crashed'].includes(this.workerState);
      if (this.isMarker) return false;
      if (this.isValue) return false;
      return this.workerState === 'idle' && !this.isDisabledType;
    },
    runMenuLabel() {
      if (!this.isService) return this.taskQueueCount > 0 ? `Run next (${this.taskQueueCount})` : 'Run';
      return this.taskQueueCount > 0 ? 'Run queued order' : 'Start';
    },
    canStop() {
      if (this.isService) return ['starting', 'running', 'healthy', 'unhealthy'].includes(this.workerState);
      return this.isWorking;
    },
    canRestart() {
      return this.isService && ['idle', 'stopped', 'running', 'healthy', 'unhealthy', 'crashed'].includes(this.workerState);
    },
    canWatch() {
      return this.isService || this.isWorking;
    },
    canConfigure() {
      return !this.isUnknownType;
    },
    isScheduled() {
      return this.worker.activation === 'at_time' || this.worker.activation === 'on_interval';
    },
    isPaused() {
      return this.worker.paused === true;
    },
    isHeldQueue() {
      return this.workerState === 'idle' && this.worker?.activation === 'manual' && this.taskQueueCount > 0;
    },
    automationPausedForWorker() {
      const paused = this.$root?.state?.config?.worker_automation_paused === true;
      return paused && ['ai', 'shell', 'marker', 'notification'].includes(String(this.worker?.type || 'ai'));
    },
    canPauseWorker() {
      return !this.isMarker && !this.isValue && !this.isEval && !this.isUnknownType;
    },
    connectedGroupCount() {
      return Array.isArray(this.menuContext?.connectedGroupSlots) ? this.menuContext.connectedGroupSlots.length : 0;
    },
    selectionCount() {
      return Array.isArray(this.menuContext?.selectionSlots) ? this.menuContext.selectionSlots.length : 0;
    },
    hasConnectedGroup() {
      return this.menuContext?.hasConnectedGroup === true && this.connectedGroupCount > 1;
    },
    hasSelection() {
      return this.menuContext?.hasSelection === true && this.selectionCount > 1;
    },
    canMove() {
      return this.workerState === 'idle' || (this.isService && ['stopped', 'crashed'].includes(this.workerState));
    },
    agentColor() {
      return workerColor(this.worker);
    },
    workerIcon() {
      return getWorkerTypeIcon(this.worker);
    },
    workerTypeLabel() {
      return workerTypeLabel(this.worker);
    },
    isShell() {
      return isShellWorker(this.worker);
    },
    isService() {
      return isServiceWorker(this.worker);
    },
    isMarker() {
      return isMarkerWorker(this.worker);
    },
    isNotification() {
      return isNotificationWorker(this.worker);
    },
    isValue() {
      return isValueWorker(this.worker);
    },
    isEval() {
      return isEvalWorker(this.worker);
    },
    isUnknownType() {
      return isUnknownWorkerType(this.worker);
    },
    isDisabledType() {
      return this.isEval || this.isUnknownType;
    },
    acceptsTaskDrop() {
      return !this.isValue && !this.isDisabledType;
    },
    cardAriaLabel() {
      const type = this.workerTypeLabel || 'Worker';
      const name = this.workerNameWithPort || this.valueCellRef || 'Unnamed worker';
      if (this.isValue) {
        const ref = this.valueCellRef ? ` at ${this.valueCellRef}` : '';
        return `Value worker ${name}${ref}. Not a ticket drop target.`;
      }
      return `${type} worker ${name}`;
    },
    disabledTypeMessage() {
      if (this.isUnknownType) return 'Worker type not installed';
      if (this.isEval) return 'Eval workers reserved for a future release';
      return '';
    },
    queuedTasks() {
      if (!this.worker.task_queue) return [];
      return this.worker.task_queue.map(id => {
        const t = this.lookupTask(id);
        return t || { id, title: id };
      });
    },
    visibleQueuedTasks() {
      if (!this.showActiveOutputPane) return this.queuedTasks;
      return this.queuedTasks.slice(1);
    },
    menuIconToken() {
      return [
        this.showMenu ? 'open' : 'closed',
        this.workerState,
        this.taskQueueCount,
        this.isPaused ? 'paused' : 'active',
        this.multipleSelectionActive ? 'multi' : 'single',
        this.multipleWorkspaces ? 'workspaces' : 'one-workspace',
        this.serviceSiteUrl ? 'site' : 'no-site',
      ].join('|');
    },
    menuStyle() {
      return { position: 'fixed', top: this.menuPos.top + 'px', left: this.menuPos.left + 'px' };
    },
    serviceSiteUrl() {
      return window.getServiceSiteUrl ? window.getServiceSiteUrl(this.worker) : '';
    },
    lastOutput() {
      // Prefer live output buffer when working
      if ((this.isWorking || this.isService) && this.outputLines?.length) {
        return this.outputLines.slice(-5).join('\n');
      }
      if (!this.worker.task_queue?.length) return '';
      const task = this.lookupTask(this.worker.task_queue[0]);
      if (!task?.body) return '';
      let idx = -1;
      let markerLen = 0;
      for (const marker of ['## Agent Output', '## Worker Output']) {
        const i = task.body.indexOf(marker);
        if (i < 0) continue;
        if (idx < 0 || i < idx) { idx = i; markerLen = marker.length; }
      }
      if (idx < 0) return '';
      const output = task.body.substring(idx + markerLen).trim();
      const lines = output.split('\n');
      return lines.slice(-5).join('\n');
    },
    emptyLabel() {
      if (this.isMarker) return 'Marker';
      if (this.isNotification) return 'Notification';
      if (this.isValue) return 'Value';
      if (this.isService) return this.workerState === 'idle' ? 'Stopped' : this.workerState;
      if (this.isHeldQueue) return 'Waiting for Run';
      return 'Idle';
    },
    idleDetail() {
      if (this.workerState !== 'idle' || this.isHeldQueue) return '';
      if (this.isShell) return this.interpolateValuePlaceholders(this.worker?.command);
      if (this.isService || this.isMarker || this.isNotification || this.isValue || this.isDisabledType) return '';
      return String(this.worker?.expertise_prompt || '').trim();
    },
    markerNote() {
      return String(this.worker?.note || '').trim();
    },
    notificationSummaryItems() {
      return window.notificationSummaryItems ? window.notificationSummaryItems(this.worker) : [];
    },
    storedValueText() {
      const value = this.worker?.value;
      return value === null || value === undefined ? '' : String(value);
    },
    valueCellRef() {
      return window.GridGeometry?.coordToCellRef?.(this.worker) || '';
    },
    valueTypeLabel() {
      const declared = String(this.worker?.value_type || 'auto');
      const resolved = String(this.worker?.resolved_value_type || '');
      return declared === 'auto' && resolved ? resolved : declared;
    },
    valueUnitLabels() {
      const unit = String(this.worker?.unit || '').trim();
      if (!unit) return { abbr: '', name: '' };
      return VALUE_UNIT_LABELS[unit] || { abbr: unit, name: unit };
    },
    valueUsesFullUnitLabel() {
      return this.isValue && this.effectiveLayoutMode !== 'small' && Number(this.cardHeight || 0) >= 120;
    },
    valueDisplayBase() {
      const value = this.worker?.value;
      if (value === null || value === undefined) return '';
      const format = this.worker?.format || {};
      const kind = String(format.kind || 'general');
      const numeric = typeof value === 'number' ? value : Number(value);
      const resolvedNumeric = String(this.worker?.resolved_value_type || '') === 'number';
      if ((kind === 'number' || kind === 'currency') && resolvedNumeric && Number.isFinite(numeric)) {
        const hasPlaces = Object.prototype.hasOwnProperty.call(format, 'places');
        const rawPlaces = hasPlaces ? format.places : 2;
        const automaticPlaces = rawPlaces === null || rawPlaces === '' || rawPlaces === 'auto';
        const fixedPlaces = automaticPlaces ? null : Math.max(0, Math.min(10, Number(rawPlaces)));
        const options = { useGrouping: format.grouping !== false };
        if (automaticPlaces) {
          options.maximumFractionDigits = 20;
        } else {
          options.minimumFractionDigits = fixedPlaces;
          options.maximumFractionDigits = fixedPlaces;
        }
        const displayNumeric = !automaticPlaces && Math.abs(numeric) < (0.5 * (10 ** -fixedPlaces)) ? 0 : numeric;
        const rendered = displayNumeric.toLocaleString(undefined, options);
        return kind === 'currency' ? `${format.symbol || '$'}${rendered}` : rendered;
      }
      return String(value);
    },
    valueAlignment() {
      const kind = String(this.worker?.format?.kind || 'general');
      if (kind === 'string-left') return 'left';
      if (kind === 'string-right' || kind === 'number' || kind === 'currency') return 'right';
      return String(this.worker?.resolved_value_type || '') === 'number' ? 'right' : 'left';
    },
    valueDisplay() {
      if (this.formulaError) return this.formulaError;
      const base = this.valueDisplayBase;
      if (!base) return '';
      const unit = this.valueUsesFullUnitLabel ? this.valueUnitLabels.name : this.valueUnitLabels.abbr;
      return unit ? `${base} ${unit}` : base;
    },
    isFormulaValue() {
      return this.isValue && !!this.worker?.formula?.source;
    },
    formulaError() {
      return this.isFormulaValue && this.worker?.formula_state?.status === 'error'
        ? String(this.worker.formula_state.error_code || '#VALUE!')
        : '';
    },
    numericValueHistory() {
      const points = [];
      for (const entry of this.valueHistoryRows) {
        const value = entry.rawValue;
        const numeric = typeof value === 'number' ? value : Number(value);
        if (!Number.isFinite(numeric) || value === true || value === false) continue;
        if (entry.resolvedValueType && entry.resolvedValueType !== 'number') continue;
        points.push({
          value: numeric,
          updatedAt: entry.updatedAt,
          time: entry.time,
        });
      }
      return points;
    },
    valueHistoryEnabled() {
      return this.isValue && !!this.worker?.save_history;
    },
    valueHistoryRows() {
      if (!this.valueHistoryEnabled) return [];
      const history = Array.isArray(this.worker?.history) ? this.worker.history : [];
      return history.map((entry, index) => {
        const updatedAt = String(entry?.updated_at || '').trim();
        const time = updatedAt ? Date.parse(updatedAt) : NaN;
        const rawValue = entry?.value;
        return {
          index,
          rawValue,
          displayValue: rawValue === null || rawValue === undefined ? '' : String(rawValue),
          updatedAt,
          displayTime: this.formatHistoryTimestamp(updatedAt),
          time: Number.isFinite(time) ? time : null,
          valueType: String(entry?.value_type || ''),
          resolvedValueType: String(entry?.resolved_value_type || ''),
        };
      });
    },
    hasNumericValueHistory() {
      return this.numericValueHistory.length > 0;
    },
    hasNumericValueSparkline() {
      return this.valueHistoryEnabled && this.valueTypeLabel === 'number' && this.numericValueHistory.length > 0;
    },
    valueSparklineTitle() {
      const count = this.numericValueHistory.length;
      return count === 1 ? 'Open graph for 1 recorded value' : `Open graph for ${count} recorded values`;
    },
    valueSparklinePoints() {
      return this.buildChartPoints(this.numericValueHistory, 120, 32, { top: 3, right: 2, bottom: 3, left: 2 });
    },
    valueSparklineSinglePoint() {
      return this.buildSingleChartPoint(this.numericValueHistory, 120, 32, { top: 3, right: 2, bottom: 3, left: 2 });
    },
    valueGraphTitle() {
      const name = String(this.worker?.name || '').trim();
      const ref = this.valueCellRef || 'Value';
      return name ? `${name} history` : `${ref} history`;
    },
    valueGraphAriaLabel() {
      return `Value history graph for ${this.valueGraphTitle}`;
    },
    valueGraphPoints() {
      return this.buildChartPoints(this.numericValueHistory, 640, 260, { top: 18, right: 14, bottom: 34, left: 54 });
    },
    valueGraphSinglePoint() {
      return this.buildSingleChartPoint(this.numericValueHistory, 640, 260, { top: 18, right: 14, bottom: 34, left: 54 });
    },
    valueGraphYTicks() {
      const values = this.numericValueHistory.map(point => point.value);
      if (!values.length) return [];
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = max - min || 1;
      return [max, min + range / 2, min].map(value => ({
        y: this.valueToChartY(value, min, max, 260, { top: 18, bottom: 34 }),
        label: this.formatCompactNumber(value),
      }));
    },
    valueGraphStartLabel() {
      return this.formatHistoryTime(this.numericValueHistory[0]);
    },
    valueGraphEndLabel() {
      return this.formatHistoryTime(this.numericValueHistory[this.numericValueHistory.length - 1]);
    },
    valueEditSourceText() {
      const name = String(this.worker?.name || '').trim();
      const unit = String(this.worker?.unit || '').trim();
      const source = this.worker?.formula?.source || this.storedValueText;
      return `${unit ? `${name}/${unit}` : name}:${source}`;
    },
    showCompactValue() {
      return this.isValue && this.effectiveLayoutMode === 'small';
    },
    showVerticalResizeHandle() {
      return !!(this.showsVerticalResizeControl && (this.hoveredVerticalResize || this.isVerticalResizing));
    },
    hasExpandableCardContent() {
      return this.isPaused || this.taskQueueCount > 0 || this.workerState !== 'idle';
    },
    showsVerticalResizeControl() {
      return this.isSelected && this.hasExpandableCardContent;
    },
    outputRequestToken() {
      const taskId = this.worker?.task_queue?.[0] || '';
      const startedAt = this.worker?.started_at || '';
      const serviceStartedAt = this.worker?.service_state?.started_at || '';
      return `${this.workerState}|${taskId}|${startedAt}|${serviceStartedAt}`;
    },
    verticalResizeHandleStyle() {
      const width = 42;
      const cardWidth = this.$el?.getBoundingClientRect?.().width || 220;
      const x = Number.isFinite(this.verticalResizeX) && this.verticalResizeX > 0 ? this.verticalResizeX : cardWidth / 2;
      return {
        left: `${Math.max(6, Math.min(cardWidth - width - 6, x - (width / 2)))}px`,
        bottom: '2px',
      };
    }
  },
  watch: {
    isSelected(next) {
      if (!next) this.hoveredVerticalResize = false;
    },
    workerNameLabel() {
      this.$nextTick(() => this.recalculateTitlePortVisibility());
    },
    titlePortCandidate() {
      this.$nextTick(() => this.recalculateTitlePortVisibility());
    },
    showOutputPane() {
      this.$nextTick(() => this.ensureOutputCatchup());
    },
    workerIcon() {
      this.$nextTick(() => renderLucideIcons(this.$el));
    },
    taskQueueCount() {
      this.$nextTick(() => renderLucideIcons(this.$el));
    },
    effectiveLayoutMode() {
      this.$nextTick(() => renderLucideIcons(this.$el));
    },
    showMenu(next) {
      if (next) {
        this.$nextTick(() => {
          renderLucideIcons(this.$refs.menu);
          this.repositionMenuWithinViewport();
        });
      } else {
        this.menuAnchorPos = null;
      }
    },
    menuIconToken() {
      if (this.showMenu) this.$nextTick(() => renderLucideIcons(this.$refs.menu));
    },
    needsElapsedTimer() {
      this.syncElapsedTimer();
    },
    workerState() {
      this.$nextTick(() => this.ensureOutputCatchup(true));
    },
    outputRequestToken() {
      this.$nextTick(() => this.ensureOutputCatchup(true));
    },
  },
  methods: {
    menuItems() {
      const menu = this.$refs.menu;
      if (!menu || typeof menu.querySelectorAll !== 'function') return [];
      return Array.from(menu.querySelectorAll('.worker-menu-item:not([disabled])'));
    },
    ensureOutputCatchup(force = false) {
      if (typeof this.requestOutputCatchup !== 'function') return;
      if (!this.showOutputPane) return;
      if (!(this.isWorking || this.isService)) return;
      this.requestOutputCatchup(this.slotIndex, {
        workspaceId: this.workspaceId,
        workerType: this.worker?.type,
        force,
      });
    },
    lookupTask(id) {
      return (this.taskById && this.taskById[id])
        || (this.tasks || []).find(task => task.id === id);
    },
    interpolateValuePlaceholders(template) {
      const text = String(template || '').trim();
      if (!text) return '';
      return text.replace(/\{([A-Za-z0-9][A-Za-z0-9 _.\-]{0,127})\}/g, (match, rawRef) => {
        const found = this.findValueWorkerForRef(rawRef);
        if (!found) return match;
        const value = found.value;
        return value === null || value === undefined ? '' : String(value);
      });
    },
    findValueWorkerForRef(rawRef) {
      const ref = String(rawRef || '').trim();
      if (!ref || !Array.isArray(this.allWorkers)) return null;
      const parsed = window.GridGeometry?.parseCellRef?.(ref);
      if (parsed) {
        return this.allWorkers.find(slot =>
          isValueWorker(slot) &&
          Number(slot?.col) === parsed.col &&
          Number(slot?.row) === parsed.row
        ) || null;
      }
      const needle = ref.toLocaleLowerCase();
      return this.allWorkers.find(slot =>
        isValueWorker(slot) &&
        String(slot?.name || '').trim().toLocaleLowerCase() === needle
      ) || null;
    },
    syncElapsedTimer() {
      if (!this.needsElapsedTimer) {
        if (this._timer) {
          clearInterval(this._timer);
          this._timer = null;
        }
        return;
      }
      if (!this._timer) {
        this._timer = setInterval(() => this.updateElapsed(), 1000);
      }
    },
    recalculateTitlePortVisibility() {
      const suffix = this.titlePortCandidate;
      if (!suffix) {
        if (this.showTitlePort) this.showTitlePort = false;
        return;
      }
      const nameEl = this.$refs.nameLabel;
      const measureEl = this.$refs.nameMeasure;
      if (!nameEl || !measureEl) return;
      const availableWidth = nameEl.clientWidth;
      if (!availableWidth) {
        if (this.showTitlePort) this.showTitlePort = false;
        return;
      }
      measureEl.textContent = `${this.workerNameLabel}${suffix}`;
      const fits = measureEl.offsetWidth <= availableWidth;
      if (this.showTitlePort !== fits) this.showTitlePort = fits;
    },
    onBodyClick() {
      if (this.isWorking || this.isService) {
        this.$emit('open-focus', this.slotIndex);
      }
    },
    onStatusPillClick() {
      if (this.isWorking || this.isService) {
        this.$emit('open-focus', this.slotIndex);
      }
    },
    openConfigFromIdleDetail() {
      if (!this.idleDetail || !this.canConfigure) return;
      this.$emit('configure', this.slotIndex);
    },
    onBodyDblClick() {
      if (this.isValue) {
        this.startValueEdit();
        return;
      }
      const taskId = this.queuedTasks.length ? this.queuedTasks[0].id : null;
      if (taskId) this.$emit('select-task', taskId);
    },
    onHeaderClick() {
      if (this.showCompactValue && !this.valueEditing) this.startCompactValueEdit();
    },
    onHeaderDblClick() {
      if (this.showCompactValue || this.valueEditing) return;
      this.$emit('configure', this.slotIndex);
    },
    parseValueEditText(text) {
      const raw = String(text || '').trim();
      if (raw.startsWith('=') || raw.startsWith("'=")) {
        return {
          name: String(this.worker?.name || '').trim(),
          unit: String(this.worker?.unit || '').trim(),
          value: raw,
        };
      }
      const colon = raw.indexOf(':');
      if (colon < 0) {
        return { name: String(this.worker?.name || '').trim(), unit: String(this.worker?.unit || '').trim(), value: raw };
      }
      const label = raw.slice(0, colon).trim();
      const slash = label.lastIndexOf('/');
      return {
        name: (slash >= 0 ? label.slice(0, slash) : label).trim(),
        unit: slash >= 0 ? label.slice(slash + 1).trim() : String(this.worker?.unit || '').trim(),
        value: raw.slice(colon + 1).trim(),
      };
    },
    validateValueEditText(text) {
      const valueType = String(this.worker?.value_type || 'auto');
      const parsed = this.valueEditIncludesName ? this.parseValueEditText(text) : { value: String(text || '').trim() };
      const trimmed = parsed.value;
      if (trimmed.startsWith('=')) return '';
      if (valueType === 'number' && !/^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(trimmed)) {
        return 'Enter a valid number.';
      }
      return '';
    },
    startValueEdit() {
      if (!this.isValue) return;
      this.valueEditIncludesName = false;
      this.valueEditText = this.worker?.formula?.source || this.storedValueText;
      this.valueEditError = '';
      this.valueEditing = true;
      this.$nextTick(() => {
        const input = this.$refs.valueEditInput;
        if (input && typeof input.focus === 'function') {
          input.focus();
          input.select?.();
        }
      });
    },
    startCompactValueEdit() {
      if (!this.isValue) return;
      this.valueEditIncludesName = true;
      this.valueEditText = this.valueEditSourceText;
      this.valueEditError = '';
      this.valueEditing = true;
      this.$nextTick(() => {
        const input = this.$refs.valueEditInput;
        if (input && typeof input.focus === 'function') {
          input.focus();
          input.select?.();
        }
      });
    },
    cancelValueEdit(options = {}) {
      const wasEditing = this.valueEditing;
      this.valueEditing = false;
      this.valueEditText = '';
      this.valueEditError = '';
      this.valueEditIncludesName = false;
      if (!wasEditing) return;
      this.$nextTick(() => {
        renderLucideIcons(this.$el);
        if (options && options.restoreGridFocus === true) {
          this.$emit('value-edit-ended');
        }
      });
    },
    commitValueEdit() {
      const error = this.validateValueEditText(this.valueEditText);
      if (error) {
        this.valueEditError = error;
        return;
      }
      const parsed = this.valueEditIncludesName
        ? this.parseValueEditText(this.valueEditText)
        : { value: String(this.valueEditText) };
      const isFormula = String(parsed.value || '').trim().startsWith('=');
      if (isFormula) {
        const fields = { formula_source: String(parsed.value).trim() };
        if (this.valueEditIncludesName) {
          fields.name = parsed.name;
          fields.unit = parsed.unit;
        }
        this.$root.saveWorkerConfig({
          slot: this.slotIndex,
          fields,
        });
        this.cancelValueEdit({ restoreGridFocus: true });
        return;
      }
      this.$root.saveWorkerConfig({
        slot: this.slotIndex,
        fields: this.valueEditIncludesName
          ? { name: parsed.name, unit: parsed.unit, value: parsed.value }
          : { value: parsed.value },
      });
      this.cancelValueEdit({ restoreGridFocus: true });
    },
    openValueHistory() {
      if (!this.valueHistoryEnabled) return;
      this.valueGraphOpen = true;
      this.$nextTick(() => this.$refs.valueGraphOverlay?.focus?.());
    },
    openValueGraph() {
      this.openValueHistory();
    },
    closeValueGraph() {
      this.valueGraphOpen = false;
    },
    saveValueHistory(history) {
      if (!this.valueHistoryEnabled) return;
      const nextHistory = Array.isArray(history) ? history : [];
      this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { history: nextHistory } });
    },
    deleteValueHistoryRow(index) {
      if (!this.valueHistoryEnabled) return;
      const history = Array.isArray(this.worker?.history) ? this.worker.history.slice() : [];
      if (!Number.isInteger(index) || index < 0 || index >= history.length) return;
      history.splice(index, 1);
      this.saveValueHistory(history);
    },
    clearValueHistory() {
      if (!this.valueHistoryEnabled || !this.valueHistoryRows.length) return;
      if (!window.confirm('Clear all value history rows?')) return;
      this.closeValueGraph();
      this.saveValueHistory([]);
    },
    exportValueHistoryCsv() {
      if (!this.valueHistoryRows.length) return;
      const headers = ['updated_at', 'value', 'value_type', 'resolved_value_type'];
      const rows = this.valueHistoryRows.map(row => [
        row.updatedAt,
        row.displayValue,
        row.valueType,
        row.resolvedValueType,
      ]);
      const csv = [headers, ...rows]
        .map(row => row.map(cell => this.csvCell(cell)).join(','))
        .join('\n') + '\n';
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${this.valueHistoryFilenameBase()}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
    csvCell(value) {
      const text = String(value ?? '');
      return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    },
    valueHistoryFilenameBase() {
      const label = String(this.worker?.name || this.valueCellRef || `slot-${Number(this.slotIndex) + 1}`)
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
      return `value-history-${label || 'value'}`;
    },
    chartXForIndex(index, count, width, inset) {
      const left = inset.left || 0;
      const right = inset.right || 0;
      if (count <= 1) return left + ((width - left - right) / 2);
      return left + (index / (count - 1)) * (width - left - right);
    },
    valueToChartY(value, min, max, height, inset) {
      const top = inset.top || 0;
      const bottom = inset.bottom || 0;
      const chartHeight = height - top - bottom;
      if (max === min) return top + chartHeight / 2;
      return top + (1 - ((value - min) / (max - min))) * chartHeight;
    },
    buildChartPoints(points, width, height, inset) {
      if (!Array.isArray(points) || points.length < 2) return '';
      const values = points.map(point => point.value);
      const min = Math.min(...values);
      const max = Math.max(...values);
      return points.map((point, index) => {
        const x = this.chartXForIndex(index, points.length, width, inset);
        const y = this.valueToChartY(point.value, min, max, height, inset);
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      }).join(' ');
    },
    buildSingleChartPoint(points, width, height, inset) {
      if (!Array.isArray(points) || points.length !== 1) return null;
      return {
        x: this.chartXForIndex(0, 1, width, inset),
        y: this.valueToChartY(points[0].value, points[0].value, points[0].value, height, inset),
      };
    },
    formatCompactNumber(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return '';
      return new Intl.NumberFormat(undefined, {
        notation: Math.abs(numeric) >= 10000 ? 'compact' : 'standard',
        maximumFractionDigits: Math.abs(numeric) >= 100 ? 0 : 2,
      }).format(numeric);
    },
    formatHistoryTime(point) {
      if (!point) return '';
      if (point.time) {
        return new Intl.DateTimeFormat(undefined, {
          month: 'short',
          day: 'numeric',
          hour: 'numeric',
          minute: '2-digit',
        }).format(new Date(point.time));
      }
      return point.updatedAt || '';
    },
    formatHistoryTimestamp(value) {
      const raw = String(value || '').trim();
      if (!raw) return '';
      const time = Date.parse(raw);
      if (!Number.isFinite(time)) return raw;
      return new Intl.DateTimeFormat(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      }).format(new Date(time));
    },
    canConnect(dir) {
      if (this.isValue) return false;
      return !!(this.neighborSlots && this.neighborSlots[dir] != null);
    },
    connectHandleArrow(dir) {
      return {
        up: '\u2191',
        down: '\u2193',
        left: '\u2190',
        right: '\u2192',
      }[dir] || '';
    },
    updateCardHoverState(e) {
      // Reveal at most one drag handle — whichever edge the cursor is closest
      // to, within a small threshold. This keeps the card body free of drag
      // affordances so ordinary clicks (e.g. to open the focus view) are
      // unobstructed, and guarantees we never show all four handles at once.
      const rect = this.$el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const threshold = 24;
      const downHandleZone = this.canConnect('down') && Math.abs(x - (rect.width / 2)) <= 18;
      if (this.showsVerticalResizeControl && y >= rect.height - threshold && !downHandleZone) {
        this.verticalResizeX = Math.max(21, Math.min(rect.width - 21, x));
        this.hoveredVerticalResize = true;
        this.hoveredHandle = null;
        return;
      }
      this.hoveredVerticalResize = false;
      const distances = { up: y, down: rect.height - y, left: x, right: rect.width - x };
      let nearest = null;
      let nearestDist = Infinity;
      for (const dir of ['up', 'down', 'left', 'right']) {
        if (!this.canConnect(dir)) continue;
        const d = distances[dir];
        if (d <= threshold && d < nearestDist) {
          nearest = dir;
          nearestDist = d;
        }
      }
      if (this.hoveredHandle !== nearest) this.hoveredHandle = nearest;
    },
    onCardMouseMove(e) {
      this.updateCardHoverState(e);
    },
    onCardMouseLeave() {
      this.hoveredHandle = null;
      this.hoveredVerticalResize = false;
    },
    onVerticalResizeHandleDown(e) {
      if (!this.showsVerticalResizeControl || e.button !== 0) return;
      e.preventDefault();
      this.$emit('vertical-resize-start', e);
    },
    onPointerDown(e) {
      if (e.button !== 0) return;
      if (e.target.closest('.card-height-resize-handle, .connect-handle, .status-pill, .worker-menu-btn, .worker-menu, button, input, select, textarea')) return;
      this.shiftDragIntent = !!e.shiftKey;
      if (!e.shiftKey || typeof this.buildWorkerDragPayload !== 'function') return;
      const payload = this.buildWorkerDragPayload(this.slotIndex, {
        singleton: true,
        clientX: e.clientX,
        clientY: e.clientY,
      });
      this.pointerWorkerDrag = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        payload,
        active: false,
      };
      window._bullpenWorkerDrag = payload;
      this.isDragging = true;
      document.body.classList.add('worker-singleton-dragging');
      this.$el.setPointerCapture?.(e.pointerId);
      e.preventDefault();
      e.stopPropagation();
    },
    onPointerMove(e) {
      this.updateCardHoverState(e);
      const drag = this.pointerWorkerDrag;
      if (!drag || drag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      if (!drag.active && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) <= 5) return;
      drag.active = true;
      window._bullpenWorkerDrag = drag.payload;
      if (typeof this.updateSingletonWorkerDrag === 'function') {
        this.updateSingletonWorkerDrag(drag.payload.source, e);
      }
    },
    onPointerUp(e) {
      const drag = this.pointerWorkerDrag;
      if (drag) {
        if (drag.active && typeof this.endSingletonWorkerDrag === 'function') {
          this.endSingletonWorkerDrag(drag.payload.source, e);
          window._bullpenSuppressWorkerClickUntil = Date.now() + 250;
        } else if (typeof this.cancelSingletonWorkerDrag === 'function') {
          this.cancelSingletonWorkerDrag();
        }
        this.pointerWorkerDrag = null;
        this.$el.releasePointerCapture?.(drag.pointerId);
        e.preventDefault();
        e.stopPropagation();
      }
      this.shiftDragIntent = false;
      this.isDragging = false;
      if (window._bullpenWorkerDrag?.source === drag?.payload?.source) window._bullpenWorkerDrag = null;
      document.body.classList.remove('worker-singleton-dragging');
    },
    onPointerCancel(e) {
      const drag = this.pointerWorkerDrag;
      if (drag) {
        if (typeof this.cancelSingletonWorkerDrag === 'function') this.cancelSingletonWorkerDrag();
        this.pointerWorkerDrag = null;
        this.$el.releasePointerCapture?.(drag.pointerId);
      }
      this.shiftDragIntent = false;
      this.isDragging = false;
      if (window._bullpenWorkerDrag?.source === drag?.payload?.source) window._bullpenWorkerDrag = null;
      document.body.classList.remove('worker-singleton-dragging');
    },
    onPointerLostCapture(e) {
      if (this.pointerWorkerDrag && this.pointerWorkerDrag.pointerId === e.pointerId) {
        this.onPointerCancel(e);
      }
    },
    onDragStart(e) {
      if (this.pointerWorkerDrag) {
        e.preventDefault();
        return;
      }
      const singleton = !!(e.shiftKey || this.shiftDragIntent);
      const payload = typeof this.buildWorkerDragPayload === 'function'
        ? this.buildWorkerDragPayload(this.slotIndex, {
          singleton,
          clientX: e.clientX,
          clientY: e.clientY,
        })
        : { source: this.slotIndex, group: [this.slotIndex] };
      e.dataTransfer.setData('application/x-worker-slot', String(this.slotIndex));
      try {
        e.dataTransfer.setData('application/x-worker-group', JSON.stringify(payload));
      } catch (_err) { /* ignore */ }
      e.dataTransfer.effectAllowed = 'move';
      window._bullpenWorkerDrag = payload;
      this.isDragging = true;
      this.removeDragImage();
      if (typeof this.buildWorkerDragImage === 'function') {
        const dragImage = this.buildWorkerDragImage(this.slotIndex, {
          clientX: e.clientX,
          clientY: e.clientY,
        }, { singleton });
        if (dragImage?.element && typeof e.dataTransfer.setDragImage === 'function') {
          const offsetX = Number.isFinite(Number(dragImage.offsetX)) ? Number(dragImage.offsetX) : 0;
          const offsetY = Number.isFinite(Number(dragImage.offsetY)) ? Number(dragImage.offsetY) : 0;
          e.dataTransfer.setDragImage(dragImage.element, offsetX, offsetY);
          this._dragImageEl = dragImage.element;
        }
      }
    },
    onDragEnd() {
      window._bullpenWorkerDrag = null;
      this.shiftDragIntent = false;
      this.isDragging = false;
      this.removeDragImage();
    },
    onHandleDragStart(dir, e) {
      if (!this.canConnect(dir)) {
        e.preventDefault();
        return;
      }
      const payload = { source: this.slotIndex, direction: dir, target: this.neighborSlots[dir] };
      // Custom MIME type stores the full payload; a global mirror lets dragover
      // handlers know the intended target without having to read dataTransfer
      // (which is restricted to drop events in most browsers).
      try {
        e.dataTransfer.setData('application/x-worker-connect', JSON.stringify(payload));
      } catch (_err) { /* ignore */ }
      e.dataTransfer.effectAllowed = 'link';
      window._bullpenConnectDrag = payload;
    },
    onHandleDragEnd() {
      window._bullpenConnectDrag = null;
    },
    onDragOver(e) {
      const types = e.dataTransfer.types;
      const isTaskDrag = types.includes(window.BULLPEN_TASK_DND_MIME) || (window.BULLPEN_TASK_DRAG_ACTIVE && types.includes('text/plain'));
      this.hoveredVerticalResize = false;
      if (types.includes('application/x-worker-connect')) {
        const drag = window._bullpenConnectDrag;
        if (drag && drag.target === this.slotIndex) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'link';
          this.connectTarget = true;
        } else {
          // Do not call preventDefault — cursor shows "no drop" on non-targets.
          e.dataTransfer.dropEffect = 'none';
        }
        return;
      }
      if (
        isTaskDrag ||
        types.includes('application/x-worker-slot') ||
        types.includes('application/x-worker-group') ||
        window._bullpenWorkerDrag
      ) {
        if (types.includes('application/x-worker-slot') || types.includes('application/x-worker-group') || window._bullpenWorkerDrag) {
          const drag = window._bullpenWorkerDrag;
          const source = Number(drag?.source);
          const canDrop = Number.isInteger(source)
            ? (typeof this.canDropWorkerAtSlot === 'function' ? !!this.canDropWorkerAtSlot(source, this.slotIndex, e) : true)
            : false;
          if (canDrop) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            this.dragOver = true;
          } else {
            e.dataTransfer.dropEffect = 'none';
            this.dragOver = false;
          }
          return;
        }
        if (isTaskDrag && !this.acceptsTaskDrop) {
          e.dataTransfer.dropEffect = 'none';
          this.dragOver = false;
          return;
        }
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        this.dragOver = true;
      }
    },
    onDragLeave() { this.dragOver = false; this.connectTarget = false; },
    onDrop(e) {
      e.preventDefault();
      this.dragOver = false;
      this.connectTarget = false;
      const connectData = e.dataTransfer.getData('application/x-worker-connect');
      if (connectData) {
        e.stopPropagation();
        try {
          const payload = JSON.parse(connectData);
          if (payload && payload.target === this.slotIndex) {
            this.$root.saveWorkerConfig({ slot: payload.source, fields: { disposition: 'pass:' + payload.direction } });
          }
        } catch (_err) { /* ignore malformed payload */ }
        window._bullpenConnectDrag = null;
        return;
      }
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      const dragSource = fromSlot !== '' ? Number(fromSlot) : Number(window._bullpenWorkerDrag?.source);
      if (Number.isInteger(dragSource)) {
        if (typeof this.dropWorkerOnSlot === 'function') {
          const handled = this.dropWorkerOnSlot(dragSource, this.slotIndex, e);
          if (handled) {
            e.stopPropagation();
          }
        } else if (dragSource !== this.slotIndex) {
          e.stopPropagation();
          this.$root.moveWorker(dragSource, this.slotIndex);
        }
        return;
      }
      const taskId = e.dataTransfer.getData(window.BULLPEN_TASK_DND_MIME)
        || (window.BULLPEN_TASK_DRAG_ACTIVE ? e.dataTransfer.getData('text/plain') : '');
      try {
        if (taskId && this.acceptsTaskDrop) {
          e.stopPropagation();
          this.$root.assignTask(taskId, this.slotIndex);
        }
      } finally {
        if (window.BULLPEN_TASK_DRAG_ACTIVE) {
          window.dispatchEvent(new CustomEvent('bullpen:task-drag:end', { detail: { taskId } }));
        }
      }
    },
    toggleMenu() {
      if (this.showMenu) {
        this.showMenu = false;
        this.menuAnchorPos = null;
        return;
      }
      const btn = this.$refs.menuBtn;
      if (btn) {
        const rect = btn.getBoundingClientRect();
        const menuWidth = 210;
        let left = rect.right - menuWidth;
        if (left < 4) left = rect.left;
        this.menuAnchorPos = { top: rect.bottom + 4, left };
        this.menuPos = { ...this.menuAnchorPos };
      }
      this.showMenu = true;
      this.$emit('menu-opened');
      this.$nextTick(() => {
        this.repositionMenuWithinViewport();
        const [first] = this.menuItems();
        if (first) first.focus();
      });
    },
    openMenuAndFocus() {
      if (!this.showMenu) this.toggleMenu();
    },
    closeMenuAndRestoreFocus() {
      this.showMenu = false;
      this.menuAnchorPos = null;
      this.$emit('menu-closed');
    },
    repositionMenuWithinViewport() {
      if (!this.showMenu || !this.menuAnchorPos) return;
      const menu = this.$refs.menu;
      if (!menu || typeof menu.getBoundingClientRect !== 'function') return;
      const margin = 8;
      const rect = menu.getBoundingClientRect();
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
      const maxLeft = Math.max(margin, viewportWidth - rect.width - margin);
      const maxTop = Math.max(margin, viewportHeight - rect.height - margin);
      const left = Math.min(Math.max(this.menuAnchorPos.left, margin), maxLeft);
      const top = Math.min(Math.max(this.menuAnchorPos.top, margin), maxTop);
      if (left !== this.menuPos.left || top !== this.menuPos.top) {
        this.menuPos = { top, left };
      }
    },
    onMenuKeydown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.closeMenuAndRestoreFocus();
        return;
      }
      const items = this.menuItems();
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
    menuEdit() {
      this.closeMenuAndRestoreFocus();
      this.$emit('configure', this.slotIndex);
    },
    menuRun() {
      this.closeMenuAndRestoreFocus();
      this.$root.startWorkerSlot(this.slotIndex);
    },
    menuStop() {
      this.closeMenuAndRestoreFocus();
      this.$root.stopWorkerSlot(this.slotIndex);
    },
    menuRestart() {
      this.closeMenuAndRestoreFocus();
      this.$root.restartServiceSlot(this.slotIndex);
    },
    menuPause() {
      this.closeMenuAndRestoreFocus();
      this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { paused: true } });
    },
    menuUnpause() {
      this.closeMenuAndRestoreFocus();
      this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { paused: false } });
    },
    menuDuplicate() {
      this.closeMenuAndRestoreFocus();
      this.$root.duplicateWorker(this.slotIndex);
    },
    menuCopyWorker() {
      this.closeMenuAndRestoreFocus();
      this.$emit('copy-worker', this.slotIndex);
    },
    menuExportWorker() {
      this.closeMenuAndRestoreFocus();
      this.$root.exportWorker(this.slotIndex);
    },
    menuShowValueHistory() {
      this.closeMenuAndRestoreFocus();
      this.openValueHistory();
    },
    menuClearValueHistory() {
      this.closeMenuAndRestoreFocus();
      this.clearValueHistory();
    },
    menuWatch() {
      this.closeMenuAndRestoreFocus();
      this.$emit('open-focus', this.slotIndex);
    },
    menuOpenSite() {
      this.closeMenuAndRestoreFocus();
      this.$root.openServiceSite(this.slotIndex);
    },
    menuCopyTo() {
      this.closeMenuAndRestoreFocus();
      this.$emit('transfer', { slot: this.slotIndex, mode: 'copy' });
    },
    menuMoveTo() {
      this.closeMenuAndRestoreFocus();
      this.$emit('transfer', { slot: this.slotIndex, mode: 'move' });
    },
    menuDelete() {
      this.closeMenuAndRestoreFocus();
      this.$emit('delete-worker', this.slotIndex);
    },
    menuScoped(action, scope) {
      this.closeMenuAndRestoreFocus();
      this.$emit('worker-scope-action', { action, scope, slot: this.slotIndex });
    },
    removeDragImage() {
      if (this._dragImageEl && this._dragImageEl.parentNode) {
        this._dragImageEl.parentNode.removeChild(this._dragImageEl);
      }
      this._dragImageEl = null;
    },
    updateElapsed() {
      if (!this.isWorking || !this.worker?.started_at) {
        this.elapsed = '0s';
        return;
      }
      const start = new Date(this.worker.started_at).getTime();
      const now = Date.now();
      const secs = Math.floor((now - start) / 1000);
      if (secs < 0 || Number.isNaN(secs)) {
        this.elapsed = '0s';
        return;
      }
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = secs % 60;
      if (h > 0) {
        this.elapsed = `${h}h ${m}m ${s}s`;
        return;
      }
      this.elapsed = m > 0 ? `${m}m ${s}s` : `${s}s`;
    },
  }
};
