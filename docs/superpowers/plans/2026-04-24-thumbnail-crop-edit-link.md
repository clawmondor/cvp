# Thumbnail Crop-Edit Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hovering over a cropped thumbnail in the Items table reveals an "Edit crop" overlay that opens a new tab to the Evidence tab with the crop editor pre-opened and the item's bounding box pre-selected.

**Architecture:** Four files change. The thumbnail cell in both item row templates gets a hover overlay `<a>` linking to `/matters/{matter_id}?file={evidence_file_id}&crop={crop_id}#evidence`. The crop editor exposes a `ceSelect_*` function on `window`. `app.js` reads URL params on load, calls `toggleCropEditor`, then auto-selects the crop via `htmx:afterSettle`.

**Tech Stack:** Jinja2 templates, vanilla JS, HTMX, Tailwind CSS via CDN, pytest + FastAPI TestClient for integration tests.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/cvp/templates/_items_tbody.html` | Wrap thumbnail `<img>` in hover-overlay group (bulk render) |
| Modify | `src/cvp/templates/_item_row.html` | Same change for single-row re-renders (edit/confirm) |
| Modify | `src/cvp/templates/_crop_editor.html` | Expose `ceSelect_<EF_ID>(cropId)` on `window` |
| Modify | `src/cvp/static/app.js` | Auto-init on `DOMContentLoaded`: open editor + select crop |
| Create | `tests/test_items_template.py` | Integration test: items tbody renders crop-edit link |

---

### Task 1: Write failing template integration test

**Files:**
- Create: `tests/test_items_template.py`

- [ ] **Step 1: Create the test file**

```python
"""Integration test: items tbody renders crop-edit overlay link."""
import pytest
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from urllib.parse import quote_plus

TEMPLATE_DIR = Path(__file__).parent.parent / "src" / "cvp" / "templates"


@pytest.fixture
def env():
    e = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    e.filters["qplus"] = quote_plus
    return e


class FakeCrop:
    def __init__(self):
        self.id = "crop-abc"
        self.evidence_file_id = "ef-xyz"
        self.crop_path = "ef-xyz/item.jpg"


class FakeItem:
    def __init__(self):
        self.id = "item-1"
        self.matter_id = "matter-1"
        self.line_number = 1
        self.description = "Lamp"
        self.brand = None
        self.model = None
        self.source_url = "https://example.com"
        self.search_hint = None
        self.room_id = None
        self.category_id = 1
        self.quantity = 1
        self.age_years = 3
        self.condition = "average"
        self.rcv_unit_cents = 5000
        self.rcv_total_cents = 5000
        self.acv_total_cents = 4000
        self.acv_override_cents = None
        self.acv_override_reason = None
        self.confirmed = False
        self.excluded = False
        self.crops = [FakeCrop()]


def test_tbody_renders_crop_edit_link(env):
    tmpl = env.get_template("_items_tbody.html")
    html = tmpl.render(items=[FakeItem()], categories=[], rooms=[], conditions=[])
    assert "Edit crop" in html
    assert "/matters/matter-1?file=ef-xyz&amp;crop=crop-abc#evidence" in html
    assert 'target="_blank"' in html


def test_tbody_no_overlay_when_no_crop(env):
    item = FakeItem()
    item.crops = []
    tmpl = env.get_template("_items_tbody.html")
    html = tmpl.render(items=[item], categories=[], rooms=[], conditions=[])
    assert "Edit crop" not in html


