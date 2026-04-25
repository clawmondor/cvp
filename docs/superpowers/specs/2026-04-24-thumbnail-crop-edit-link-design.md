# Thumbnail Crop-Edit Link — Design Spec

**Date:** 2026-04-24  
**Status:** Approved

## Problem

On the Items tab, each row has a thumbnail showing the item's cropped photo. If the crop needs adjusting, the specialist must navigate to the Evidence tab, find the right photo card, click "Edit crops", and manually locate the correct bounding box. There is no direct path from thumbnail to crop editor.

## Goal

Hovering over a thumbnail in the Items table reveals an "Edit crop" overlay link. Clicking it opens a new browser tab on the Evidence tab of the same matter, with the crop editor already open and the item's bounding box pre-selected.

## Scope

Four files change. No new routes, no new templates, no new dependencies.

| File | Change |
|---|---|
| `src/cvp/templates/_items_tbody.html` | Thumbnail cell → hover overlay with link |
| `src/cvp/templates/_item_row.html` | Same change (single-row re-renders after edit/confirm) |
| `src/cvp/templates/_crop_editor.html` | Expose `ceSelect_<EF_ID>(cropId)` on `window` |
| `src/cvp/static/app.js` | Auto-init block: open editor + select crop from URL params |

## URL Scheme

The "Edit crop" link targets:

```
/matters/{item.matter_id}?file={evidence_file_id}&crop={crop_id}#evidence
```

- `#evidence` causes `initTabs` to activate the Evidence panel on load (existing behaviour).
- `?file=` and `?crop=` are read by new auto-init logic in `app.js`.

## Hover Overlay

Only appears when `item.crops and item.crops[0].crop_path` (i.e. the item has a real crop). Blank placeholder cells get no overlay.

The `<img>` is wrapped in a `relative group/thumb` div. A translucent bottom-strip `<a>` is hidden by default and shown on `group-hover/thumb`:

```html
<div class="relative group/thumb inline-block" style="width:96px;height:96px;">
  <img src="/crops/{{ item.crops[0].crop_path }}" ...>
  <a href="/matters/{{ item.matter_id }}?file={{ item.crops[0].evidence_file_id }}&crop={{ item.crops[0].id }}#evidence"
     target="_blank"
     rel="noopener"
     class="absolute inset-x-0 bottom-0 flex items-center justify-center py-1
            bg-black/50 opacity-0 group-hover/thumb:opacity-100
            transition-opacity rounded-b text-white text-xs font-medium">
    Edit crop
  </a>
</div>
```

`item.matter_id`, `item.crops[0].evidence_file_id`, and `item.crops[0].id` are all ORM attributes available in both templates without any context changes. Crops are already eager-loaded via `selectinload(Item.crops)`.

## Crop Editor — Exposed Select Function

Inside the IIFE in `_crop_editor.html`, alongside the existing `ceReset_*` export:

```js
window['ceSelect_' + EF_ID.replace(/-/g, '_')] = function(cropId) {
  var idx = boxes.findIndex(function(b) { return b.id === cropId; });
  if (idx >= 0) {
    selectedIdx = idx;
    draw();
    updateSidebar();
  }
};
```

## Auto-Init Logic in `app.js`

Appended after the existing `toggleCropEditor` function, runs on `DOMContentLoaded`:

```js
document.addEventListener('DOMContentLoaded', function () {
  var params = new URLSearchParams(window.location.search);
  var fileId = params.get('file');
  var cropId = params.get('crop');
  if (!fileId) return;

  // Hash is already #evidence; initTabs activates the right panel.
  toggleCropEditor(fileId);

  if (cropId) {
    document.addEventListener('htmx:afterSettle', function handler() {
      var fnName = 'ceSelect_' + fileId.replace(/-/g, '_');
      if (window[fnName]) {
        window[fnName](cropId);
        document.removeEventListener('htmx:afterSettle', handler);
      }
    });
  }
});
```

The `htmx:afterSettle` listener fires once after HTMX inserts the crop editor and its inline `<script>` registers `ceSelect_*`, selects the crop, then removes itself.

## What Is Not Changing

- No new FastAPI routes or Pydantic models.
- No changes to the data model or migrations.
- The crop editor's existing drag/resize/autosave/recrop behaviour is unchanged.
- Items with no crop (blank placeholder) show no overlay.
