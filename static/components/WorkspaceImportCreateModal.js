const WorkspaceImportCreateModal = {
  props: ['visible', 'preview', 'projectsRoot'],
  emits: ['close', 'apply'],
  data() {
    return { projectName: '' };
  },
  watch: {
    visible(next) {
      if (next) this.projectName = this.preview?.proposed_name || 'Imported project';
    },
    preview(next) {
      if (this.visible) this.projectName = next?.proposed_name || 'Imported project';
    },
  },
  computed: {
    projectSlug() {
      const normalized = String(this.projectName || '')
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 80)
        .replace(/-+$/g, '');
      return normalized || 'imported-project';
    },
    destinationLabel() {
      if (this.projectsRoot) return `${this.projectsRoot.replace(/\/$/, '')}/${this.projectSlug}`;
      return `${this.projectSlug} (beside the current project)`;
    },
    counts() {
      return [
        ['Workers', Number(this.preview?.workers || 0)],
        ['Tickets', Number(this.preview?.tickets || 0)],
        ['Archived tickets', Number(this.preview?.archived_tickets || 0)],
        ['Profiles', Number(this.preview?.profiles || 0)],
      ];
    },
    canSubmit() {
      return Boolean(String(this.projectName || '').trim());
    },
  },
  methods: {
    submit() {
      if (!this.canSubmit) return;
      this.$emit('apply', { name: this.projectName.trim() });
    },
  },
  template: `
    <div v-if="visible && preview" class="modal-overlay" @click.self="$emit('close')" @keydown.escape="$emit('close')" @keydown.meta.enter="submit" tabindex="0">
      <div class="modal workspace-import-create-modal">
        <div class="modal-header">
          <h2>Import as New Project</h2>
          <button class="btn btn-icon" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <label class="form-label">
            Project name
            <input class="form-input" v-model="projectName" maxlength="100" autofocus>
          </label>
          <div class="bento-review-section">
            <div class="bento-review-heading">Destination</div>
            <code>{{ destinationLabel }}</code>
          </div>
          <div class="bento-review-section">
            <div class="bento-review-heading">Bullpen state</div>
            <div v-for="entry in counts" :key="entry[0]" class="bento-review-item">
              <span>{{ entry[0] }}</span>
              <span class="bento-review-count">{{ entry[1] }}</span>
            </div>
          </div>
          <div class="bento-review-section">
            <div class="bento-review-heading">Important</div>
            <ul class="bento-review-warnings">
              <li>This creates a new project and never changes the selected project.</li>
              <li>Project repository and ordinary workspace files are not included in this archive.</li>
              <li>Imported workers are stopped and automation starts paused.</li>
            </ul>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="$emit('close')">Cancel</button>
          <button class="btn btn-primary" :disabled="!canSubmit" @click="submit">Create Project</button>
        </div>
      </div>
    </div>
  `,
};