def test_tbody_no_overlay_when_crop_path_empty(env):
    item = FakeItem()
    item.crops[0].crop_path = None
    tmpl = env.get_template("_items_tbody.html")
    html = tmpl.render(items=[item], categories=[], rooms=[], conditions=[])
    assert "Edit crop" not in html
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
source .venv/bin/activate && uv run pytest tests/test_items_template.py -v
```

Expected: All three tests FAIL — "Edit crop" not found in HTML (overlay doesn't exist yet).

---

### Task 2: Add hover overlay to `_items_tbody.html`

**Files:**
- Modify: `src/cvp/templates/_items_tbody.html` lines 10–17

- [ ] **Step 1: Replace the thumbnail `<td>` content**

In `_items_tbody.html`, find this block (lines 10–17):

```html
  <td class="px-2 py-1" style="width:100px;min-width:100px;">
    {% if item.crops and item.crops[0].crop_path %}
    <img src="/crops/{{ item.crops[0].crop_path }}" alt="{{ item.description }}"
         class="object-contain rounded border border-gray-200 bg-white"
         style="width:96px;height:96px;">
    {% else %}
    <div class="rounded border border-gray-100 bg-gray-50" style="width:96px;height:96px;"></div>
    {% endif %}
  </td>
```

Replace it with:

```html
  <td class="px-2 py-1" style="width:100px;min-width:100px;">
    {% if item.crops and item.crops[0].crop_path %}
    <div class="relative group/thumb inline-block" style="width:96px;height:96px;">
      <img src="/crops/{{ item.crops[0].crop_path }}" alt="{{ item.description }}"
           class="object-contain rounded border border-gray-200 bg-white"
           style="width:96px;height:96px;">
      <a href="/matters/{{ item.matter_id }}?file={{ item.crops[0].evidence_file_id }}&crop={{ item.crops[0].id }}#evidence"
         target="_blank"
         rel="noopener"
         class="absolute inset-x-0 bottom-0 flex items-center justify-center py-1
                bg-black/50 opacity-0 group-hover/thumb:opacity-100
                transition-opacity rounded-b text-white text-xs font-medium">
        Edit crop
      </a>
    </div>
    {% else %}
    <div class="rounded border border-gray-100 bg-gray-50" style="width:96px;height:96px;"></div>
    {% endif %}
  </td>
```

- [ ] **Step 2: Run the tests**

```bash
source .venv/bin/activate && uv run pytest tests/test_items_template.py -v
```

Expected: All three tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/templates/_items_tbody.html tests/test_items_template.py
git commit -m "feat: add Edit crop hover overlay to items tbody thumbnail"
```

---

### Task 3: Add hover overlay to `_item_row.html`

**Files:**
- Modify: `src/cvp/templates/_item_row.html` lines 8–15

`_item_row.html` is used for single-row HTMX re-renders (after edit/confirm/toggle). It must stay in sync with `_items_tbody.html`.

- [ ] **Step 1: Replace the thumbnail `<td>` content**

In `_item_row.html`, find this block (lines 8–15):

```html
  <td class="px-2 py-1" style="width:100px;min-width:100px;">
    {% if item.crops and item.crops[0].crop_path %}
    <img src="/crops/{{ item.crops[0].crop_path }}" alt="{{ item.description }}"
         class="object-contain rounded border border-gray-200 bg-white"
         style="width:96px;height:96px;">
    {% else %}
    <div class="rounded border border-gray-100 bg-gray-50" style="width:96px;height:96px;"></div>
    {% endif %}
  </td>
```

Replace it with:

```html
  <td class="px-2 py-1" style="width:100px;min-width:100px;">
    {% if item.crops and item.crops[0].crop_path %}
    <div class="relative group/thumb inline-block" style="width:96px;height:96px;">
      <img src="/crops/{{ item.crops[0].crop_path }}" alt="{{ item.description }}"
           class="object-contain rounded border border-gray-200 bg-white"
           style="width:96px;height:96px;">
      <a href="/matters/{{ item.matter_id }}?file={{ item.crops[0].evidence_file_id }}&crop={{ item.crops[0].id }}#evidence"
         target="_blank"
         rel="noopener"
         class="absolute inset-x-0 bottom-0 flex items-center justify-center py-1
                bg-black/50 opacity-0 group-hover/thumb:opacity-100
                transition-opacity rounded-b text-white text-xs font-medium">
        Edit crop
      </a>
    </div>
    {% else %}
    <div class="rounded border border-gray-100 bg-gray-50" style="width:96px;height:96px;"></div>
    {% endif %}
  </td>
```

- [ ] **Step 2: Run all tests to confirm nothing broke**

