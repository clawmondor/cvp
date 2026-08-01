# Jump to Last Edited Item — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal, per-matter "Last edited: <item> · jump to it" link at the top of the Items tab that scrolls the user back to the item they most recently opened in edit mode.

**Architecture:** Pure client-side. The existing delegated row-click handler in `app.js` (which opens the inline editor) also writes `{id, description}` to `localStorage` keyed by matter. A small JS module renders a hidden link from that storage on load/tab-render and, on click, smooth-scrolls to the row and flashes a highlight — or shows an inline "not in the current view" note if the row is absent.

**Tech Stack:** Vanilla JS (delegated listeners in `src/cvp/static/app.js`), Jinja2 templates, Tailwind-via-CDN utility classes, `localStorage`. No new routes, no schema changes, no build step.

## Global Constraints

- **CSP: no inline JavaScript.** No `onclick`/`onchange`/etc. in templates. All interactivity is delegated listeners in `src/cvp/static/app.js` (see existing pattern ~lines 225–275, 354–359). — verbatim from CLAUDE.md.
- **Description is inserted as text content, never innerHTML** — item-supplied text must not be able to inject markup.
- **`localStorage`/`sessionStorage` access is wrapped in `try { … } catch (_) {}`** — matches existing pattern at `app.js:545` and `app.js:586` (private mode / quota safety).
- **No new dependencies, no CSS build step.** Highlight uses Tailwind utility classes toggled via `classList`.
- This is client-side only: verification is the **browser-verify recipe** (fresh DB + `AUTO_LOGIN` + `system_admin` + Playwright), not pytest. No Python is touched, so `ruff` is not in scope.

---

### Task 1: Capture and render the "Last edited" link

Add a `data-item-description` hook to each item row, add the hidden link container to the Items tab, and add the JS that (a) records the item on edit-open and (b) renders/refreshes the link from `localStorage`.

**Files:**
- Modify: `src/cvp/templates/_item_row.html:5-7` (the `<tr>` opening tag)
- Modify: `src/cvp/templates/_tab_items.html` (add link container after the `items-new-banner` block, ~line 13)
- Modify: `src/cvp/static/app.js` (add a new IIFE module; hook the existing row-click handler at ~line 354)

**Interfaces:**
- Produces (for Task 2, same module in `app.js`):
  - `LAST_EDITED_KEY(matterId)` → returns `'claimos:lastEdited:' + matterId` (string)
  - `getMatterId()` → reads `#items-new-banner[data-matter-id]`, returns string or `null`
  - `readLastEdited()` → returns `{ id, description }` or `null`
  - `renderLastEditedLink()` → shows/hides and populates `#last-edited-link`
  - DOM contract: container element `id="last-edited-link"` (hidden by default) containing a description text node target `[data-last-edited-desc]` and a jump control `[data-jump-last-edited]`, plus an inline note target `[data-last-edited-note]`.

- [ ] **Step 1: Add the description hook to the item row**

In `src/cvp/templates/_item_row.html`, add `data-item-description` to the `<tr>` opening tag (currently lines 5–7):

```html
<tr id="item-row-{{ item.id }}"
    data-item-edit-url="/api/items/{{ item.id }}/edit"
    data-item-description="{{ item.description or '—' }}"
    class="{% if item.excluded %}opacity-40{% endif %} hover:bg-gray-50 text-sm cursor-pointer">
```

- [ ] **Step 2: Add the hidden link container to the Items tab**

In `src/cvp/templates/_tab_items.html`, immediately **after** the closing `</div>` of the `items-new-banner` block (after line 13) and before the `<!-- Add item form -->` comment, insert:

```html
  <!-- Last-edited jump link: shown/populated by app.js from localStorage -->
  <div id="last-edited-link" class="hidden items-center gap-2 text-sm text-gray-600">
    <span aria-hidden="true">→</span>
    <span>Last edited:</span>
    <span data-last-edited-desc class="font-medium text-gray-900"></span>
    <span aria-hidden="true">·</span>
    <button type="button" data-jump-last-edited
            class="text-indigo-600 hover:text-indigo-500 hover:underline cursor-pointer">jump to it</button>
    <span data-last-edited-note class="hidden text-xs text-gray-400"></span>
  </div>
```

(The container uses `hidden` initially; `renderLastEditedLink()` swaps it to `flex` when there is an entry.)

- [ ] **Step 3: Add the last-edited JS module**

Append a new IIFE to `src/cvp/static/app.js` (near the other item-region modules, e.g. after the new-items banner IIFE that ends at ~line 778):

```javascript
// ---- Last-edited item: capture on edit-open, render a jump link ----
(function () {
  function LAST_EDITED_KEY(matterId) { return 'claimos:lastEdited:' + matterId; }

  function getMatterId() {
    var banner = document.getElementById('items-new-banner');
    return banner ? banner.dataset.matterId : null;
  }

  function readLastEdited() {
    var matterId = getMatterId();
    if (!matterId) return null;
    try {
      var raw = localStorage.getItem(LAST_EDITED_KEY(matterId));
      if (!raw) return null;
      var val = JSON.parse(raw);
      if (val && val.id) return val;
    } catch (_) {}
    return null;
  }

  function writeLastEdited(id, description) {
    var matterId = getMatterId();
    if (!matterId) return;
    try {
      localStorage.setItem(
        LAST_EDITED_KEY(matterId),
        JSON.stringify({ id: id, description: description || '' })
      );
    } catch (_) {}
  }

  function renderLastEditedLink() {
    var container = document.getElementById('last-edited-link');
    if (!container) return;
    var entry = readLastEdited();
    var descEl = container.querySelector('[data-last-edited-desc]');
    var noteEl = container.querySelector('[data-last-edited-note]');
    if (!entry) {
      container.classList.add('hidden');
      container.classList.remove('flex');
      return;
    }
    if (descEl) descEl.textContent = entry.description || '(item)';
    if (noteEl) { noteEl.textContent = ''; noteEl.classList.add('hidden'); }
    container.classList.remove('hidden');
    container.classList.add('flex');
  }

  // Capture: piggyback on the row-click that opens the inline editor.
  document.addEventListener('click', function (e) {
    if (e.target.closest('a, button, input, select, textarea, label, summary')) return;
    var row = e.target.closest('tr[data-item-edit-url]');
    if (!row) return;
    var id = row.id.replace(/^item-row-/, '');
    writeLastEdited(id, row.dataset.itemDescription || '');
    renderLastEditedLink();
  });

  // Render on full load and whenever htmx swaps the items tab back in.
  document.addEventListener('DOMContentLoaded', renderLastEditedLink);
  document.addEventListener('htmx:afterSettle', function () {
    if (document.getElementById('last-edited-link')) renderLastEditedLink();
  });

  // Expose for Task 2's jump handler (same file, later IIFE not needed —
  // jump handler is added inside this IIFE in Task 2).
  window.__lastEdited = { readLastEdited: readLastEdited, renderLastEditedLink: renderLastEditedLink };
})();
```

> Note: The capture listener is a **second** delegated `click` listener — it does not replace the existing editor-opening handler at `app.js:354`. Both run; order does not matter because capture only reads `row.dataset` and writes storage.

- [ ] **Step 4: Browser-verify capture + render + persistence**

Using the browser-verify recipe (fresh DB + `AUTO_LOGIN` + `system_admin`, Playwright), open a matter with several items on the Items tab. Then:

1. Click an item row to open its editor. Expect the `#last-edited-link` to appear reading `→ Last edited: <that item's description> · jump to it`.
2. Click a different item row. Expect the link's description to update to the new item.
3. Reload the page. Expect the link to still show the last item's description (persisted).
4. Open the same matter in a second tab/window — confirm the link renders from storage on load with no server call (Network tab shows no new request for the link).

