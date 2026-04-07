const ToastContainer = {
  props: ['toasts'],
  template: `
    <div class="toast-container">
      <div v-for="toast in toasts" :key="toast.id"
           class="toast" :class="'toast-' + toast.type">
        {{ toast.message }}
      </div>
    </div>
  `
};