```bash
source .venv/bin/activate && uv run pytest -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/templates/_item_row.html
git commit -m "feat: add Edit crop hover overlay to item_row thumbnail (single-row re-renders)"
```

---

### Task 4: Expose `ceSelect_*` in crop editor

**Files:**
- Modify: `src/cvp/templates/_crop_editor.html`

The crop editor IIFE already exposes `window['ceReset_' + EF_ID.replace(/-/g,'_')]`. We add a parallel `ceSelect_*` function.

- [ ] **Step 1: Add the export after the `ceReset_*` block**

In `_crop_editor.html`, find this block (around line 202):

```js
  window['ceReset_' + EF_ID.replace(/-/g, '_')] = function() {
    if (selectedIdx === null) return;
    var box = boxes[selectedIdx];
    fetch('/api/item-crops/' + box.id + '/adjust-bbox', {method:'DELETE'}).then(function(r) {
      if (!r.ok) return;
      box.left = box.claudeLeft; box.upper = box.claudeUpper;
      box.right = box.claudeRight; box.lower = box.claudeLower;
      box.adjusted = false;
      draw(); updateSidebar(); updateRecropButton();
    });
  };
```

Add the following immediately after it (before the `function updateSidebarInputs` line):

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

- [ ] **Step 2: Run all tests**

```bash
source .venv/bin/activate && uv run pytest -v
```

Expected: All tests PASS (template change has no automated test — manual verification in Task 6).

- [ ] **Step 3: Commit**

```bash
git add src/cvp/templates/_crop_editor.html
git commit -m "feat: expose ceSelect_* on window for programmatic crop selection"
```

---

### Task 5: Add auto-init block to `app.js`

**Files:**
- Modify: `src/cvp/static/app.js`

- [ ] **Step 1: Append the auto-init block at the end of `app.js`**

At the very end of `src/cvp/static/app.js` (after the closing `}` of `toggleCropEditor`), add:

```js
// ── Crop-edit deep-link auto-init ────────────────────────────────────────────
// When the page is opened via the "Edit crop" thumbnail link (?file=&crop=#evidence),
// auto-open the crop editor for the evidence file and pre-select the item's crop.
document.addEventListener('DOMContentLoaded', function () {
  var params = new URLSearchParams(window.location.search);
  var fileId = params.get('file');
  var cropId = params.get('crop');
  if (!fileId) return;

  // The hash is already #evidence; initTabs (also on DOMContentLoaded) activates the panel.
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

- [ ] **Step 2: Run all tests**

```bash
source .venv/bin/activate && uv run pytest -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/static/app.js
git commit -m "feat: auto-open crop editor and select crop from URL params on Evidence tab"
```

---

### Task 6: Manual end-to-end verification

No automated test covers browser behaviour. Run the dev server and verify the full flow.

- [ ] **Step 1: Start the server**

```bash
source .venv/bin/activate && uv run dev
```

Open `http://localhost:8000` in a browser.

- [ ] **Step 2: Verify overlay appears on hover**

1. Navigate to any matter that has items with scanned crops (thumbnails visible).
2. Go to the **Items** tab.
3. Hover over a thumbnail that shows a photo (not a blank grey box).
4. Expected: a semi-transparent "Edit crop" label appears across the bottom of the thumbnail.
5. Hover away — label disappears.
6. Hover over a blank grey placeholder — no label appears.

- [ ] **Step 3: Verify new tab opens with crop editor pre-selected**

1. Click the "Edit crop" overlay on a cropped thumbnail.
2. Expected: a new browser tab opens.
3. The new tab shows the same matter page on the **Evidence** tab (not Overview).
4. The crop editor is already open for the correct evidence photo.
5. The item's bounding box is highlighted/selected (handles visible, sidebar shows the item description and coordinate inputs).

- [ ] **Step 4: Verify single-row re-renders preserve the overlay**

1. On the Items tab, click **Edit** on a row that has a crop, make any change, save.
2. The row re-renders via HTMX.
3. Hover over the thumbnail again — "Edit crop" overlay still appears with the correct link.
