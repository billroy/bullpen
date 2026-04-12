const TopToolbar = {
  props: ['projectName', 'connected', 'themes', 'activeTheme', 'ambientPresets', 'ambientPreset', 'ambientVolume'],
  template: `
    <div class="top-toolbar">
      <div class="toolbar-left">
        <button class="btn btn-icon" @click="$emit('toggle-left-pane')" title="Toggle left pane">&#9776;</button>
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
