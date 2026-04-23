# Design: Manual Crop Adjustment Editor

**Date:** 2026-04-23  
**Status:** Approved

## Summary

Allow specialists to manually adjust the bounding boxes of item crops on the Evidence tab. When Vision's auto-detected crop is wrong (too tight, clipped, or off-center), the specialist can drag the box or type exact pixel coordinates, then re-generate the JPEG crop file. The adjusted crop is what Google Lens searches use going forward.

---

## Data Model

### Modified: `ItemCrop`

Four new nullable columns:

| column | type | notes |
|---|---|---|
| `adjusted_bbox_left` | Integer \| None | user-drawn left edge, pixels |
| `adjusted_bbox_upper` | Integer \| None | user-drawn upper edge, pixels |
| `adjusted_bbox_right` | Integer \| None | user-drawn right edge, pixels |
| `adjusted_bbox_lower` | Integer \| None | user-drawn lower edge, pixels |

New property `effective_bbox -> tuple[int, int, int, int]`:
- Returns `(adjusted_bbox_left, adjusted_bbox_upper, adjusted_bbox_right, adjusted_bbox_lower)` when **all four** are set (including zero — zero is a valid pixel coordinate).
- Falls back to `(bbox_left, bbox_upper, bbox_right, bbox_lower)` if any adjusted value is `None`.

**Important:** Claude's original `bbox_*` columns already have 15% padding baked in (applied by `_parse_bbox` in `vision.py` during scan). User-adjusted coordinates are drawn directly on the original image and represent the final crop boundary — no additional padding is applied during recrop.

### Migration

One Alembic migration adds the four `adjusted_bbox_*` columns to `item_crops`. No backfill — `None` means "use Claude's bbox."

---

## Service Layer

### New file: `src/cvp/services/crop.py`

```python
def recrop_item_crop(
    item_crop: ItemCrop,
    evidence_file: EvidenceFile,
    upload_base: Path,
    crop_base: Path,
) -> str:
    """
    Re-crop the item using effective_bbox (adjusted if set, else Claude's original).
    Opens the original evidence image, crops to effective_bbox, saves JPEG at quality 85
    to data/crops/{evidence_file_id}/{item_crop.id}.jpg.
    Returns the relative crop_path string.
    """
```

No padding is applied — the coordinates in `effective_bbox` are the final crop boundary.

### Modified: `src/cvp/services/vision.py`

The inline crop-save block inside `run_scan()` is replaced with a call to `recrop_item_crop()`. Pure refactor — no behavior change for Vision scans.

---

## API Endpoints

### New file: `src/cvp/routers/crops.py`

**1. Adjust bbox**
```
POST /api/item-crops/{crop_id}/adjust-bbox
Content-Type: application/json
Body: { "left": int, "upper": int, "right": int, "lower": int }
```
- Fetch `ItemCrop`; 404 if not found
- Open original image with Pillow to get `(img_w, img_h)`
- Validate: `left < right`, `upper < lower`, all four within `[0, img_w]` / `[0, img_h]`; 422 on failure
- Set `adjusted_bbox_*`, commit
- Return `{"ok": true}`

**2. Clear adjustment**
```
DELETE /api/item-crops/{crop_id}/adjust-bbox
```
- Set all four `adjusted_bbox_*` to `None`, commit
- Return `{"ok": true}`

**3. Load crop editor panel**
```
GET /api/evidence/{file_id}/crop-editor  →  HTML partial
```
- Fetch `EvidenceFile` and all associated `ItemCrop` rows (with `Item` description loaded)
- Open image with Pillow to read `(img_w, img_h)`
- Render `_crop_editor.html` with:
  - `evidence_file` (for image URL)
  - `img_w`, `img_h`
  - `crops_json`: JSON array of `{ id, description, bbox: effective_bbox, claude_bbox: original_bbox, adjusted: bool }`

**4. Re-crop adjusted items**
```
POST /api/evidence/{file_id}/recrop
```
- Fetch all `ItemCrop` rows for this file where any `adjusted_bbox_*` is not `None`
- For each: call `recrop_item_crop()`, update `item_crop.crop_path`, commit
- Return `{"recropped": ["crop_id_1", "crop_id_2", ...]}`

### Modified: `src/cvp/main.py`

Register `crops.router` alongside existing routers.

---

## UI

### Entry point — Evidence tab (`_tab_evidence.html`)

Each scanned evidence file row that has at least one `ItemCrop` gains an **"Edit crops"** button. Clicking calls `toggleCropEditor(fileId)` in `app.js`, which fires an HTMX GET to `/api/evidence/{file_id}/crop-editor` and inserts the response after the file row (`hx-swap="afterend"`). A second click removes the panel.

### New template: `src/cvp/templates/_crop_editor.html`

Two-column layout inside a `<div>` (not a `<tr>` — the evidence tab uses cards/divs, not a table):

**Left — canvas:**
- `<canvas>` element scaled to fit the container width (`scale = min(1, containerWidth / img_w)`)
- Original evidence photo drawn as background
- All item bboxes drawn as colored rectangles with 1-digit index labels
  - Indigo: Claude's original (no adjustment)
  - Amber: user-adjusted
- Selected item: 8 resize handles (corners + edge midpoints), red ✕ delete icon at top-right of box
- Drag box body → move; drag handle → resize one or two edges
- Minimum box size: 10×10px; coordinates clamped to image bounds

**Right — sidebar:**
- Item name (`#N description`)
- Four numeric inputs: Left, Upper, Right, Lower (sync live with canvas during drag; save on `blur` or `Enter`)
- "Reset to Claude bbox" link
- Error message line (hidden until needed)
- Bottom: "Re-crop adjusted items (N)" button + status line

**Interaction model:**
- `mousedown` → select item or begin drag (handles take priority over box-move)
- `mousemove` → live preview; updates canvas and sidebar inputs
- `mouseup` → auto-save via `POST /api/item-crops/{crop_id}/adjust-bbox`
- Numeric input `blur` / `Enter` → validate, update canvas, auto-save
- "Reset" → `DELETE /api/item-crops/{crop_id}/adjust-bbox`, restores Claude bbox in canvas and inputs
- "Re-crop" → `POST /api/evidence/{file_id}/recrop`, cache-busts crop thumbnail `<img>` tags in the open serp panel by appending `?v=<timestamp>` to their `src`

### Modified: `src/cvp/static/app.js`

Add `toggleCropEditor(fileId)` — mirrors the existing `toggleSerpPanel(itemId)` pattern.

---

## Testing

- `tests/test_item_crop_bbox.py` — unit tests for `ItemCrop.effective_bbox`:
  - Returns Claude bbox when no adjustment set
  - Returns adjusted bbox when all four are set
  - Falls back to Claude bbox if any adjusted value is `None`
  - Treats `0` as a valid coordinate (not "unset")
- `tests/test_crop_service.py` — unit tests for `recrop_item_crop`:
  - Saves JPEG to correct path, returns correct relative path
  - Uses adjusted bbox when set (output size differs from Claude bbox)
- Integration tests in `tests/test_crops_router.py`:
  - `POST adjust-bbox` stores values, rejects invalid coords, 404 for unknown crop
  - `DELETE adjust-bbox` clears values
  - `POST recrop` regenerates crop files, skips items without adjustment

---

## Out of Scope

- Touch / mobile drag support
- Multi-select or bulk adjust
- Undo/redo history
- Zoom controls on the canvas
