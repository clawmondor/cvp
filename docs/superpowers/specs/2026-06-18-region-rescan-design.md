# Region Rescan — Design

**Date:** 2026-06-18
**Status:** Approved (brainstorm)

## Problem

The whole-image vision scan does not always detect every item in a photo. A
specialist needs a way to point at a region the scan missed and have just that
region scanned, creating the items it contains.

## Overview

Extend the existing crop editor with a "draw a box → scan that region" flow. The
user draws a new rectangle over a missed region; that sub-region is cropped from
the original image and scanned through the **existing async vision pipeline**,
creating new `Item`s + `ItemCrop`s positioned in original-image coordinates so
they render correctly on the full photo and in the Items tab.

This reuses the current scanning machinery as much as possible. The model sees
the cropped region as if it were a whole image; returned bounding boxes are
translated back into the full image's coordinate space.

## Decisions (from brainstorm)

- **UI placement:** extend the existing crop editor modal (not a separate modal).
- **Execution:** async via the existing `VisionJob` / `VisionJobImage` / worker
  pipeline (respects the sequential + 500 ms rule, restart-safe, consistent with
  bulk scans).
- **Model:** reuse the user's `last_vision_model_slug` silently — no per-scan
  picker.
- **Region count:** one region per scan (draw, scan, repeat). Batched multi-region
  is out of scope.

## Data model

One additive migration. Add four nullable region columns to `VisionJobImage`:

- `region_left: int | None`
- `region_upper: int | None`
- `region_right: int | None`
- `region_lower: int | None`

Semantics:

- All four `NULL` → ordinary whole-image scan. Existing behavior is untouched.
- All four set → region scan of that sub-rectangle of the evidence image.

No new tables. "Each region = one image in a job" fits the existing schema. A
one-image `VisionJob` is created per region scan.

## Worker changes (`services/vision.py::process_one_image`)

A branch keyed on whether the region columns are set. Whole-image path is
unchanged.

1. **Skip-guard fix.** Today the worker skips when `ef.scanned is True` (restart
   recovery). Region images must bypass that guard, because the file is already
   marked scanned. For region images, idempotency keys off
   `VisionJobImage.status` (skip only if already `done`), not `ef.scanned`.
2. **Crop before scan.** Open the original image and `crop((left, upper, right,
   lower))` to the region. Then run the *same* downscale + `build_scan_prompt(
   crop_w, crop_h)` + `openrouter.call_vision` as the whole-image path. The model
   receives the region as a standalone image.
3. **Translate coordinates back.** Returned item bboxes are in crop space (or
   downscaled-crop space). Scale back from any downscale using the crop
   dimensions, then offset by `(region_left, region_upper)` so the resulting
   `ItemCrop` bboxes are in original-image coordinates. `recrop_item_crop` then
   works unchanged.
4. **Reuse item creation.** Line numbering, `_match_category_id`,
   `_resolve_effective_item_group_id` (so new items inherit the file's pinned
   item group / placard logic) are all unchanged.
5. **Side effects.** `ef.scanned` stays `True`. A `VisionRun` row is still written
   for the audit trail. `VisionJobImage.items_created` is set as today.

## Endpoint

`POST /api/evidence/{file_id}/region-scan` (in `routers/vision.py`).

- Body (JSON): `{left, upper, right, lower}` — integers in original-image pixels.
- Validation: reuse the bbox validation from `routers/crops.py` (left < right,
  upper < lower, all within image bounds). Return 422 on failure, 404 if the file
  is missing or not an image.
- Resolve the user's `last_vision_model_slug`; if unset or the model is disabled,
  return a clear error fragment.
- Create a one-image `VisionJob` (status `running`) with a single
  `VisionJobImage` whose `evidence_file_id` is the file and whose region columns
  are populated.
- Wake the worker (`vision_worker.wake()`), audit-log (`action="vision.region"`),
  and return the `_scan_progress.html` fragment so the existing polling UI drives
  it.
- Guarded by `require_matter_role("contributor")` like other scan endpoints.

## Frontend (`crop-editor.js` + `_crop_editor.html`)

- **"Draw scan region" toggle button** in the editor controls. While active,
  dragging on empty canvas space rubber-bands a new rectangle (distinct color,
  e.g. green) instead of deselecting an existing box.
- Once a region is drawn, a **"Scan this region"** button POSTs the region bbox
  (in original-image pixels — convert from canvas coords using the existing `fc()`
  scale helper) to the new endpoint, and renders the returned `_scan_progress.html`
  fragment in the sidebar. It polls the existing
  `GET /api/matters/{matter_id}/vision-scan/{job_id}` endpoint.
- **On completion:** re-fetch the crop-editor crop data and redraw so the newly
  detected item boxes appear on the canvas; show "N items created." Switching to
  the Items tab shows the new rows.
- All interactivity wired via `data-*` attributes and delegated listeners
  (CSP-safe; no inline `on*` handlers). One region drawn at a time; drawing a new
  region replaces the previous unsaved one.

## Testing

- **Worker unit test:** a region-scan `VisionJobImage` with a mocked vision
  response → items created with bboxes offset into original-image space; an
  already-`scanned=True` file does *not* cause the region image to skip.
- **Coordinate-translation test:** downscale + offset round-trip produces correct
  original-image `ItemCrop` coordinates.
- **Endpoint integration test:** happy path (bbox validation + one-image job
  creation), vision mocked; plus a 422 for an out-of-bounds bbox.

## Out of scope (YAGNI)

- Multiple batched regions in one scan.
- Per-scan model picker.
- Editing or re-running a region scan after the fact.