Expected: all four pass. (No automated JS test harness exists in this repo; this browser check is the test cycle.)

- [ ] **Step 5: Commit**

```bash
git add src/cvp/templates/_item_row.html src/cvp/templates/_tab_items.html src/cvp/static/app.js
git commit -m "feat(items): track last-edited item, render jump link

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Jump-to-row with highlight and not-in-view fallback

Wire the "jump to it" button to scroll to the stored row and flash a highlight, or show an inline note when the row isn't currently rendered.

**Files:**
- Modify: `src/cvp/static/app.js` (add a delegated `click` handler for `[data-jump-last-edited]` inside the Task 1 IIFE, before its closing `})();`)

**Interfaces:**
- Consumes (from Task 1, same IIFE): `readLastEdited()`, and the DOM contract for `#last-edited-link` (`[data-last-edited-note]`).

- [ ] **Step 1: Add the jump + highlight handler**

Inside the Task 1 IIFE, immediately before the `window.__lastEdited = …` line, add:

```javascript
  function flashRow(row) {
    var classes = ['ring-2', 'ring-indigo-400', 'bg-indigo-50'];
    row.classList.add.apply(row.classList, classes);
    setTimeout(function () {
      row.classList.remove.apply(row.classList, classes);
    }, 1500);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-jump-last-edited]');
    if (!btn) return;
    e.preventDefault();
    var container = document.getElementById('last-edited-link');
    var noteEl = container ? container.querySelector('[data-last-edited-note]') : null;
    var entry = readLastEdited();
    if (!entry) return;
    var row = document.getElementById('item-row-' + entry.id);
    if (row) {
      if (noteEl) { noteEl.textContent = ''; noteEl.classList.add('hidden'); }
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      flashRow(row);
    } else if (noteEl) {
      noteEl.textContent = 'not in the current view';
      noteEl.classList.remove('hidden');
    }
  });
```

- [ ] **Step 2: Browser-verify jump, highlight, and fallback**

Using the browser-verify recipe on a matter with enough items to require scrolling:

1. Open an item near the bottom, scroll back to the top, then click **jump to it**. Expect a smooth scroll to that row and a ~1.5s indigo highlight ring on it.
2. With that item recorded, apply a table filter (or sort) that removes it from the visible rows, then click **jump to it**. Expect the inline note `not in the current view` to appear next to the link and no scroll/error.
3. Clear the filter, delete the last-edited item, then click **jump to it**. Expect the same `not in the current view` note (row no longer in DOM), no console error.

Expected: all three pass.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/static/app.js
git commit -m "feat(items): jump-to-last-edited scroll, highlight, not-in-view note

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Capture on edit-open, per-matter localStorage `{id, description}` → Task 1 Steps 1–3. ✓
- Minimal single-line link, hidden when empty, text-content description → Task 1 Steps 2–3. ✓
- Persist across reload/revisit, no server round-trip → Task 1 Step 4 checks. ✓
- Jump = scroll + highlight flash → Task 2 Step 1. ✓
- Row-not-in-DOM (filtered/sorted/deleted) → "not in the current view" note → Task 2 Steps 1–2 handler + Step 2 checks. ✓
- CSP-safe delegated listeners, try/catch storage, no innerHTML → Global Constraints + code uses `textContent` and `try/catch`. ✓
- Different matter shows its own entry → keyed by `getMatterId()`; covered implicitly (key includes matterId). ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; all code blocks are concrete. ✓

**Type consistency:** `readLastEdited`, `renderLastEditedLink`, `getMatterId`, `writeLastEdited`, `LAST_EDITED_KEY`, `flashRow` names are consistent between tasks; the `#last-edited-link` DOM contract (`[data-last-edited-desc]`, `[data-jump-last-edited]`, `[data-last-edited-note]`) matches between the template (Task 1 Step 2) and the JS (Tasks 1–2). ✓
