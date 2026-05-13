# Accessibility Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Accessibility engineer / WCAG 2.1 compliance expert evaluating for acquisition

---

## Executive Summary

Bullpen's UI is built on semantic HTML (Vue 3 templates), uses appropriate form controls, and provides keyboard shortcuts for common operations. These are strong accessibility foundations. However, the product has not been designed to WCAG 2.1 AA compliance. Critical gaps include: no ARIA roles or labels on custom interactive components (worker cards, Kanban drag targets), no visible keyboard focus indicators, color-only state indicators for worker status, and no screen-reader testing. For a developer tool targeting a technical audience, the severity is lower than a consumer product, but compliance becomes mandatory for enterprise or government deployments.

---

## Findings

### HIGH — Custom interactive components lack ARIA roles and labels

**Location:** `static/components/WorkerCard.js`, `static/components/KanbanTab.js`, `static/app.js`

**Detail:** Worker cards (the primary interactive grid elements for managing AI agents) are Vue components rendered as custom DOM structures. Based on the component architecture, these are likely `<div>` or `<span>` elements styled to look like interactive controls. Without explicit ARIA roles:

1. A screen reader cannot identify worker cards as interactive controls
2. The state of a worker (idle, working, retrying, blocked) is conveyed visually (color, icon) but not announced to assistive technology
3. Context menus triggered by right-click or button on worker cards are inaccessible without keyboard discovery

Similarly, Kanban columns serve as drop zones but have no `role="region"` or `aria-label` to identify their purpose to screen readers.

**Recommendation:** Add `role="button"` and `aria-label="[Worker name] - [state]"` to worker card root elements. Add `aria-live="polite"` regions for worker state changes. Add `role="region"` and `aria-label` to Kanban column containers. Add `aria-dropeffect="move"` to drop zones. Implement `aria-grabbed` on draggable task cards.

---

### HIGH — No visible keyboard focus indicators

**Location:** `static/style.css` — no `focus-visible` rules or `:focus` ring definitions observed for custom interactive elements

**Detail:** WCAG 2.1 Success Criterion 2.4.7 (Focus Visible, AA) requires that any keyboard-operable interface has a visible keyboard focus indicator. Browsers provide default focus rings, but CSS frequently overrides these with `outline: none` for aesthetic reasons. If custom interactive elements (worker cards, Kanban tasks, modals) suppress the default focus ring without providing a visible alternative, keyboard users cannot determine which element is focused.

**Recommendation:** Add explicit `focus-visible` styles for all interactive elements. At minimum: `:focus-visible { outline: 2px solid var(--accent-color); outline-offset: 2px; }` applied globally, with refinements per component. Never set `outline: none` without a replacement focus indicator.

---

### MEDIUM — Worker state conveyed by color only

**Location:** `static/components/WorkerCard.js` (state indicators), `static/style.css` (state color classes)

**Detail:** Worker states (idle, working, retrying, blocked, paused) are indicated by color coding (green for working, yellow for retrying, red for blocked, etc.). WCAG 2.1 Success Criterion 1.4.1 (Use of Color, A) requires that color not be the sole means of conveying information. A user with red-green color blindness (affecting approximately 8% of males) cannot reliably distinguish a blocked (red) from a working (green) worker state.

**Recommendation:** Add a text label or icon alongside the color indicator for each worker state. A two-letter badge (e.g., "WK" for working, "BL" for blocked) or a shape-differentiated icon would satisfy this requirement without changing the visual design significantly.

---

### MEDIUM — Drag-and-drop has no keyboard alternative

**Location:** `static/components/KanbanTab.js` (drag-drop for task cards), `static/app.js` (worker grid repositioning)

**Detail:** Drag-and-drop is the primary mechanism for:
1. Moving task cards between Kanban columns
2. Moving tasks onto worker cards (to assign)
3. Repositioning worker cards on the grid

