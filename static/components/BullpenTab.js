const BullpenTab = {
  props: ['layout', 'config'],
  template: `
    <div class="bullpen-grid-container">
      <div class="bullpen-header">
        <span>Bullpen Grid</span>
      </div>
      <div class="bullpen-grid" :style="gridStyle">
        <div v-for="i in totalSlots" :key="i" class="grid-slot empty-slot">
          <span class="slot-placeholder">+</span>
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
        gridTemplateRows: `repeat(${this.rows}, 1fr)`,
      };
    }
  }
};
