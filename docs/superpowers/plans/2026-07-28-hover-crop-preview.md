# Hover-to-Enlarge Crop Thumbnails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hovering a crop thumbnail on the Items tab floats an enlarged copy of that crop next to it, without disturbing the existing click-to-open-editor behavior.

**Architecture:** Add two `data-*` attributes to the existing thumbnail `<img>` in `_item_row.html`, then add a single lazily-created floating `<img>` plus two document-level delegated `mouseover`/`mouseout` listeners in `app.js`. `position: fixed` + `pointer-events: none` sidesteps table-cell clipping and never intercepts clicks.

**Tech Stack:** Jinja2 template, vanilla JS in `src/cvp/static/app.js` (no build step, no framework).

## Global Constraints

- **Never use inline JS event handlers** (`onclick=`, etc.). CSP `script-src` has no `unsafe-inline`. Wire via `data-*` attributes and delegated listeners in `app.js`. (Spec + CLAUDE.md)
- **No new dependencies.** Vanilla JS only.
- Line length 100; run `uv run ruff format .` before commit only if Python changes (none expected here).
- This is a client-side, visual-only change: no Python, data-model, depreciation, or export changes.

Spec: `docs/superpowers/specs/2026-07-28-hover-crop-preview-design.md`

---

### Task 1: Hover-to-enlarge crop preview

**Files:**
- Modify: `src/cvp/templates/_item_row.html` (thumbnail `<img>`, ~lines 11–13)
- Modify: `src/cvp/static/app.js` (append new delegated-listener block near the existing `data-toggle-crop-editor` block, ~line 361)

**Interfaces:**
- Consumes: existing thumbnail `<img>` render and its `?v=<crop_updated_at>` cache-busting query already in `_item_row.html`.
- Produces: no exported symbols; self-contained DOM behavior keyed on `[data-crop-preview]`.

- [ ] **Step 1: Add data attributes to the thumbnail `<img>` in `_item_row.html`**

The current `<img>` (lines 11–13) is:

```html
      <img src="/crops/{{ item.crops[0].crop_path }}{% if item.crops[0].crop_updated_at %}?v={{ item.crops[0].crop_updated_at.timestamp() | int }}{% endif %}" alt="{{ item.description }}"
           class="object-contain rounded border border-gray-200 bg-white"
           style="width:96px;height:96px;">
```

Add `data-crop-preview` (the same URL as `src`) and `data-crop-preview-alt`:

```html
      <img src="/crops/{{ item.crops[0].crop_path }}{% if item.crops[0].crop_updated_at %}?v={{ item.crops[0].crop_updated_at.timestamp() | int }}{% endif %}" alt="{{ item.description }}"
           data-crop-preview="/crops/{{ item.crops[0].crop_path }}{% if item.crops[0].crop_updated_at %}?v={{ item.crops[0].crop_updated_at.timestamp() | int }}{% endif %}"
           data-crop-preview-alt="{{ item.description }}"
           class="object-contain rounded border border-gray-200 bg-white"
           style="width:96px;height:96px;">
```

- [ ] **Step 2: Add the floating-preview logic to `app.js`**

Append this block immediately after the existing `data-toggle-crop-editor` delegated-click listener (after line 361). It creates one reused floating image and wires `mouseover`/`mouseout` delegation. Positions to the right of the thumbnail, flips left near the right viewport edge, and clamps vertically.

```javascript
// Delegated hover: [data-crop-preview] → float an enlarged copy of the crop.
// pointer-events:none guarantees it never intercepts the "Edit crop" click.
(function () {
  var GAP = 12;
  var MAX = 400;
  var preview = null;

  function ensurePreview() {
    if (preview) return preview;
    preview = document.createElement('img');
    preview.id = 'crop-hover-preview';
    preview.style.cssText =
      'position:fixed;display:none;pointer-events:none;z-index:60;' +
      'max-width:' + MAX + 'px;max-height:' + MAX + 'px;object-fit:contain;' +
      'background:#fff;border:1px solid #d1d5db;border-radius:6px;' +
      'box-shadow:0 10px 25px rgba(0,0,0,0.25);padding:2px;';
    document.body.appendChild(preview);
    return preview;
  }

  function position(rect) {
    var p = preview;
    // Measure natural render size (bounded by MAX) after the image loads/paints.
    var w = Math.min(p.offsetWidth || MAX, MAX);
    var h = Math.min(p.offsetHeight || MAX, MAX);
    var left = rect.right + GAP;
    if (left + w > window.innerWidth) {
      left = rect.left - GAP - w; // flip to the left of the thumbnail
    }
    if (left < 0) left = GAP;
    var top = rect.top + rect.height / 2 - h / 2;
    if (top < GAP) top = GAP;
    if (top + h > window.innerHeight - GAP) top = window.innerHeight - GAP - h;
    if (top < GAP) top = GAP;
    p.style.left = left + 'px';
    p.style.top = top + 'px';
  }

  document.addEventListener('mouseover', function (e) {
    var thumb = e.target.closest('[data-crop-preview]');
    if (!thumb) return;
    var p = ensurePreview();
    var rect = thumb.getBoundingClientRect();
    if (p.getAttribute('src') !== thumb.dataset.cropPreview) {
      p.setAttribute('src', thumb.dataset.cropPreview);
      p.setAttribute('alt', thumb.dataset.cropPreviewAlt || '');
      p.onload = function () { position(rect); };
    }
    p.style.display = 'block';
    position(rect);
  });

  document.addEventListener('mouseout', function (e) {
    if (!e.target.closest('[data-crop-preview]')) return;
    if (preview) preview.style.display = 'none';
  });
})();
```

- [ ] **Step 3: Verify by driving the app**

Start the app (`uv run dev`), open a matter's Items tab that has crops, then check:
1. Hover a thumbnail → enlarged preview appears beside it, inside the viewport.
2. Hover a thumbnail on a row near the **right edge** → preview flips to the left.
3. Hover a thumbnail near the **top and bottom** of the viewport → preview stays fully on-screen.
4. Move the mouse away → preview disappears.
5. Click "Edit crop" → the crop editor still opens (regression check).
6. Trigger a scan/rescan HTMX swap, then hover a newly-inserted thumbnail → preview works (delegation check).

- [ ] **Step 4: Commit**

```bash
git add src/cvp/templates/_item_row.html src/cvp/static/app.js
git commit -m "feat(items): hover a crop thumbnail to see the enlarged crop"
```

---

## Self-Review

- **Spec coverage:** Template `data-*` attributes (Task 1 Step 1), floating single-element preview + delegated `mouseover`/`mouseout` + fixed positioning with flip/clamp (Step 2), no-interference with "Edit crop" via `pointer-events:none` (Step 2), verification incl. delegation and regression (Step 3). All spec sections covered.
- **Placeholder scan:** none — full template and JS provided.
- **Type consistency:** single self-contained IIFE; `preview`, `ensurePreview()`, `position(rect)` used consistently. `dataset.cropPreview` / `dataset.cropPreviewAlt` match the `data-crop-preview` / `data-crop-preview-alt` attributes added in Step 1.
