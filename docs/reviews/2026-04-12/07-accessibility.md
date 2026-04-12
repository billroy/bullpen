# Accessibility Review — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Review of the frontend UI for WCAG 2.1 compliance, keyboard navigation, screen reader support, color contrast, ARIA usage, and accessible interaction patterns. Based on source code analysis of `static/index.html`, `static/app.js`, `static/style.css`, and Vue component files under `static/components/`.

---

## Limitations

This review is based on static source analysis. No automated accessibility scanner (axe, WAVE) or screen reader (NVDA, VoiceOver) was run against a live instance. Findings are based on code patterns and component structure. A runtime audit is recommended for definitive compliance assessment.

---

## Findings

### HIGH — Drag-and-drop kanban is keyboard-inaccessible

**Files:** `static/components/KanbanTab.js`, `static/components/TaskCard.js`, `static/components/WorkerCard.js`

The primary task management workflow relies on drag-and-drop to move tickets between kanban columns and onto workers. There is a `test_frontend_dragdrop_ipad_guard.py` test which confirms drag-and-drop is the primary interaction model. There is no evidence of a keyboard-accessible alternative (e.g., keyboard shortcuts to assign a task, context menu, or accessible drag-and-drop using `aria-grabbed`/`aria-dropeffect` or the Keyboard API pattern).

WCAG 2.1 Success Criterion 2.1.1 (Keyboard) requires that all functionality is operable via keyboard. Drag-and-drop without a keyboard alternative is a Level A failure.

**Recommendation:** Add keyboard shortcuts (or a modal action) to assign tasks to workers and move tickets between columns. Document these in the UI.

---

### HIGH — No ARIA roles or labels on interactive grid and panel elements

**Files:** `static/components/LeftPane.js`, `static/components/WorkerCard.js`, `static/components/TaskDetailPanel.js`

The worker grid, task cards, and left-pane navigation are implemented as `<div>` elements with click handlers. Without `role`, `aria-label`, or `aria-describedby` attributes, screen readers will not convey the purpose or state of these elements. A screen reader user navigating Bullpen will encounter a sequence of unlabeled interactive regions.

**Recommendation:** Add appropriate ARIA roles (`role="grid"`, `role="gridcell"`, `role="button"`, `role="dialog"`) and labels to all interactive containers.

---

### HIGH — No skip navigation link

**File:** `static/index.html`

There is no "skip to main content" link at the top of the page. For keyboard and screen reader users, this means every page load requires tabbing through all navigation elements before reaching main content. This is a WCAG 2.4.1 (Bypass Blocks) Level A failure.

**Recommendation:** Add `<a href="#main-content" class="skip-link">Skip to main content</a>` as the first element in `<body>`, and add `id="main-content"` to the primary content region.

---

### MEDIUM — Color themes may not meet contrast requirements

**File:** `static/style.css`, `server/validation.py:20–25`

Bullpen supports 22 color themes (dark, light, dracula, nord, gruvbox, etc.). The review cannot confirm that all themes meet WCAG 2.1 SC 1.4.3 (Contrast Minimum, Level AA: 4.5:1 for text). Some dark themes (e.g., gruvbox, monokai) use low-contrast color combinations that are aesthetically intentional but may fail contrast requirements for users with low vision.

**Recommendation:** Run automated contrast checks on all 22 themes against the text/background color pairs defined in `style.css`. Ensure at minimum the default "dark" and "light" themes are AA compliant.

---

### MEDIUM — No `aria-live` regions for real-time streaming output

**Files:** `static/components/WorkerFocusView.js`, `static/components/LiveAgentChatTab.js`

Worker output streaming and live agent chat responses are appended to the DOM in real time via SocketIO events. Without `aria-live="polite"` (or `assertive`) regions, screen readers will not announce new content as it arrives. A blind user monitoring an agent run will receive no feedback.

**Recommendation:** Wrap streaming output containers with `<div aria-live="polite" aria-atomic="false">` so screen readers announce updates incrementally.

---

### MEDIUM — Modal dialogs lack focus management and `aria-modal`

**Files:** `static/components/TaskCreateModal.js`, `static/components/WorkerConfigModal.js`, `static/components/ColumnManagerModal.js`

Modal dialogs (task create, worker config, column manager) open without:
- Moving keyboard focus to the first focusable element inside the modal.
- Trapping keyboard focus within the modal while it is open.
- Using `role="dialog"` and `aria-modal="true"`.
- Returning focus to the triggering element when closed.

The `test_frontend_modal_escape.py` and `test_frontend_modal_cmd_enter.py` tests verify keyboard shortcut handling, but do not test ARIA patterns or focus management.

**Recommendation:** Implement the ARIA dialog pattern for all modals: `role="dialog"`, `aria-labelledby` pointing to the modal title, focus trap on open, restore focus on close.

---

### LOW — Form inputs in modals may lack associated `<label>` elements

**Files:** `static/components/WorkerConfigModal.js`, `static/components/TaskCreateModal.js`

Form inputs inside configuration modals may not have explicitly associated `<label>` elements with `for`/`id` pairing or `aria-label`. Inputs identified only by placeholder text are not accessible to screen readers (placeholder text is not reliably announced as a label).

**Recommendation:** Ensure every form input has an associated `<label>` element or `aria-label` attribute.

---

### LOW — Toast notifications may not be announced to screen readers

**File:** `static/components/ToastContainer.js`

Toast notifications (used for error and success feedback) are transient UI elements. Without `role="alert"` or an `aria-live` region, screen readers will not announce toasts. Users relying on screen readers will miss error messages and confirmations.

**Recommendation:** Add `role="alert"` to the toast container or wrap it in an `aria-live="assertive"` region.

---

### LOW — No dark/light mode auto-detection

**File:** `server/validation.py:20–25`, `static/app.js`

Bullpen has a theme system with 22 themes including light and dark variants. However, there is no automatic selection based on the user's OS preference (`prefers-color-scheme` media query). Users with system-level dark mode or high-contrast preferences must manually select a theme.

**Recommendation:** On first load, detect `window.matchMedia('(prefers-color-scheme: dark)')` and default to "dark" or "light" accordingly.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| A1 | HIGH | Drag-and-drop has no keyboard alternative (WCAG 2.1.1) |
| A2 | HIGH | No ARIA roles/labels on interactive elements |
| A3 | HIGH | No skip navigation link (WCAG 2.4.1) |
| A4 | MEDIUM | Color themes not verified for contrast compliance (WCAG 1.4.3) |
| A5 | MEDIUM | No `aria-live` regions for streaming output |
| A6 | MEDIUM | Modal dialogs lack focus management and `aria-modal` |
| A7 | LOW | Form inputs may lack associated labels |
| A8 | LOW | Toast notifications not announced to screen readers |
| A9 | LOW | No `prefers-color-scheme` auto-detection |
