const TopToolbar = {
  props: ['projectName', 'projectPath', 'connected', 'themes', 'activeTheme', 'ambientPresets', 'ambientPreset', 'ambientVolume', 'quickCreateClearToken'],
  emits: [
    'toggle-left-pane',
    'export-workers',
    'set-theme',
    'set-ambient-preset',
    'set-ambient-volume',
    'export-workspace',
    'export-all',
    'import-workers',
    'import-workspace',
    'import-all',
    'quick-create-task',
    'run-command-bar',
  ],
  data() {
    return {
      showMainMenu: false,
      quickCreateText: '',
      showEventSoundsMenu: false,
      eventSoundFlags: (window.EventSounds && window.EventSounds.getFlags())
        || { ...(window.EVENT_SOUND_FLAGS_DEFAULTS || {}) },
      eventSoundLabels: window.EVENT_SOUND_LABELS || [],
    };
  },
  watch: {
    quickCreateClearToken() {
      this.quickCreateText = '';
    },
  },
  mounted() {
    document.addEventListener('click', this.onGlobalClick);
    window.addEventListener('bullpen:menu:close-main', this.onExternalCloseMainMenu);
    renderLucideIcons(this.$el);
  },
  updated() {
    renderLucideIcons(this.$el);
  },
  beforeUnmount() {
    document.removeEventListener('click', this.onGlobalClick);
    window.removeEventListener('bullpen:menu:close-main', this.onExternalCloseMainMenu);
  },
  methods: {
    toggleMainMenu() {
      this.showMainMenu = !this.showMainMenu;
      if (this.showMainMenu) {
        this.showEventSoundsMenu = false;
        window.dispatchEvent(new Event('bullpen:menu:close-projects'));
      }
    },
    onGlobalClick() {
      this.showMainMenu = false;
      this.showEventSoundsMenu = false;
    },
    toggleEventSoundsMenu() {
      this.showEventSoundsMenu = !this.showEventSoundsMenu;
      if (this.showEventSoundsMenu) this.showMainMenu = false;
    },
    onToggleEventSoundFlag(key) {
      if (!window.EventSounds) return;
      const next = !this.eventSoundFlags[key];
      window.EventSounds.setFlag(key, next);
      this.eventSoundFlags = { ...this.eventSoundFlags, [key]: next };
    },
    onPreviewEventSound(previewMethod) {
      if (window.ambientAudio && typeof window.ambientAudio[previewMethod] === 'function') {
        window.ambientAudio.unlock();
        window.ambientAudio[previewMethod]();
      }
    },
    onExternalCloseMainMenu() {
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
    onExportWorkers() {
      this.showMainMenu = false;
      this.$emit('export-workers');
    },
    onExportAll() {
      this.showMainMenu = false;
      this.$emit('export-all');
    },
    triggerImportWorkers() {
      if (!this.$refs.workersImportInput) return;
      this.$refs.workersImportInput.value = '';
      this.$refs.workersImportInput.click();
      this.showMainMenu = false;
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
    onOpenGitHub() {
      window.open('https://github.com/billroy/bullpen', '_blank', 'noopener,noreferrer');
      this.showMainMenu = false;
    },
    onImportWorkspaceSelected(event) {
      const file = event?.target?.files?.[0];
      if (!file) return;
      this.$emit('import-workspace', file);
    },
    onImportWorkersSelected(event) {
      const file = event?.target?.files?.[0];
      if (!file) return;
      this.$emit('import-workers', file);
    },
    onImportAllSelected(event) {
      const file = event?.target?.files?.[0];
      if (!file) return;
      this.$emit('import-all', file);
    },
    submitQuickCreate() {
      const text = this.quickCreateText.trim();
      if (!text) return;
      if (text.startsWith('/')) {
        this.$emit('run-command-bar', text);
        this.quickCreateText = '';
        return;
      }
      const slashIdx = text.indexOf('/');
      const payload = slashIdx >= 0
        ? {
            title: text.slice(0, slashIdx).trim(),
            description: text.slice(slashIdx + 1).trim(),
          }
        : { title: text, description: '' };
      if (!payload.title) return;
      this.$emit('quick-create-task', payload);
    },
  },
  template: `
    <div class="top-toolbar">
      <div class="toolbar-left">
        <div class="toolbar-menu-wrap" @click.stop>
          <button class="btn btn-icon" @click="toggleMainMenu" title="Main menu">&#9776;</button>
          <div v-if="showMainMenu" class="project-menu toolbar-menu">
            <button class="project-menu-item" @click="onToggleLeftPane"><i class="menu-item-icon" data-lucide="panel-left" aria-hidden="true"></i><span class="menu-item-label">Toggle Left Pane</span></button>
            <button class="project-menu-item" @click="onExportWorkspace"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Project</span></button>
            <button class="project-menu-item" @click="onExportWorkers"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Workers</span></button>
            <button class="project-menu-item" @click="onExportAll"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export All</span></button>
            <button class="project-menu-item" @click="triggerImportWorkspace"><i class="menu-item-icon" data-lucide="upload" aria-hidden="true"></i><span class="menu-item-label">Import Project</span></button>
            <button class="project-menu-item" @click="triggerImportWorkers"><i class="menu-item-icon" data-lucide="upload" aria-hidden="true"></i><span class="menu-item-label">Import Workers</span></button>
            <button class="project-menu-item" @click="triggerImportAll"><i class="menu-item-icon" data-lucide="upload" aria-hidden="true"></i><span class="menu-item-label">Import All</span></button>
            <button class="project-menu-item" @click="onOpenGitHub"><i class="menu-item-icon" data-lucide="github" aria-hidden="true"></i><span class="menu-item-label">Bullpen on GitHub</span></button>
          </div>
          <input
            ref="workersImportInput"
            type="file"
            accept=".zip,application/zip"
            class="toolbar-import-input"
            @change="onImportWorkersSelected"
          >
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
        <span class="toolbar-name">Bullpen<span v-if="projectName" :title="projectPath || ''"> / {{ projectName }}</span></span>
      </div>
      <div class="toolbar-center">
        <input
          class="quick-create-input toolbar-quick-create-input"
          v-model="quickCreateText"
          placeholder="Enter ticket title/description"
          @keyup.enter="submitQuickCreate"
        />
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
        <div class="toolbar-menu-wrap event-sounds-menu-wrap" @click.stop>
          <button
            class="btn btn-icon event-sounds-btn"
            :class="{ 'is-disabled': !eventSoundFlags.enabled }"
            @click="toggleEventSoundsMenu"
            title="Event sounds"
          >
            <i data-lucide="bell" aria-hidden="true"></i>
          </button>
          <div v-if="showEventSoundsMenu" class="project-menu toolbar-menu event-sounds-menu">
            <label class="event-sounds-row event-sounds-master">
              <input
                type="checkbox"
                :checked="eventSoundFlags.enabled"
                @change="onToggleEventSoundFlag('enabled')"
              >
              <span class="event-sounds-row-label">All event sounds</span>
            </label>
            <div class="event-sounds-divider"></div>
            <div
              v-for="item in eventSoundLabels"
              :key="item.key"
              class="event-sounds-row"
            >
              <label class="event-sounds-row-main">
                <input
                  type="checkbox"
                  :checked="!!eventSoundFlags[item.key]"
                  :disabled="!eventSoundFlags.enabled"
                  @change="onToggleEventSoundFlag(item.key)"
                >
                <span class="event-sounds-row-label">{{ item.label }}</span>
              </label>
              <button
                class="btn btn-sm event-sounds-preview"
                @click="onPreviewEventSound(item.preview)"
                title="Preview"
              >▶</button>
            </div>
          </div>
        </div>
        <select class="form-select theme-select" :value="activeTheme" @change="$emit('set-theme', $event.target.value)" title="Theme">
          <option v-for="t in themes || []" :key="t.id" :value="t.id">{{ t.label }}</option>
        </select>
        <span class="connection-dot" :class="{ connected }"></span>
      </div>
    </div>
  `
};
