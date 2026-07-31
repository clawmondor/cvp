# Jump to Last Edited Item — Design

**Date:** 2026-07-31
**Status:** Approved (brainstorm)

## Problem

The Items table for a matter can be long. A specialist working down the list
opens an item's inline editor, saves, scrolls away, and then loses their place.
There is no quick way to return to the item they were most recently working on.

## Goal

Add a minimal element at the top of the Items tab that tracks the **last item
the user opened in edit mode** and lets them scroll straight back to it.

## Scope

- Single "last edited" item per matter (not a history list).
- Trigger is **opening** the inline editor, not saving.
- Persists across page reloads and revisits, scoped per matter.
- Client-side only. No new routes, no schema changes, no template data beyond
  the matter id already present in the DOM.

Explicitly out of scope: a recent-items history list, server-side tracking,
cross-user/shared "last edited", live-syncing the stored description on every
save.

## Behavior

### Capture

Item edit mode is entered via the existing delegated row-click handler
(`src/cvp/static/app.js` ~line 354): clicking a row (outside interactive
controls) fires `htmx.ajax('GET', row.dataset.itemEditUrl, …)`.

At that point we also record the item:

- Key: `claimos:lastEdited:<matterId>` in `localStorage`.
- Value: JSON `{ "id": "<itemId>", "description": "<text>" }`.
- The item id is parsed from `row.id` (`item-row-<id>`). The description is
  read from the row's description cell.

Storing the description alongside the id lets the link render immediately on
page load with **no server round-trip**, and keeps working even when the item
is filtered or sorted out of the current table view.

The stored value is overwritten each time an editor is opened, so it always
reflects the most recent edit target (and its current description).

### The link

A single-line element rendered at the top of the Items tab, just above the
table and adjacent to the existing "New items" banner. Hidden by default.

Rendered example:

```
→ Last edited: 65″ Samsung QLED TV · jump to it
```

- Built and shown entirely by `app.js` from `localStorage` on page load /
  Items-tab render. No Jinja data required beyond the matter id, which is
  already exposed on `#items-new-banner[data-matter-id]`.
- Hidden (`display:none` / `hidden` class) whenever there is no stored entry
  for the current matter.
- The description text is inserted as **text content** (never innerHTML) to
  avoid injecting item-supplied markup.
- "jump to it" is a CSP-safe control (delegated listener in `app.js`, no inline
  handler).

### Jump

Clicking "jump to it":

1. Find `#item-row-<storedId>` in the DOM.
2. If found: `scrollIntoView({ behavior: 'smooth', block: 'center' })` and
   briefly flash a highlight ring on the row (add a CSS class, remove it after
   ~1.5s) so the eye catches the target. This mirrors the existing new-items
   banner scroll behavior.
3. If **not found** (item filtered out, on another sort page, or deleted):
   show a brief inline note next to the link — *"not in the current view"* —
   and take no other action. No hard error, no navigation.

## Implementation notes

- All logic lives in `src/cvp/static/app.js` as delegated listeners, matching
  the established CSP-safe pattern (no `onclick`/inline handlers).
- One small markup addition to `src/cvp/templates/_tab_items.html`: the
  hidden last-edited link container, placed near the `items-new-banner`.
- Highlight-flash uses a Tailwind-utility ring class toggled via JS, or a small
  keyframe added to the existing stylesheet — whichever matches current
  conventions; no new build step.
- `localStorage` access wrapped in try/catch (private-mode / quota safety),
  consistent with the existing `sessionStorage` usage around the banner
  dismissal logic (`app.js` ~line 545/586).

## Testing

- Manual/browser: open an item editor → link appears with correct description
  → reload page → link persists → jump scrolls + highlights the row.
- Filtered-out case: filter the table so the last-edited item is hidden →
  jump shows "not in the current view".
- Deleted case: delete the last-edited item → jump shows the same note.
- Different matter: switching matters shows that matter's own last-edited entry
  (or nothing), not another matter's.

Given this is client-side JS with no Python surface, verification is via the
browser-verify recipe rather than pytest.
