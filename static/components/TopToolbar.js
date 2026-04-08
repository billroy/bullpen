const TopToolbar = {
  props: ['name', 'connected'],
  template: `
    <div class="top-toolbar">
      <div class="toolbar-left">
        <button class="btn btn-icon" @click="$emit('toggle-left-pane')" title="Toggle left pane">&#9776;</button>
        <span class="toolbar-name">{{ name }}</span>
      </div>
      <div class="toolbar-center">
      </div>
      <div class="toolbar-right">
        <button class="btn btn-icon theme-toggle" @click="$emit('toggle-theme')" :title="isDark ? 'Switch to light theme' : 'Switch to dark theme'">
          {{ isDark ? '\u2600' : '\u263E' }}
        </button>
        <span class="connection-dot" :class="{ connected }"></span>
      </div>
    </div>
  `,
  computed: {
    isDark() {
      return document.documentElement.getAttribute('data-theme') !== 'light';
    }
  }
};
