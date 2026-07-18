# Formula Help MVP

## Purpose

Bullpen formulas are edited primarily in Value cells, where there is not enough
room to carry reference material. The MVP provides a small, explicit handbook
that can be consulted without abandoning the in-cell edit.

The governing design criterion is functional lightness: keep only the pieces
that make reference help useful, and avoid turning it into an editor subsystem.

## MVP

### Entry point

- Show a small `fx` help button beside the in-cell Value editor.
- Open the same help with `F1` while that editor has focus.
- Never open help automatically or in response to formula text.

The button is available whenever a Value cell is being edited, including before
the value begins with `=`, so it can help someone start a formula.

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

Opening or using the handbook must not commit or cancel the cell edit. The
formula draft, validation state, caret, and selection remain intact while focus
moves between the input and the reference card.

The existing explicit editor actions keep their meaning:

- `Enter` commits the edit.
- `Escape` in the formula input cancels the edit.
- `Escape` in the handbook closes the handbook and resumes the edit.
- Clicking outside both the cell and handbook cancels the edit as it does now.

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

1. A fresh page emits no `formula-help:*` requests.
2. Clicking `fx` or pressing `F1` opens the function list and makes the first
   index request.
3. Opening one function makes one detail request and does not fetch other
   functions' detail.
4. Reopening an already fetched function uses the page-memory cache.
5. Searching finds all 173 public functions by name, category, signature, or
   short summary.
6. Opening and closing help preserves the exact in-cell draft and selection.
7. `Enter`, `Escape`, and outside-click behavior remain predictable as described
   above.
8. The handbook remains usable at narrow viewport widths and does not obscure
   the active input when the viewport provides room beside it.
9. Missing or malformed help data cannot prevent formula editing.

## Deferred work

The following are intentionally outside the MVP:

- help in the worker configuration modal;
- a global header icon, permanent side rail, or Ticket/Formula inspector tabs;
- tutorials, formula-convention articles, error-code articles, and category
  landing pages;
- autocomplete, signature popovers, caret inspection, automatic function
  detection, or suggestions;
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
