const TopToolbar = {
  props: ['name', 'connected', 'themes', 'activeTheme'],
  template: `
    <div class="top-toolbar">
      <div class="toolbar-left">
        <button class="btn btn-icon" @click="$emit('toggle-left-pane')" title="Toggle left pane">&#9776;</button>
        <span class="toolbar-name">{{ name }}</span>
      </div>
      <div class="toolbar-center">
      </div>
      <div class="toolbar-right">
        <select class="form-select theme-select" :value="activeTheme" @change="$emit('set-theme', $event.target.value)" title="Theme">
          <option v-for="t in themes || []" :key="t.id" :value="t.id">{{ t.label }}</option>
        </select>
        <span class="connection-dot" :class="{ connected }"></span>
      </div>
    </div>
  `
};
