const BullpenTab = {
  props: ['layout', 'config', 'profiles', 'tasks'],
  emits: ['add-worker', 'configure-worker'],
  components: { WorkerCard },
  data() {
    return {
      showLibrary: false,
      selectedAddSlot: null,
    };
  },
  template: `
    <div class="bullpen-grid-container">
      <div class="bullpen-header">
        <span>Bullpen Grid ({{ rows }}&times;{{ cols }})</span>
        <div class="bullpen-header-actions">
          <select class="form-select" :value="rows + 'x' + cols" @change="onGridResize">
            <option v-for="opt in gridOptions" :key="opt" :value="opt">{{ opt }}</option>
          </select>
        </div>
      </div>
      <div class="bullpen-grid" :style="gridStyle">
        <template v-for="i in totalSlots" :key="i">
          <WorkerCard
            v-if="getSlot(i - 1)"
            :worker="getSlot(i - 1)"
            :slot-index="i - 1"
            :tasks="tasks"
            @configure="$emit('configure-worker', $event)"
          />
          <div v-else class="grid-slot empty-slot"
               @click="openLibrary(i - 1)"
               @dragover.prevent
               @drop="onDropOnEmpty($event, i - 1)">
            <span class="slot-placeholder">+</span>
          </div>
        </template>
      </div>

      <!-- Profile library popup -->
      <div v-if="showLibrary" class="modal-overlay" @click.self="showLibrary = false">
        <div class="modal">
          <div class="modal-header">
            <h2>Add Worker</h2>
            <button class="btn btn-icon" @click="showLibrary = false">&times;</button>
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
      return (this.profiles || []).slice().sort((a, b) => a.name.localeCompare(b.name));
    }
  },
  methods: {
    getSlot(index) {
      return this.layout?.slots?.[index] || null;
    },
    openLibrary(slotIndex) {
      this.selectedAddSlot = slotIndex;
      this.showLibrary = true;
    },
    addFromLibrary(profileId) {
      this.$emit('add-worker', { slot: this.selectedAddSlot, profile: profileId });
      this.showLibrary = false;
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
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      if (fromSlot !== '') {
        this.$root.moveWorker(Number(fromSlot), slotIndex);
      }
    }
  }
};
