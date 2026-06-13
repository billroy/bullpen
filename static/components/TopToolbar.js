const TopToolbar = {
  props: ['projectName', 'projectPath', 'deployLabel', 'connected', 'themes', 'activeTheme', 'ambientPresets', 'ambientPreset', 'ambientVolume', 'providerColors', 'defaultProviderColors', 'workerAutomationPaused', 'workerMinimapCollapsed', 'quickCreateClearToken', 'paletteCommands'],
  emits: [
    'toggle-left-pane',
    'export-workers',
    'set-theme',
    'set-ambient-preset',
    'set-ambient-volume',
    'set-provider-color',
    'reset-provider-colors',
    'pause-automation',
    'resume-automation',
    'stop-the-line',
    'pause-all-automation',
    'resume-all-automation',
    'stop-all-lines',
    'set-worker-minimap-collapsed',
    'export-workspace',
    'export-all',
    'import-workers',
    'import-workspace',
    'import-all',
    'quick-create-task',
    'run-palette-command',
    'run-palette-input',
  ],
  data() {
    return {
      showMainMenu: false,
      showSafetyMenu: false,
      quickCreateText: '',
      showPalette: false,
      paletteOverlayOpen: false,
      selectedPaletteIndex: 0,
      showAudioMenu: false,
      showProviderColorsMenu: false,
      eventSoundFlags: (window.EventSounds && window.EventSounds.getFlags())
        || { ...(window.EVENT_SOUND_FLAGS_DEFAULTS || {}) },
      eventSoundLabels: window.EVENT_SOUND_LABELS || [],
      notificationFlags: (window.NotificationWorkers && window.NotificationWorkers.getFlags())
        || { ...(window.NOTIFICATION_WORKER_FLAGS_DEFAULTS || {}) },
    };
  },
  computed: {
    paletteMode() {
      const text = this.quickCreateText.trimStart();
      if (text.startsWith('>')) return 'command';
      if (text.startsWith('?')) return 'help';
      return 'ticket';
    },
    paletteQuery() {
      const text = this.quickCreateText.trimStart();
      if (text.startsWith('>') || text.startsWith('?')) return text.slice(1).trim();
      return text.trim();
    },
    visiblePaletteResults() {
      if (this.paletteMode === 'command' || this.paletteMode === 'help') {
        const parsed = window.BullpenCommands?.parseCommandInput(this.quickCreateText) || { args: '' };
        const limit = this.paletteQuery ? 10 : Infinity;
        let matches = window.BullpenCommands
          ? window.BullpenCommands.filterCommands(this.paletteCommands || [], this.paletteQuery, limit)
          : [];
        if (window.BullpenCommands && parsed.command && parsed.args) {
          const direct = window.BullpenCommands.findCommand(this.paletteCommands || [], `>${parsed.command}`);
          if (direct?.command && !matches.some(command => command.id === direct.command.id)) {
            matches = [direct.command, ...matches].slice(0, limit);
          }
        }
        return matches.map(command => ({
          kind: 'command',
          command,
          title: command.title,
          subtitle: command.subtitle,
          group: command.group,
          shortcut: command.shortcut,
          disabledReason: command.disabledReason,
          args: parsed.args,
        }));
      }

      const text = this.quickCreateText.trim();
      if (!text) {
        const createCommand = (this.paletteCommands || []).find(command => command.id === 'ticket.create');
        return [
          {
            kind: 'mode',
            title: 'Show commands',
            subtitle: 'Type > to run Bullpen commands',
            shortcut: '>',
          },
          {
            kind: 'description-help',
            title: 'How to add a description',
            subtitle: 'Use Title / description',
          },
          {
            kind: 'command',
            command: createCommand,
            title: 'Create ticket',
            subtitle: 'Open the ticket composer',
            shortcut: 'Enter',
            disabledReason: createCommand?.disabledReason || '',
          },
        ].filter(result => result.kind !== 'command' || result.command);
      }

      const payload = this.splitQuickCreateText(text);
      const title = payload.description
        ? `Create ticket: "${payload.title}" with description`
        : `Create ticket: "${payload.title}"`;
      return [
        {
          kind: 'create',
          title,
          subtitle: payload.description || 'Plain text creates a ticket',
          shortcut: 'Enter',
          payload,
          disabledReason: payload.title ? '' : 'Ticket title cannot be empty',
        },
        {
          kind: 'mode',
          title: 'Show commands',
          subtitle: 'Start with > to search commands',
          shortcut: '>',
        },
      ];
    },
    ambientPresetLabel() {
      if (!this.ambientPreset) return 'Off';
      const preset = (this.ambientPresets || []).find(item => item.key === this.ambientPreset);
      return preset ? preset.label : this.ambientPreset;
    },
    audioButtonTitle() {
      const eventState = this.eventSoundFlags.enabled ? 'event sounds on' : 'event sounds off';
      const notificationState = this.notificationFlags.enabled ? 'notifications on' : 'notifications off';
      return `Audio: ${this.ambientPresetLabel}, ${this.ambientVolume}%, ${eventState}, ${notificationState}`;
    },
  },
  watch: {
    quickCreateClearToken() {
      this.quickCreateText = '';
    },
    quickCreateText() {
      this.selectedPaletteIndex = 0;
      if (this.paletteOverlayOpen) this.showPalette = true;
    },
    selectedPaletteIndex() {
      this.$nextTick(() => this.scrollSelectedPaletteResultIntoView());
    },
    showMainMenu(next) {
      if (next) this.$nextTick(() => renderLucideIcons(this.$el));
    },
    showSafetyMenu(next) {
      if (next) this.$nextTick(() => renderLucideIcons(this.$el));
    },
    showAudioMenu(next) {
      if (next) this.$nextTick(() => renderLucideIcons(this.$el));
    },
    showProviderColorsMenu(next) {
      if (next) this.$nextTick(() => renderLucideIcons(this.$el));
    },
  },
  mounted() {
    document.addEventListener('click', this.onGlobalClick);
    window.addEventListener('keydown', this.onGlobalKeydown);
    window.addEventListener('bullpen:command-palette:open', this.openPaletteOverlay);
    window.addEventListener('bullpen:menu:close-main', this.onExternalCloseMainMenu);
    renderLucideIcons(this.$el);
  },
  updated() {
    this.$nextTick(() => renderLucideIcons(this.$el));
  },
  beforeUnmount() {
    document.removeEventListener('click', this.onGlobalClick);
    window.removeEventListener('keydown', this.onGlobalKeydown);
    window.removeEventListener('bullpen:command-palette:open', this.openPaletteOverlay);
    window.removeEventListener('bullpen:menu:close-main', this.onExternalCloseMainMenu);
  },
  methods: {
    splitQuickCreateText(text) {
      if (window.BullpenCommands?.splitQuickCreateText) {
        return window.BullpenCommands.splitQuickCreateText(text);
      }
      const raw = String(text || '').trim();
      const slashIdx = raw.indexOf('/');
      return slashIdx >= 0
        ? { title: raw.slice(0, slashIdx).trim(), description: raw.slice(slashIdx + 1).trim() }
        : { title: raw, description: '' };
    },
    toggleMainMenu() {
      this.showMainMenu = !this.showMainMenu;
      if (this.showMainMenu) {
        this.showSafetyMenu = false;
        this.showAudioMenu = false;
        window.dispatchEvent(new Event('bullpen:menu:close-projects'));
      }
    },
    toggleSafetyMenu() {
      this.showSafetyMenu = !this.showSafetyMenu;
      if (this.showSafetyMenu) {
        this.showMainMenu = false;
        this.showAudioMenu = false;
        this.showProviderColorsMenu = false;
        window.dispatchEvent(new Event('bullpen:menu:close-projects'));
      }
    },
    onGlobalClick() {
      this.showMainMenu = false;
      this.showSafetyMenu = false;
      this.showAudioMenu = false;
      this.showProviderColorsMenu = false;
      if (!this.paletteOverlayOpen) this.showPalette = false;
    },
    toggleProviderColorsMenu() {
      this.showProviderColorsMenu = !this.showProviderColorsMenu;
      if (this.showProviderColorsMenu) {
        this.showMainMenu = false;
        this.showSafetyMenu = false;
        this.showAudioMenu = false;
      }
    },
    providerColorValue(agent) {
      return (this.providerColors && this.providerColors[agent])
        || (this.defaultProviderColors && this.defaultProviderColors[agent])
        || '#6B7280';
    },
    onProviderColorInput(agent, event) {
      const value = event?.target?.value;
      if (!value) return;
      this.$emit('set-provider-color', agent, value);
    },
    onThemeSelect(event) {
      const value = event?.target?.value;
      if (!value) return;
      this.$emit('set-theme', value, { focusWorkerGrid: true });
    },
    onResetProviderColors() {
      this.$emit('reset-provider-colors');
    },
    onPauseCurrentAutomation() {
      this.showSafetyMenu = false;
      this.$emit('pause-automation');
    },
    onResumeCurrentAutomation() {
      this.showSafetyMenu = false;
      this.$emit('resume-automation');
    },
    onPauseAllAutomation() {
      const ok = window.confirm('Pause automation in all workspaces?');
      if (!ok) return;
      this.showSafetyMenu = false;
      this.$emit('pause-all-automation');
    },
    onResumeAllAutomation() {
      const ok = window.confirm('Resume automation in all workspaces? This clears workspace pauses everywhere.');
      if (!ok) return;
      this.showSafetyMenu = false;
      this.$emit('resume-all-automation');
    },
    onToggleWorkerMinimap() {
      this.showMainMenu = false;
      this.$emit('set-worker-minimap-collapsed', !this.workerMinimapCollapsed);
    },
    onStopTheLine() {
      const ok = window.confirm(
        'Stop active AI/Shell runs in this workspace and pause automation? Services will keep running.'
      );
      if (!ok) return;
      this.showSafetyMenu = false;
      this.$emit('stop-the-line');
    },
    onStopAllLines() {
      const ok = window.confirm(
        'Stop active AI/Shell runs in all workspaces and pause automation everywhere? Services will keep running.'
      );
      if (!ok) return;
      this.showSafetyMenu = false;
      this.$emit('stop-all-lines');
    },
    onGlobalKeydown(event) {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return;
      event.preventDefault();
      this.openPaletteOverlay();
    },
    onPaletteFocus() {
      this.showPalette = true;
    },
    openPaletteOverlay() {
      if (!this.quickCreateText.trim()) this.quickCreateText = '>';
      this.paletteOverlayOpen = true;
      this.showPalette = true;
      this.selectedPaletteIndex = 0;
      this.$nextTick(() => {
        const input = this.$refs.paletteOverlayInput || this.$refs.quickCreateInput;
        if (input) input.focus();
      });
    },
    closePaletteOverlay() {
      this.paletteOverlayOpen = false;
      this.showPalette = false;
    },
    toggleAudioMenu() {
      this.showAudioMenu = !this.showAudioMenu;
      if (this.showAudioMenu) {
        this.showMainMenu = false;
        this.showSafetyMenu = false;
        this.showProviderColorsMenu = false;
      }
    },
    onAmbientPresetChange(event) {
      this.$emit('set-ambient-preset', event?.target?.value || '');
    },
    onAmbientVolumeInput(event) {
      this.$emit('set-ambient-volume', Number(event?.target?.value || 0));
    },
    onToggleEventSoundFlag(key) {
      if (!window.EventSounds) return;
      const next = !this.eventSoundFlags[key];
      window.EventSounds.setFlag(key, next);
      this.eventSoundFlags = { ...this.eventSoundFlags, [key]: next };
    },
    onToggleNotificationFlag(key) {
      if (!window.NotificationWorkers) return;
      const next = !this.notificationFlags[key];
      window.NotificationWorkers.setFlag(key, next);
      this.notificationFlags = { ...this.notificationFlags, [key]: next };
    },
    onStopNotificationSpeech() {
      if (window.NotificationWorkers) window.NotificationWorkers.stopSpeech();
    },
    onPreviewEventSound(previewMethod) {
      if (window.ambientAudio && typeof window.ambientAudio[previewMethod] === 'function') {
        window.ambientAudio.unlock();
        window.ambientAudio[previewMethod]();
      }
    },
    onExternalCloseMainMenu() {
      this.showMainMenu = false;
      this.showSafetyMenu = false;
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
    async onLogout() {
      this.showMainMenu = false;
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = '/logout';
      form.style.display = 'none';

      try {
        const resp = await fetch('/login/csrf', { credentials: 'same-origin' });
        if (resp.ok) {
          const data = await resp.json();
          if (data.csrf_token) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'csrf_token';
            input.value = data.csrf_token;
            form.appendChild(input);
          }
        }
      } catch (err) {
        console.error('Failed to prepare logout request', err);
      }

      document.body.appendChild(form);
      form.submit();
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
    onPaletteKeydown(event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        const count = this.visiblePaletteResults.length || 1;
        this.selectedPaletteIndex = (this.selectedPaletteIndex + 1) % count;
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        const count = this.visiblePaletteResults.length || 1;
        this.selectedPaletteIndex = (this.selectedPaletteIndex - 1 + count) % count;
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        this.submitQuickCreate();
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        if (this.paletteOverlayOpen) {
          this.closePaletteOverlay();
          return;
        }
        if (this.paletteMode === 'command' || this.paletteMode === 'help') {
          this.quickCreateText = '';
          return;
        }
        this.showPalette = false;
      }
    },
    scrollSelectedPaletteResultIntoView() {
      const container = this.paletteOverlayOpen
        ? this.$el.querySelector('.command-palette-overlay-results')
        : this.$el.querySelector('.command-palette-menu');
      if (!container) return;
      const selected = container.children[this.selectedPaletteIndex];
      if (selected && typeof selected.scrollIntoView === 'function') {
        selected.scrollIntoView({ block: 'nearest' });
      }
    },
    focusActiveInput() {
      this.$nextTick(() => {
        const input = this.paletteOverlayOpen ? this.$refs.paletteOverlayInput : this.$refs.quickCreateInput;
        if (input) input.focus();
      });
    },
    runPaletteResult(result) {
      if (!result || result.disabledReason) return;
      if (result.kind === 'create') {
        if (!result.payload?.title) return;
        this.$emit('quick-create-task', result.payload);
        this.showPalette = false;
        return;
      }
      if (result.kind === 'mode') {
        this.quickCreateText = '>';
        this.showPalette = true;
        this.focusActiveInput();
        return;
      }
      if (result.kind === 'description-help') {
        this.quickCreateText = 'Ticket title / description';
        this.showPalette = true;
        this.focusActiveInput();
        return;
      }
      if (result.kind === 'command' && result.command) {
        this.$emit('run-palette-command', result.command.id, result.args || '');
        this.quickCreateText = '';
        this.closePaletteOverlay();
      }
    },
    submitQuickCreate() {
      const text = this.quickCreateText.trim();
      if (!text) return;
      if (this.paletteMode === 'command') {
        const result = this.visiblePaletteResults[this.selectedPaletteIndex] || this.visiblePaletteResults[0];
        if (result?.kind === 'command') {
          this.runPaletteResult(result);
          return;
        }
        this.$emit('run-palette-input', text);
        this.quickCreateText = '';
        this.closePaletteOverlay();
        return;
      }
      if (this.paletteMode === 'help') {
        this.quickCreateText = '>';
        this.showPalette = true;
        return;
      }
      const payload = this.splitQuickCreateText(text);
      if (!payload.title) return;
      this.$emit('quick-create-task', payload);
      this.showPalette = false;
    },
  },
  template: `
    <div class="top-toolbar-shell">
      <div class="top-toolbar">
        <div class="toolbar-left">
          <div class="toolbar-menu-wrap" @click.stop>
            <button class="btn btn-icon" @click="toggleMainMenu" title="Main menu">&#9776;</button>
            <div v-if="showMainMenu" class="project-menu toolbar-menu">
              <button class="project-menu-item" @click="onToggleLeftPane"><i class="menu-item-icon" data-lucide="panel-left" aria-hidden="true"></i><span class="menu-item-label">Toggle Left Pane</span></button>
              <button class="project-menu-item" @click="onToggleWorkerMinimap"><i class="menu-item-icon" data-lucide="map" aria-hidden="true"></i><span class="menu-item-label">{{ workerMinimapCollapsed ? 'Show Minimap' : 'Hide Minimap' }}</span></button>
              <button class="project-menu-item" @click="onExportWorkspace"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Project</span></button>
              <button class="project-menu-item" @click="onExportWorkers"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Workers</span></button>
              <button class="project-menu-item" @click="onExportAll"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export All</span></button>
              <button class="project-menu-item" @click="triggerImportWorkspace"><i class="menu-item-icon" data-lucide="upload" aria-hidden="true"></i><span class="menu-item-label">Import Project</span></button>
              <button class="project-menu-item" @click="triggerImportWorkers"><i class="menu-item-icon" data-lucide="upload" aria-hidden="true"></i><span class="menu-item-label">Import Workers</span></button>
              <button class="project-menu-item" @click="triggerImportAll"><i class="menu-item-icon" data-lucide="upload" aria-hidden="true"></i><span class="menu-item-label">Import All</span></button>
              <button class="project-menu-item" @click="onOpenGitHub"><i class="menu-item-icon" data-lucide="git-branch" aria-hidden="true"></i><span class="menu-item-label">Bullpen on GitHub</span></button>
              <button class="project-menu-item" @click="onLogout"><i class="menu-item-icon" data-lucide="log-out" aria-hidden="true"></i><span class="menu-item-label">Logout</span></button>
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
          <span class="toolbar-name">
            Bullpen<span v-if="projectName" :title="projectPath || ''"> / {{ projectName }}</span>
            <span v-if="deployLabel" class="toolbar-deploy-label">{{ deployLabel }}</span>
          </span>
        </div>
        <div class="toolbar-center">
          <div class="command-palette-inline" @click.stop>
            <input
              ref="quickCreateInput"
              class="quick-create-input toolbar-quick-create-input"
              v-model="quickCreateText"
              placeholder="New ticket / description, or > commands"
              @focus="onPaletteFocus"
              @keydown="onPaletteKeydown"
            />
            <div v-if="showPalette && !paletteOverlayOpen" class="command-palette-menu">
              <button
                v-for="(result, index) in visiblePaletteResults"
                :key="result.kind + '-' + (result.command?.id || result.title)"
                class="command-palette-result"
                :class="{ selected: index === selectedPaletteIndex, disabled: result.disabledReason }"
                @mousedown.prevent="runPaletteResult(result)"
              >
                <span class="command-palette-result-main">
                  <span class="command-palette-result-title">{{ result.title }}</span>
                  <span class="command-palette-result-subtitle">{{ result.disabledReason || result.subtitle }}</span>
                </span>
                <span v-if="result.group || result.shortcut" class="command-palette-result-meta">{{ result.group || result.shortcut }}</span>
              </button>
            </div>
          </div>
        </div>
        <div class="toolbar-right">
          <div class="toolbar-worker-controls">
            <span v-if="workerAutomationPaused" class="toolbar-status-pill">AUTOMATION PAUSED</span>
            <div class="toolbar-safety-menu-wrap" @click.stop>
              <button
                class="btn btn-icon toolbar-safety-btn"
                :class="{ active: showSafetyMenu || workerAutomationPaused }"
                @click="toggleSafetyMenu"
                :aria-expanded="showSafetyMenu ? 'true' : 'false'"
                aria-label="Automation safety controls"
                title="Automation safety controls"
              >
                <span class="toolbar-stop-sign-icon" aria-hidden="true"></span>
              </button>
              <div v-if="showSafetyMenu" class="project-menu toolbar-safety-menu">
                <div class="safety-menu-section-label">Current workspace</div>
                <button v-if="workerAutomationPaused" class="project-menu-item" @click="onResumeCurrentAutomation"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Resume current workspace</span></button>
                <button v-else class="project-menu-item" @click="onPauseCurrentAutomation"><i class="menu-item-icon" data-lucide="pause" aria-hidden="true"></i><span class="menu-item-label">Pause current workspace</span></button>
                <button class="project-menu-item project-menu-item-danger" @click="onStopTheLine"><span class="menu-item-icon menu-stop-sign-icon" aria-hidden="true"></span><span class="menu-item-label">Stop current workspace...</span></button>
                <div class="safety-menu-divider"></div>
                <div class="safety-menu-section-label">All workspaces</div>
                <button class="project-menu-item" @click="onPauseAllAutomation"><i class="menu-item-icon" data-lucide="pause" aria-hidden="true"></i><span class="menu-item-label">Pause all workspaces...</span></button>
                <button class="project-menu-item" @click="onResumeAllAutomation"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Resume all workspaces...</span></button>
                <button class="project-menu-item project-menu-item-danger" @click="onStopAllLines"><span class="menu-item-icon menu-stop-sign-icon" aria-hidden="true"></span><span class="menu-item-label">Stop all workspaces...</span></button>
              </div>
            </div>
          </div>
          <div class="toolbar-menu-wrap toolbar-audio-menu-wrap" @click.stop>
            <button
              class="btn btn-icon toolbar-audio-btn"
              :class="{ 'is-disabled': !eventSoundFlags.enabled && !ambientPreset }"
              @click="toggleAudioMenu"
              :title="audioButtonTitle"
              :aria-label="audioButtonTitle"
              :aria-expanded="showAudioMenu ? 'true' : 'false'"
            >
              <i data-lucide="volume-2" aria-hidden="true"></i>
            </button>
            <div v-if="showAudioMenu" class="project-menu toolbar-menu toolbar-audio-panel">
              <div class="toolbar-audio-panel-section">
                <div class="toolbar-audio-panel-title">Ambient</div>
                <label class="toolbar-audio-control">
                  <span class="toolbar-audio-control-label">Sound</span>
                  <select class="form-select toolbar-audio-select" :value="ambientPreset || ''" @change="onAmbientPresetChange" title="Ambient sound">
                    <option value="">Off</option>
                    <option v-for="p in ambientPresets || []" :key="p.key" :value="p.key">{{ p.label }}</option>
                  </select>
                </label>
                <label class="toolbar-audio-control">
                  <span class="toolbar-audio-control-label">Volume</span>
                  <input
                    class="toolbar-audio-volume"
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    :value="ambientVolume"
                    @input="onAmbientVolumeInput"
                    title="Ambient volume"
                  >
                  <span class="toolbar-audio-value">{{ ambientVolume }}%</span>
                </label>
              </div>
              <div class="event-sounds-divider"></div>
              <div class="toolbar-audio-panel-section">
                <div class="toolbar-audio-panel-title">Notification workers</div>
                <label class="event-sounds-row event-sounds-master">
                  <input
                    type="checkbox"
                    :checked="notificationFlags.enabled"
                    @change="onToggleNotificationFlag('enabled')"
                  >
                  <span class="event-sounds-row-label">All notification workers</span>
                </label>
                <label class="event-sounds-row">
                  <span class="event-sounds-row-main">
                    <input type="checkbox" :checked="notificationFlags.toasts" :disabled="!notificationFlags.enabled" @change="onToggleNotificationFlag('toasts')">
                    <span class="event-sounds-row-label">Toasts</span>
                  </span>
                </label>
                <label class="event-sounds-row">
                  <span class="event-sounds-row-main">
                    <input type="checkbox" :checked="notificationFlags.sounds" :disabled="!notificationFlags.enabled" @change="onToggleNotificationFlag('sounds')">
                    <span class="event-sounds-row-label">Sounds</span>
                  </span>
                </label>
                <div class="event-sounds-row">
                  <label class="event-sounds-row-main">
                    <input type="checkbox" :checked="notificationFlags.speech" :disabled="!notificationFlags.enabled" @change="onToggleNotificationFlag('speech')">
                    <span class="event-sounds-row-label">Speech</span>
                  </label>
                  <button class="btn btn-sm event-sounds-preview" @click="onStopNotificationSpeech" title="Stop speech">Stop</button>
                </div>
                <label class="event-sounds-row">
                  <span class="event-sounds-row-main">
                    <input type="checkbox" :checked="notificationFlags.flash" :disabled="!notificationFlags.enabled" @change="onToggleNotificationFlag('flash')">
                    <span class="event-sounds-row-label">Screen flash</span>
                  </span>
                </label>
              </div>
              <div class="event-sounds-divider"></div>
              <div class="toolbar-audio-panel-section">
                <div class="toolbar-audio-panel-title">Event sounds</div>
                <label class="event-sounds-row event-sounds-master">
                  <input
                    type="checkbox"
                    :checked="eventSoundFlags.enabled"
                    @change="onToggleEventSoundFlag('enabled')"
                  >
                  <span class="event-sounds-row-label">All event sounds</span>
                </label>
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
          </div>
          <div class="toolbar-menu-wrap provider-colors-menu-wrap" @click.stop>
            <button
              class="btn btn-icon provider-colors-btn"
              @click="toggleProviderColorsMenu"
              title="Worker colors"
            >
              <i data-lucide="palette" aria-hidden="true"></i>
            </button>
            <div v-if="showProviderColorsMenu" class="project-menu toolbar-menu provider-colors-menu">
              <div class="provider-colors-title">Worker colors</div>
              <div class="provider-colors-row" v-for="agent in ['claude','codex','gemini','opencode','shell','service','marker','notification']" :key="agent">
                <span class="provider-colors-swatch" :style="{ background: providerColorValue(agent) }"></span>
                <label class="provider-colors-label">{{ agent }}</label>
                <input
                  type="color"
                  class="provider-colors-input"
                  :value="providerColorValue(agent)"
                  @input="onProviderColorInput(agent, $event)"
                />
              </div>
              <div class="provider-colors-actions">
                <button class="btn btn-sm" @click="onResetProviderColors">Restore defaults</button>
              </div>
            </div>
          </div>
          <select class="form-select theme-select" :value="activeTheme" @change="onThemeSelect" title="Theme">
            <option v-for="t in themes || []" :key="t.id" :value="t.id">{{ t.label }}</option>
          </select>
          <span class="connection-dot" :class="{ connected }"></span>
        </div>
      </div>
      <div v-if="paletteOverlayOpen" class="command-palette-overlay" @mousedown.self="closePaletteOverlay">
        <div class="command-palette-dialog" @click.stop>
          <input
            ref="paletteOverlayInput"
            class="quick-create-input command-palette-overlay-input"
            v-model="quickCreateText"
            placeholder="New ticket / description, or > commands"
            @keydown="onPaletteKeydown"
          />
          <div class="command-palette-overlay-results">
            <button
              v-for="(result, index) in visiblePaletteResults"
              :key="'overlay-' + result.kind + '-' + (result.command?.id || result.title)"
              class="command-palette-result"
              :class="{ selected: index === selectedPaletteIndex, disabled: result.disabledReason }"
              @mousedown.prevent="runPaletteResult(result)"
            >
              <span class="command-palette-result-main">
                <span class="command-palette-result-title">{{ result.title }}</span>
                <span class="command-palette-result-subtitle">{{ result.disabledReason || result.subtitle }}</span>
              </span>
              <span v-if="result.group || result.shortcut" class="command-palette-result-meta">{{ result.group || result.shortcut }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  `
};
