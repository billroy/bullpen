const WorkerTransferModal = {
  props: ['visible', 'worker', 'slotIndex', 'slotIndices', 'mode', 'projects', 'activeWorkspaceId'],
  emits: ['close', 'transfer'],
  data() {
    return {
      selectedWorkspaceId: null,
      copyProfile: false,
    };
  },
  template: `
    <div v-if="visible && worker" class="modal-overlay" @click.self="$emit('close')" @keydown.escape="$emit('close')" tabindex="0" ref="overlay">
      <div class="modal" style="max-width: 420px;">
        <div class="modal-header">
          <h2>{{ mode === 'move' ? 'Move' : 'Copy' }} {{ isGroup ? 'Workers' : 'Worker' }}</h2>
          <button class="btn btn-icon" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <p style="margin: 0 0 12px;">
            {{ mode === 'move' ? 'Move' : 'Copy' }}
            <strong>{{ transferSubject }}</strong> to another workspace.
          </p>
          <label class="form-label">
            Destination Workspace
            <select class="form-select" v-model="selectedWorkspaceId" ref="wsSelect">
              <option :value="null" disabled>Select a workspace...</option>
              <option v-for="p in otherProjects" :key="p.id" :value="p.id">
                {{ p.name }}
              </option>
            </select>
          </label>
          <label v-if="worker.profile" class="form-label" style="display: flex; align-items: center; gap: 8px; margin-top: 8px;">
            <input type="checkbox" v-model="copyProfile">
            Copy worker profile to destination
          </label>
          <div v-if="worker.type === 'shell' || worker.type === 'service'" class="shell-warning" style="margin-top: 12px;">
            <strong>{{ worker.type === 'service' ? 'Service' : 'Shell' }} worker:</strong> the command and env values transfer
            in plaintext. Review them before sending to another workspace.
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="$emit('close')">Cancel</button>
          <button class="btn btn-primary" @click="submit" :disabled="!selectedWorkspaceId">
            {{ mode === 'move' ? 'Move' : 'Copy' }}
          </button>
        </div>
      </div>
    </div>
  `,
  computed: {
    otherProjects() {
      return (this.projects || []).filter(p => p.id !== this.activeWorkspaceId);
    },
    resolvedSlots() {
      const slots = Array.isArray(this.slotIndices) ? this.slotIndices.map(Number).filter(Number.isInteger) : [];
      if (slots.length) return slots;
      return Number.isInteger(Number(this.slotIndex)) ? [Number(this.slotIndex)] : [];
    },
    isGroup() {
      return this.resolvedSlots.length > 1;
    },
    transferSubject() {
      return this.isGroup ? `${this.resolvedSlots.length} workers` : (this.worker?.name || 'Worker');
    },
  },
  watch: {
    visible(v) {
      if (v) {
        this.selectedWorkspaceId = null;
        this.copyProfile = false;
        this.$nextTick(() => {
          if (this.$refs.overlay) this.$refs.overlay.focus();
        });
      }
    },
  },
  methods: {
    submit() {
      if (!this.selectedWorkspaceId) return;
      this.$emit('transfer', {
        source_workspace_id: this.activeWorkspaceId,
        source_slot: this.slotIndex,
        source_slots: this.resolvedSlots,
        dest_workspace_id: this.selectedWorkspaceId,
        dest_slot: null,
        mode: this.mode,
        copy_profile: this.copyProfile,
      });
    },
  },
};
