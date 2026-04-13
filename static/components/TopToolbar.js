const TopToolbar = {
  props: ['projectName', 'connected', 'themes', 'activeTheme', 'ambientPresets', 'ambientPreset', 'ambientVolume'],
  emits: [
    'toggle-left-pane',
    'set-theme',
    'set-ambient-preset',
    'set-ambient-volume',
    'export-workspace',
    'export-all',
    'import-workspace',
    'import-all',
  ],
  data() {
    return { showMainMenu: false };
  },
  mounted() {
    document.addEventListener('click', this.onGlobalClick);
  },
  beforeUnmount() {
    document.removeEventListener('click', this.onGlobalClick);
  },
  methods: {
    toggleMainMenu() {
      this.showMainMenu = !this.showMainMenu;
    },
    onGlobalClick() {
      this.showMainMenu = false;
    },
    onToggleLeftPane() {
      this.showMainMenu = false;
      this.$emit('toggle-left-pane');
    },
    onExportWorkspace() {
      this.showMainMenu = false;
      this.$emit('export-workspace');
    },
    onExportAll() {
      this.showMainMenu = false;
      this.$emit('export-all');
    },
    triggerImportWorkspace() {
      if (!this.$refs.workspaceImportInput) return;
      this.$refs.workspaceImportInput.value = '';
      this.$refs.workspaceImportInput.click();
      this.showMainMenu = false;
    },
    triggerImportAll() {
      if (!this.$refs.allImportInput) return;
      this.$refs.allImportInput.value = '';
      this.$refs.allImportInput.click();
      this.showMainMenu = false;
    },
    onImportWorkspaceSelected(event) {
      const file = event?.target?.files?.[0];
      if (!file) return;
      this.$emit('import-workspace', file);
    },
    onImportAllSelected(event) {
      const file = event?.target?.files?.[0];
      if (!file) return;
      this.$emit('import-all', file);
    },
  },
  template: `
    <div class="top-toolbar">
      <div class="toolbar-left">
        <div class="toolbar-menu-wrap" @click.stop>
          <button class="btn btn-icon" @click="toggleMainMenu" title="Main menu">&#9776;</button>
          <div v-if="showMainMenu" class="project-menu toolbar-menu">
            <button class="project-menu-item" @click="onToggleLeftPane">Toggle Left Pane</button>
            <button class="project-menu-item" @click="onExportWorkspace">Export Workspace</button>
            <button class="project-menu-item" @click="onExportAll">Export All</button>
            <button class="project-menu-item" @click="triggerImportWorkspace">Import Workspace</button>
            <button class="project-menu-item" @click="triggerImportAll">Import All</button>
          </div>
          <input
            ref="workspaceImportInput"
            type="file"
            accept=".zip,application/zip"
            class="toolbar-import-input"
            @change="onImportWorkspaceSelected"
          >
          <input
            ref="allImportInput"
            type="file"
            accept=".zip,application/zip"
            class="toolbar-import-input"
            @change="onImportAllSelected"
          >
        </div>
        <span class="toolbar-name">Bullpen<span v-if="projectName"> / {{ projectName }}</span></span>
      </div>
      <div class="toolbar-center">
      </div>
      <div class="toolbar-right">
        <div class="toolbar-audio">
          <label class="toolbar-audio-label" for="ambient-preset">Ambient</label>
          <select id="ambient-preset" class="form-select toolbar-audio-select" :value="ambientPreset || ''" @change="$emit('set-ambient-preset', $event.target.value)" title="Ambient sound">
            <option value="">Off</option>
            <option v-for="p in ambientPresets || []" :key="p.key" :value="p.key">{{ p.label }}</option>
          </select>
          <label class="toolbar-audio-label" for="ambient-volume">Vol</label>
          <input
            id="ambient-volume"
            class="toolbar-audio-volume"
            type="range"
            min="0"
            max="100"
            step="1"
            :value="ambientVolume"
            @input="$emit('set-ambient-volume', Number($event.target.value))"
            title="Ambient volume"
          >
          <span class="toolbar-audio-value">{{ ambientVolume }}%</span>
        </div>
        <select class="form-select theme-select" :value="activeTheme" @change="$emit('set-theme', $event.target.value)" title="Theme">
          <option v-for="t in themes || []" :key="t.id" :value="t.id">{{ t.label }}</option>
        </select>
        <span class="connection-dot" :class="{ connected }"></span>
      </div>
    </div>
  `
};
