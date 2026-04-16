const BullpenTab = {
  UNCONFIGURED_PROFILE_ID: 'unconfigured-worker',
  props: ['layout', 'config', 'profiles', 'tasks', 'workspace', 'multipleWorkspaces'],
  emits: ['add-worker', 'configure-worker', 'select-task', 'open-focus', 'transfer-worker'],
  components: { WorkerCard },
  data() {
    return {
      showLibrary: false,
      selectedAddSlot: null,
    };
  },
  template: `
    <div class="bullpen-grid-container">
      <div class="bullpen-grid" :style="gridStyle">
        <template v-for="i in totalSlots" :key="i">
          <WorkerCard
            v-if="getSlot(i - 1)"
            :worker="getSlot(i - 1)"
            :slot-index="i - 1"
            :tasks="tasks"
            :output-lines="$root.outputBuffers?.[i - 1] || []"
            :multiple-workspaces="multipleWorkspaces"
            :neighbor-slots="neighborSlotsMap[i - 1]"
            @configure="$emit('configure-worker', $event)"
            @select-task="$emit('select-task', $event)"
            @open-focus="$emit('open-focus', $event)"
            @transfer="$emit('transfer-worker', $event)"
          />
          <div v-else class="grid-slot empty-slot"
               @click="openLibrary(i - 1)"
               @dragover.prevent
               @drop.prevent="onDropOnEmpty($event, i - 1)">
            <span class="slot-placeholder">+</span>
          </div>
        </template>
      </div>

      <!-- Profile library popup -->
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
    workspaceShort() {
      if (!this.workspace) return '';
      const parts = this.workspace.split('/');
      return parts.slice(-2).join('/');
    },
    rows() { return this.config?.grid?.rows || 4; },
    cols() { return this.config?.grid?.cols || 6; },
    totalSlots() { return this.rows * this.cols; },
    gridStyle() {
      return {
        gridTemplateColumns: `repeat(${this.cols}, 1fr)`,
        gridTemplateRows: `repeat(${this.rows}, minmax(120px, 1fr))`,
      };
    },
    gridOptions() {
      const opts = [];
      for (let r = 2; r <= 7; r++) {
        for (let c = 2; c <= 10; c++) {
          opts.push(`${r}x${c}`);
        }
      }
      return opts;
    },
    maxOccupiedSlot() {
      const slots = this.layout?.slots || [];
      let max = -1;
      for (let i = 0; i < slots.length; i++) {
        if (slots[i]) max = i;
      }
      return max;
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
      // For each occupied slot, compute the slot index of its occupied neighbor
      // in each of the four cardinal directions. Returns null when the source
      // is at the grid edge or the neighbor cell is empty — this disables the
      // corresponding drag handle in the UI.
      const slots = this.layout?.slots || [];
      const cols = this.cols;
      const rows = this.rows;
      const map = {};
      for (let i = 0; i < this.totalSlots; i++) {
        const r = Math.floor(i / cols);
        const c = i % cols;
        const up = r > 0 ? (r - 1) * cols + c : -1;
        const down = r < rows - 1 ? (r + 1) * cols + c : -1;
        const left = c > 0 ? r * cols + (c - 1) : -1;
        const right = c < cols - 1 ? r * cols + (c + 1) : -1;
        map[i] = {
          up: up >= 0 && slots[up] ? up : null,
          down: down >= 0 && slots[down] ? down : null,
          left: left >= 0 && slots[left] ? left : null,
          right: right >= 0 && slots[right] ? right : null,
        };
      }
      return map;
    }
  },
  methods: {
    getSlot(index) {
      return this.layout?.slots?.[index] || null;
    },
    openLibrary(slotIndex) {
      this.selectedAddSlot = slotIndex;
      this.showLibrary = true;
      this.$nextTick(() => this.$refs.libraryOverlay?.focus());
    },
    closeLibrary() {
      this.showLibrary = false;
      this.selectedAddSlot = null;
    },
    addFromLibrary(profileId) {
      this.$emit('add-worker', { slot: this.selectedAddSlot, profile: profileId });
      this.closeLibrary();
    },
    onGridResize(e) {
      const [rows, cols] = e.target.value.split('x').map(Number);
      const newTotal = rows * cols;
      if (this.maxOccupiedSlot >= newTotal) {
        alert(`Cannot resize: worker in slot ${this.maxOccupiedSlot + 1} would be displaced. Move or remove workers first.`);
        e.target.value = this.rows + 'x' + this.cols;
        return;
      }
      this.$root.updateConfig({ grid: { rows, cols } });
    },
    onDropOnEmpty(e, slotIndex) {
      e.preventDefault();
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      if (fromSlot !== '') {
        this.$root.moveWorker(Number(fromSlot), slotIndex);
      }
    }
  }
};
