# Accessibility Review
*Bullpen — 2026-04-27*

## Executive Summary

Bullpen's frontend is a Vue 3 single-page application assembled from CDN-delivered libraries with no build step. The interface is feature-rich — Kanban board, worker grid, modals, command palette, drag-and-drop, toast notifications — but accessibility has not been a design priority. No ARIA landmarks, roles, or live regions were found in the component code. Color-only status indicators, unconfirmed focus management, and absent screen-reader testing collectively place the product well below WCAG 2.1 Level A compliance in several areas. For a team-management tool expected to run in professional environments, this is a meaningful gap that will surface in enterprise procurement reviews and may create legal exposure in jurisdictions that mandate digital accessibility.

---

## WCAG 2.1 Compliance Assessment

| Level | Assessment |
|-------|-----------|
| A     | **Partial / Failing** — multiple Level A criteria unmet (role, name, value; keyboard access; status messages) |
| AA    | **Failing** — color contrast unverified, focus visible unconfirmed, no non-color status alternatives |
| AAA   | Not assessed; prerequisite AA not met |

---

## Findings

### HIGH — No ARIA Landmark Regions

**Criterion:** WCAG 2.1 §1.3.6 (AAA) / Best Practice for §1.3.1 (A)

The application shell (`index.html`) and Vue component tree contain no `<main>`, `<nav>`, `<header>`, `<aside>`, or equivalent ARIA `role=` landmark attributes. Screen reader users cannot jump to major sections of the page. Every top-level tab (Kanban, Workers, Files, Commits, Stats, Chat) and the left pane are unlandmarked regions. A user relying on JAWS, NVDA, or VoiceOver has no structural map of the UI.

**Impact:** Screen reader users cannot navigate the interface efficiently; the product is effectively unusable for this population.

**Remediation:** Add semantic HTML5 landmarks (`<main>`, `<nav>`, `<aside>`) and `aria-label` attributes to distinguish multiple instances of the same landmark type. Effort: 1–2 engineer-days for the shell; additional work per component.

---

### HIGH — Color-Only Worker Status Indicators

**Criterion:** WCAG 2.1 §1.4.1 Use of Color (Level A)

Worker status pills (idle, working, retrying, blocked) are described in the codebase as color-differentiated indicators. No confirming evidence of a secondary indicator (icon, pattern, text label visible at all times) was found. Users with color vision deficiency — roughly 8% of males — cannot reliably distinguish worker states.

**Impact:** A core workflow (monitoring which workers are active, blocked, or retrying) is inaccessible to a significant user segment.

**Remediation:** Supplement color with a visible text label or distinct icon per status. Effort: less than 1 engineer-day per component if labels already exist in the data model.

---

### HIGH — Drag-and-Drop Without Keyboard Alternative

**Criterion:** WCAG 2.1 §2.1.1 Keyboard (Level A)

Both the Kanban board and worker grid expose drag-and-drop as the primary interaction for reordering and moving items. No keyboard-accessible alternative (e.g., arrow-key reordering, context menu move, or accessible drag pattern using `aria-grabbed` / `aria-dropeffect`) was found. Native HTML5 drag events are not keyboard operable.

**Impact:** Keyboard-only users and users of switch-access devices cannot perform fundamental task management operations.

**Remediation:** Implement keyboard-operable reordering (e.g., grab with Space, move with arrow keys, drop with Space/Enter) on both boards. This is a moderate engineering effort — estimate 3–5 engineer-days per board if drag library does not natively support it.

---

### HIGH — No Focus Management in Modals and Command Palette

**Criterion:** WCAG 2.1 §2.1.2 No Keyboard Trap (A) / §2.4.3 Focus Order (A)

Focus management within modal dialogs (TaskCreateModal, WorkerConfigModal, and others) and the command palette (Cmd+K) was not confirmed. Standard requirements for modal focus management include: focus moves into the modal on open, focus is trapped within the modal while open, and focus returns to the trigger element on close. Without this, keyboard users lose their place in the page and may be trapped outside the modal or lose access to the modal content entirely.

**Impact:** Keyboard users may be unable to complete task creation, worker configuration, and other modal-driven workflows without a mouse.

**Remediation:** Audit each modal and the command palette for focus trap and return behavior. Vue 3's `onMounted` lifecycle hook is the standard location for this. Libraries such as `focus-trap` can be added without a build step via CDN. Effort: 1–3 engineer-days depending on modal count.

---

### MEDIUM — Unverified Color Contrast Ratios

**Criterion:** WCAG 2.1 §1.4.3 Contrast Minimum (Level AA)

