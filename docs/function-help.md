# Formula Help MVP

## Purpose

Bullpen formulas are created primarily by selecting an empty grid cell and
typing `=`. The MVP provides a small, explicit handbook that can be consulted
while creating that expression, without first creating a worker or opening its
configuration.

The governing design criterion is functional lightness: keep only the pieces
that make reference help useful, and avoid turning it into an editor subsystem.

## MVP

### Entry point

- In the empty-cell expression editor, show a labeled `fx Help` button beside
  the input.
- Open the same help with `F1` while that input has focus.
- Keep the same controls in the editor for an existing Value cell as a
  secondary workflow.
- Do not open help automatically while the user types.

The button is available throughout Value creation, including before the value
begins with `=`, so it can help someone start a formula. When help is explicitly
opened, seed handbook search from the function fragment immediately before the
caret. For example, `=SUM` followed by `F1` opens the handbook filtered to
`SUM`. This lookup happens only on the explicit action; it is not continuous
completion or an automatic popup.

### Reference card

Open one modeless card near the active cell. The card has two views:

1. A searchable function list.
2. A single function page with a Back action.

The list shows function name, signature, and category. A function page shows:

- name and category;
- signature, with a Copy action;
- concise behavior from the checked-in function reference;
- whether the function accepts ranges;
- examples, with a Copy action.

The card remains open until its Close control or `Escape` is used. It does not
trap focus. Closing it returns focus to the formula input and restores the
input's caret or selection.

### Edit-session behavior

Opening or using the handbook must not create a worker, commit, or cancel the
cell edit. The formula draft, validation state, caret, and selection remain
intact while focus moves between the input and the reference card.

The existing explicit editor actions keep their meaning:

- `Enter` commits the edit.
- `Escape` in the formula input cancels the edit.
- `Escape` in the handbook closes the handbook and resumes the edit.
- Existing outside-click behavior remains unchanged.

### Loading

Normal page loads include the small reference-card component but no function
catalog or handbook content.

The client performs the following work only after an explicit help action:

1. Request `formula-help:index` once to obtain the compact searchable index.
2. Request `formula-help:function` with a name when a function is opened.
3. Cache the index and fetched function pages in memory for the page session.

The index contains only names, categories, signatures, and short summaries.
Detailed prose and examples are not returned in the index. There is no
background prefetch.

The server uses `server/formula_functions.py` for catalog identity and
`docs/function-reference.md` for the longer checked-in descriptions. Tests
ensure that the reference contains every public catalog function.

### Failure behavior

If the index or a function page cannot be loaded, the card shows a compact
retryable error. Formula editing continues to work normally.

### Accessibility

- The help button has an accessible name including the `F1` shortcut.
- The card is a named complementary region rather than a modal dialog.
- Search results and actions are ordinary keyboard-focusable controls.
- Load, copy, and error messages are exposed through a polite live region.

## Acceptance criteria

1. Starting from an empty cell, typing `=SUM` opens the expression-creation
   editor with a visible `fx Help` control.
2. Pressing `F1` in that editor opens the handbook filtered to `SUM`, preserves
   the exact draft and selection, and makes the first index request.
3. Closing help returns focus to the same creation input; pressing `Enter`
   creates the Value worker with the original expression.
4. A fresh page emits no `formula-help:*` requests.
5. Opening one function makes one detail request and does not fetch other
   functions' detail.
6. Reopening an already fetched function uses the page-memory cache.
7. Searching finds all 173 public functions by name, category, signature, or
   short summary.
8. The secondary existing-Value editor provides the same `fx` and `F1`
   reference access.
9. `Enter`, `Escape`, and outside-click behavior remain predictable as described
   above.
10. The handbook remains usable at narrow viewport widths and does not obscure
   the active input when the viewport provides room beside it.
11. Missing or malformed help data cannot prevent expression creation.

The MVP cannot be considered complete unless criteria 1–3 pass through the
empty-cell creation path. Tests that begin with an already-created Value worker
are secondary coverage and cannot substitute for that journey.

## Deferred work

The following are intentionally outside the MVP:

- help in the worker configuration modal;
- a global header icon, permanent side rail, or Ticket/Formula inspector tabs;
- tutorials, formula-convention articles, error-code articles, and category
  landing pages;
- autocomplete, signature popovers, continuous caret inspection, automatic
  popups, or suggestions;
- inserting functions or examples directly into the formula;
- pinning, dragging, resizing, or persisting the reference card;
- persisted search, navigation, or panel state between page loads;
- background prefetching or eager bootstrap data;
- multiple examples, structured argument tables, related-function links, and
  per-function error matrices beyond what the existing reference provides;
- moving all long-form documentation into structured evaluator metadata;
- a dedicated frontend bundle or state-management layer for help.

Deferred features should be added only in response to observed use, and should
preserve the MVP's explicit, in-cell-first interaction.
