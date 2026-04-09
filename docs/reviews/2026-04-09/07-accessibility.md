# Accessibility Review — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Accessibility engineer / WCAG auditor evaluating as a potential acquirer

---

## Scope

Review of WCAG 2.1 compliance, semantic HTML structure, ARIA usage, keyboard navigation, color contrast, screen reader compatibility, and focus management across all frontend files (`static/login.html`, `static/index.html`, `static/components/*.js`).

---

## Executive Summary

The login page (`login.html`) has a solid accessibility baseline: proper `<label>` elements, a `role="alert"` error region, and a semantic `<button>` for form submission. The main application (Vue 3, loaded from `index.html`) has significant accessibility gaps: interactive elements are primarily `<div>` elements with click handlers rather than semantic `<button>` or `<a>` elements, ARIA labels are absent from action controls, there is no keyboard navigation beyond tab-cycling, and there are no landmark regions. For a developer tool that may be used by developers with visual impairments or who rely on keyboard navigation, these gaps are meaningful. WCAG 2.1 Level A conformance is not currently met in the main application.

---

## Findings

### HIGH — Interactive Divs Without Keyboard Access

**Location:** `static/components/*.js` — worker cards, task cards, toolbar buttons

Throughout the Vue 3 components, click-activated UI elements are rendered as `<div>` elements with `@click` handlers. These elements:
1. Are not focusable via keyboard Tab (no `tabindex="0"`)
2. Do not respond to Enter/Space key activation (standard for button-like elements)
3. Are not announced as interactive by screen readers

Examples of affected patterns:
- Worker card action buttons (start, stop, configure, delete)
- Task card click-to-select interaction
- Toolbar icon buttons (theme toggle, add project)
- Kanban column drag handles

**WCAG criterion:** 2.1.1 Keyboard (Level A), 4.1.2 Name, Role, Value (Level A)

**Recommendation:** Replace `<div @click="...">` with `<button @click="...">` for all action controls. Remove custom `class="btn"` on divs — use `<button class="btn">` instead. This is a mechanical refactor that can be done component by component.

---

### HIGH — No ARIA Labels on Action Controls

**Location:** `static/components/*.js` — all components

Icon-only buttons (which appear to be the dominant pattern based on the CSS and component structure) have no accessible names. A screen reader user hears "button" with no indication of the action.

**WCAG criterion:** 4.1.2 Name, Role, Value (Level A)

**Recommendation:** Add `aria-label="Start worker"`, `aria-label="Configure worker"`, etc. to all icon-only controls. Where a visible text label exists, use `aria-labelledby` to reference it.

---

### MEDIUM — No Landmark Regions in Main Application

**Location:** `static/index.html`, `static/app.js`

The main application renders into a single `<div id="app">` with no semantic landmark elements (`<nav>`, `<main>`, `<aside>`, `<header>`, `<footer>`). Screen reader users rely on landmarks to navigate large pages without reading every element.

**WCAG criterion:** 1.3.1 Info and Relationships (Level A), 2.4.1 Bypass Blocks (Level A)

**Recommendation:**
- Wrap the task list pane in `<aside aria-label="Task list">`
- Wrap the main content area (tabs, worker grid) in `<main>`
- Wrap the top toolbar in `<header>` or `<nav>`

---

### MEDIUM — No Skip Navigation Link

**Location:** `static/index.html`

There is no "skip to main content" link at the top of the page. Keyboard users must Tab through the entire toolbar and navigation on every page load to reach the primary content area.

**WCAG criterion:** 2.4.1 Bypass Blocks (Level A)

**Recommendation:** Add a visually hidden skip link as the first focusable element:
```html
<a href="#main-content" class="skip-link">Skip to main content</a>
```
With CSS to show it only on focus:
```css
.skip-link { position: absolute; left: -9999px; }
.skip-link:focus { left: 0; }
```

---

### MEDIUM — Focus Management in Modals

**Location:** `static/components/TaskCreateModal.js`, `static/components/WorkerConfigModal.js`

When a modal dialog opens, focus should move to the modal (typically its first interactive element or the dialog container with `tabindex="-1"`). When the modal closes, focus should return to the element that triggered it. Without this:
1. Keyboard users lose their place in the page.
2. Screen readers do not announce the modal content.

**WCAG criterion:** 2.4.3 Focus Order (Level A), 4.1.3 Status Messages (Level AA)

**Recommendation:** Add focus trap logic to modals:
```javascript
// On open: move focus to first input in modal
nextTick(() => modalRef.value.querySelector('input, button')?.focus());
// On close: return focus to trigger element
triggerEl.focus();
```

---

### LOW — Color Contrast Not Verified for All States

**Location:** `static/style.css`

The dark theme appears to use a dark background with light text (appropriate contrast). The light theme uses dark text on light background (also appears appropriate). However, secondary text states (disabled controls, placeholder text, muted labels) were not verified with a contrast analyzer. WCAG 2.1 requires 4.5:1 for normal text, 3:1 for large text (Level AA).

**Recommendation:** Run all color combinations through the WCAG contrast checker. Pay particular attention to: disabled button states, placeholder text in inputs, secondary metadata text in task cards.

---

### LOW — No `lang` Attribute on HTML Element

**Location:** `static/login.html` — confirmed has `<html lang="en">`, `static/index.html` — confirmed has `<html lang="en">`

Both HTML files correctly declare `lang="en"`. This finding is NOT an issue.

**Note recorded for completeness.**

---

### POSITIVE FINDINGS (Login Page)

The login page demonstrates strong accessibility practice:
- `<label for="username">` and `<label for="password">` properly associated with inputs
- `<button type="submit">` (not a div) for form submission
- `role="alert"` on the error region (correct ARIA live region for form errors)
- `id="loginError"` allows the error to be referenced programmatically
- HTML `lang="en"` declared

---

## WCAG 2.1 Conformance Summary

| Level | Status |
|-------|--------|
| Level A | Partially met (login page: met; main app: not met) |
| Level AA | Not assessed (Level A gaps block AA assessment) |
| Level AAA | Not assessed |

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| A11Y-01 | Interactive divs without keyboard access | HIGH |
| A11Y-02 | No ARIA labels on action controls | HIGH |
| A11Y-03 | No landmark regions in main application | MEDIUM |
| A11Y-04 | No skip navigation link | MEDIUM |
| A11Y-05 | Focus management missing in modals | MEDIUM |
| A11Y-06 | Color contrast not verified for all states | LOW |