Bullpen ships 25 theme variants including both light and dark modes. No automated contrast testing is present in the test suite, and no contrast audit was performed as part of development. Theme colors are configurable, meaning contrast ratios can vary widely. Low-contrast text on colored status pills, sidebar items, or toast notifications is a likely failure point.

**Impact:** Users with low vision may be unable to read interface text under some or all themes.

**Remediation:** Add a contrast audit step (e.g., `axe-core` or `pa11y`) to the test suite for the default themes. Enforce minimum 4.5:1 for normal text, 3:1 for large text. Flag user-selectable themes that fail. Effort: 1–2 engineer-days to automate; additional time to fix failing themes.

---

### MEDIUM — Form Labels Not Confirmed in Modal Dialogs

**Criterion:** WCAG 2.1 §1.3.1 Info and Relationships (A) / §3.3.2 Labels or Instructions (A)

Task creation, worker configuration, and other modal forms contain input fields whose label associations (explicit `<label for="">` or `aria-label` / `aria-labelledby`) were not confirmed in available source. Unlabeled inputs are a common failure in Vue component libraries that use placeholder text as a visual substitute for labels.

**Impact:** Screen reader users hear only the input type and no field purpose; form completion is error-prone or impossible.

**Remediation:** Audit all form fields in modal components. Add explicit `<label>` elements or `aria-label` attributes. Placeholders may remain but must not be the sole label. Effort: 1 engineer-day.

---

### MEDIUM — No ARIA Live Regions for Toast Notifications

**Criterion:** WCAG 2.1 §4.1.3 Status Messages (Level AA)

Toast notifications (ToastContainer.js) communicate task completion, errors, and warnings visually. Without an `aria-live="polite"` or `aria-live="assertive"` region, these messages are silent to screen readers. Errors surfaced only via toast are invisible to this user population.

**Impact:** Screen reader users miss ephemeral status updates, including error conditions that require action.

**Remediation:** Wrap the toast container's output in `<div aria-live="polite" aria-atomic="true">`. For error toasts, consider `aria-live="assertive"`. Effort: less than half a day.

---

### LOW — No `lang` Attribute Confirmed on `<html>`

**Criterion:** WCAG 2.1 §3.1.1 Language of Page (Level A)

The `<html>` element's `lang` attribute was not confirmed in available source snippets. Without it, screen readers cannot select the correct language profile for speech synthesis.

**Impact:** Mispronunciation and incorrect character rendering for screen reader users, particularly for non-English content.

**Remediation:** Add `lang="en"` (or appropriate BCP 47 code) to the `<html>` tag in `index.html`. Effort: minutes.

---

### LOW — No Skip Navigation Link

**Criterion:** WCAG 2.1 §2.4.1 Bypass Blocks (Level A)

No skip-to-main-content link was found. Keyboard users must tab through the entire navigation and toolbar on every page load or focus event before reaching the primary content area.

**Impact:** Inefficient but not blocking; compounded by absence of landmarks.

**Remediation:** Add a visually hidden skip link as the first focusable element in the DOM, made visible on focus. Effort: less than 1 hour.

---

### LOW — No Accessibility Testing in CI

**Criterion:** Process / Risk Management

The test suite (`pytest`) contains no automated accessibility checks. No reference to `axe-core`, `pa11y`, `lighthouse --accessibility`, or equivalent was found. Issues discovered post-sale will be more expensive to fix.

**Impact:** Regressions will go undetected; accessibility debt will compound.

**Remediation:** Integrate `axe-playwright` or `pa11y-ci` into the test suite. Even a smoke-test pass on the main page catches the most common failures. Effort: 1–2 engineer-days to set up.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 4     |
| MEDIUM   | 3     |
| LOW      | 3     |

---

## Recommendations

1. **Immediate (pre-sale disclosure):** Disclose known accessibility gaps to the buyer. Several HIGH findings constitute Level A WCAG failures, which carry legal risk in the EU (EN 301 549), US federal procurement (Section 508), and increasingly in commercial SaaS contracts that include accessibility warranties.

2. **Short-term (1–2 sprints):** Address all HIGH findings. Add `lang`, skip link, and live regions (LOW/MEDIUM) in the same pass — they are trivially inexpensive.

3. **Medium-term (1 quarter):** Conduct a full manual audit with a screen reader (NVDA + Firefox, VoiceOver + Safari). Automated tools catch approximately 30–40% of failures; manual testing is required for drag-and-drop, focus management, and dynamic content.

4. **Process:** Add `axe-core` or `pa11y` to the test pipeline so future development does not regress current state. Assign an accessibility owner for each sprint.

5. **Theming:** When exposing theme customization to users, validate contrast ratios at theme-save time and reject or warn on failing combinations.
