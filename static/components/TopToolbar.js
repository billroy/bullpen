const TopToolbar = {
  props: ['workspace', 'name', 'connected'],
  template: `
    <div class="top-toolbar">
      <div class="toolbar-left">
        <button class="btn btn-icon" @click="$emit('toggle-left-pane')" title="Toggle left pane">☰</button>
        <span class="toolbar-name">{{ name }}</span>
      </div>
      <div class="toolbar-center">
        <span class="toolbar-workspace" :title="workspace">{{ workspaceShort }}</span>
      </div>
      <div class="toolbar-right">
        <span class="connection-dot" :class="{ connected }"></span>
      </div>
    </div>
  `,
  computed: {
    workspaceShort() {
      if (!this.workspace) return '';
      const parts = this.workspace.split('/');
      return parts.slice(-2).join('/');
    }
  }
};