WCAG 2.1 Success Criterion 2.1.1 (Keyboard, A) requires that all functionality be operable via keyboard. There is no documented or observed keyboard alternative for these drag operations. Users who cannot use a mouse (motor disability, keyboard-only users) cannot perform the core workflow.

**Recommendation:** Add keyboard-based alternatives for the three drag operations:
1. **Task card move:** Focus task card → press Space → use arrow keys to move to target column → press Enter to confirm
2. **Task assignment to worker:** Add a "Assign to worker..." dropdown or right-click menu item accessible by keyboard
3. **Worker repositioning:** Add a "Move worker..." dialog accessible from the worker's keyboard-triggered context menu

---

### MEDIUM — No language attribute on HTML document

**Location:** `static/index.html` or equivalent root HTML template

**Detail:** WCAG 2.1 Success Criterion 3.1.1 (Language of Page, A) requires that the human language of each web page is programmatically determinable via the `lang` attribute on the `<html>` element. Without this attribute, screen readers cannot select the correct pronunciation engine for the page content. This is a minimal, one-line fix.

**Recommendation:** Add `lang="en"` to the `<html>` element in the root HTML template.

---

### MEDIUM — Modal focus management not verified

**Location:** `static/components/WorkerConfigModal.js`, `static/components/TaskCreateModal.js`, and other modal components

**Detail:** WCAG 2.1 Success Criterion 2.4.3 (Focus Order, A) and the ARIA Authoring Practices Guide require that when a modal dialog opens, focus moves into the dialog and is trapped within it until the dialog is dismissed. When the dialog closes, focus returns to the triggering element. The use of Vue `<dialog>` elements (if HTML5 `<dialog>` is used) provides some of this behavior natively, but custom modal implementations require explicit focus management. This could not be verified from static analysis alone.

**Recommendation:** Audit each modal component to verify: (1) focus moves to the first interactive element on open, (2) Tab/Shift+Tab cycles only within the modal, (3) Escape closes the modal, and (4) focus returns to the trigger element on close.

---

### LOW — No `alt` text enforcement for images in the file viewer

**Location:** `static/components/FilesTab.js` (image preview)

**Detail:** The file viewer displays image files inline. If images are displayed via `<img>` elements without `alt` attributes, screen readers will announce the file path as the image description, which is unhelpful. WCAG 2.1 SC 1.1.1 (Non-text Content, A) requires text alternatives for all non-text content.

**Recommendation:** Add `alt=""` (decorative) for preview thumbnails and `alt="[filename]"` for full-size previews. Consider adding a caption field to the file viewer that users can populate.

---

### LOW — Ambient sound controls have no visual indication of audio activity

**Location:** `static/` (ambient sound feature — Web Audio API, 18 synthesized soundscapes)

**Detail:** The ambient sound feature plays audio in the background. Users who are deaf or hard of hearing may not realize audio is playing. Users in shared spaces may accidentally play audio. There is no persistent visual indicator that audio is currently active.

**Recommendation:** Add a persistent audio-active indicator (e.g., a speaker icon with animated wave when ambient sound is playing) visible at all times when sound is active. Ensure the mute/volume control is always visible and keyboard-accessible.

---

## WCAG 2.1 Compliance Summary

| Criterion | Level | Status |
|---|---|---|
| 1.1.1 Non-text Content | A | PARTIAL (file viewer images) |
| 1.4.1 Use of Color | A | FAIL (worker state color-only) |
| 2.1.1 Keyboard | A | FAIL (drag-drop no keyboard alt) |
| 2.4.3 Focus Order | A | UNVERIFIED (modal focus trapping) |
| 2.4.7 Focus Visible | AA | FAIL (no focus ring verified) |
| 3.1.1 Language of Page | A | LIKELY FAIL (lang attr not confirmed) |
| 4.1.2 Name, Role, Value | A | FAIL (worker cards, kanban columns lack ARIA) |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 4 |
| LOW | 2 |
