# Crop Editor Modal Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the crop editor from a sibling of `#evidence-grid` (HTMX `swap: 'afterend'`) to a viewport-level centered modal mounted in `base.html`, so opening/closing it never disrupts the user's tab or scroll position, and the Items tab "Edit crop" button can open it in-place.

**Architecture:** A single `<div id="crop-editor-modal-root">` lives at the bottom of `base.html`. Every trigger routes through the existing delegated `data-toggle-crop-editor` handler in `app.js`, which calls `htmx.ajax(...)` into the root with `innerHTML` swap. The `_crop_editor.html` partial now wraps its contents in a fixed-position backdrop + centered dialog card. Close paths (✕ button, Esc keypress) clear the root's innerHTML and release a body-level scroll lock.

**Tech Stack:** Jinja2 templates, HTMX 1.x, plain JS (delegated event handlers), Tailwind via CDN, pytest + FastAPI TestClient.

**Spec reference:** `docs/superpowers/specs/2026-06-08-crop-editor-modal-overlay-design.md`

---

## File map

- **Modify** `src/cvp/templates/base.html` — add modal root div before `</body>`.
- **Modify** `src/cvp/templates/_crop_editor.html` — wrap inner content in backdrop + dialog shell; remove redundant card chrome classes from inner div.
- **Modify** `src/cvp/templates/_item_row.html` — convert "Edit crop" anchor to a button with `data-toggle-crop-editor` + `data-preselect-crop`.
- **Modify** `src/cvp/static/app.js` — rewrite `toggleCropEditor`, extend delegated click handler to read `data-preselect-crop`, add Esc keydown handler with scroll-lock cleanup, update DOMContentLoaded deep-link path.
- **Modify** `src/cvp/static/crop-editor.js` — change close-button handler to clear the modal root; add preselect post-init step.
- **Create** `tests/test_crop_editor_modal.py` — integration test asserting the modal shell + inner editor markup are both present in the route response.

---

### Task 1: Add modal root mount point in base.html

**Files:**
- Modify: `src/cvp/templates/base.html` (insert before `</body>`)

- [ ] **Step 1: Read base.html and locate the closing `</body>` tag**

Run: `grep -n "</body>" src/cvp/templates/base.html`
Expected: a single line number — note it. We will insert directly before that line.

- [ ] **Step 2: Insert the modal root div**

Add this line immediately before `</body>`:

```html
<div id="crop-editor-modal-root"></div>
```

- [ ] **Step 3: Verify the page still renders**

Start the dev server in another shell: `uv run dev`
Open `http://localhost:8000` and confirm the splash/login renders without error. Check the rendered HTML source (View Source) for `<div id="crop-editor-modal-root"></div>` just before `</body>`. Stop the dev server.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/templates/base.html
git commit -m "feat: add crop-editor-modal-root mount point to base.html"
```

---

### Task 2: Wrap _crop_editor.html in modal shell

**Files:**
- Modify: `src/cvp/templates/_crop_editor.html` (entire file)

- [ ] **Step 1: Replace `_crop_editor.html` with the modal-wrapped version**

Replace the entire file contents with:

```jinja
<div class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
  <div class="relative max-w-5xl w-full max-h-[90vh] overflow-auto bg-white rounded-lg shadow-xl p-4">
    <div id="crop-editor-{{ evidence_file.id }}"
         data-init="crop-editor"
         data-ef-id="{{ evidence_file.id }}"
         data-img-w="{{ img_w }}"
         data-img-h="{{ img_h }}"
         data-img-src="/files/{{ stored_path }}">

      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-semibold text-gray-800">Edit crops — {{ evidence_file.filename }}</h3>
        <button data-crop-editor-close="{{ evidence_file.id }}"
                class="text-xs text-gray-400 hover:text-gray-700">✕ Close</button>
      </div>

      <div class="flex gap-4">
        <!-- Canvas -->
        <div class="flex-shrink-0">
          <canvas id="ce-canvas-{{ evidence_file.id }}"
                  class="block rounded border border-gray-200 cursor-crosshair"
                  style="max-width:100%"></canvas>
        </div>

        <!-- Sidebar -->
        <div class="flex flex-col gap-2 min-w-[210px] w-56">
          <div id="ce-sidebar-{{ evidence_file.id }}">
            <p class="text-xs text-gray-400">Click a box to select it.</p>
          </div>
          <div class="mt-auto pt-2 border-t border-gray-100">
            <button id="ce-recrop-btn-{{ evidence_file.id }}"
                    disabled
                    class="w-full rounded bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed">
              Re-crop adjusted items (0)
            </button>
            <p id="ce-status-{{ evidence_file.id }}" class="mt-1 text-xs text-gray-400"></p>
          </div>
        </div>
      </div>

    </div>
    <script type="application/json" id="crop-data-{{ evidence_file.id }}">{{ crops_json | tojson }}</script>
  </div>
</div>
```

Key differences from the previous version:
1. Two new outer wrappers: backdrop (`fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4`) and dialog card (`relative max-w-5xl w-full max-h-[90vh] overflow-auto bg-white rounded-lg shadow-xl p-4`).
2. The inner `crop-editor-<id>` div no longer carries `mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm` — the dialog wrapper provides card chrome and padding now.
3. All `id`, `data-*` attributes on the inner div and on the script tag are preserved exactly — `crop-editor.js` finds them by id.

- [ ] **Step 2: Render-check via the existing route**

We can't easily render this partial in isolation; instead verify in Task 8 (integration test) and Task 9 (manual). For now, just confirm Jinja parses it:

Run: `uv run python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('src/cvp/templates')).get_template('_crop_editor.html')"`
Expected: no output (success). Any TemplateSyntaxError fails this step.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/templates/_crop_editor.html
git commit -m "feat: wrap crop editor partial in modal backdrop + dialog shell"
```

---

### Task 3: Rewrite `toggleCropEditor` and extend the delegated click handler in app.js

**Files:**
- Modify: `src/cvp/static/app.js:116-128` (toggleCropEditor function)
- Modify: `src/cvp/static/app.js:243-275` (delegated click handler region)

- [ ] **Step 1: Inspect the current code**

Run: `sed -n '116,128p' src/cvp/static/app.js`
Expected: see the existing `toggleCropEditor` function (the one targeting `#evidence-grid` with `afterend`).

Run: `grep -n "data-toggle-crop-editor" src/cvp/static/app.js`
Expected: one line in the delegated click handler region (around 245). Note the exact line.

- [ ] **Step 2: Replace `toggleCropEditor`**

Replace the existing function (currently at lines 116-128) with:

```javascript
// ── Crop editor toggle ───────────────────────────────────────────────────
function toggleCropEditor(fileId, opts) {
  opts = opts || {};
  const root = document.getElementById('crop-editor-modal-root');
  if (!root) return;
  // Re-entrancy guard: don't stack a second open while one is loaded or in flight.
  if (root.children.length > 0 || root.dataset.loading === '1') return;
  if (opts.preselectCropId) {
    root.dataset.preselectCrop = opts.preselectCropId;
  }
  root.dataset.loading = '1';
  document.body.classList.add('overflow-hidden');
  htmx.ajax('GET', '/api/evidence/' + fileId + '/crop-editor', {
    target: root,
    swap: 'innerHTML',
  }).finally(function () {
    delete root.dataset.loading;
  });
}
```

Notes:
- We deliberately **do not** preserve the old "if already open, remove" toggle behavior. The modal closes via ✕ or Esc only; a second click on the same button while the modal is open is a no-op (guarded by the children-count check).
- `htmx.ajax(...)` returns a promise in HTMX 1.x; `.finally` clears the loading flag on both success and error.

- [ ] **Step 3: Extend the delegated click handler to pass `preselectCropId`**

Find the existing click handler that binds `data-toggle-crop-editor` (around line 243-275). It currently looks like:

```javascript
// Delegated click: data-toggle-crop-editor → toggleCropEditor(fileId)
document.addEventListener('click', function (e) {
  var btn = e.target.closest('[data-toggle-crop-editor]');
  if (!btn) return;
  e.preventDefault();
  toggleCropEditor(btn.dataset.toggleCropEditor);
});
```

Replace that block with:

```javascript
// Delegated click: data-toggle-crop-editor → toggleCropEditor(fileId, opts)
document.addEventListener('click', function (e) {
  var btn = e.target.closest('[data-toggle-crop-editor]');
  if (!btn) return;
  e.preventDefault();
  var opts = {};
  if (btn.dataset.preselectCrop) {
    opts.preselectCropId = btn.dataset.preselectCrop;
  }
  toggleCropEditor(btn.dataset.toggleCropEditor, opts);
});
```

If the existing block differs (different variable name, different e.preventDefault placement), preserve the surrounding shape — only the body needs to read `data-preselect-crop` and pass it through.

- [ ] **Step 4: Smoke-check via dev server**

Run `uv run dev` in another shell, navigate to a matter that has at least one scanned evidence image, click **Edit crops** on the grid card. Expected: the modal appears centered, with backdrop. The image and crop boxes render in the canvas. Click ✕ — modal disappears, page scroll is at the same position. Stop the dev server.

If ✕ does not close the modal yet, that is correct — the close handler is rewritten in Task 6.

- [ ] **Step 5: Commit**

```bash
git add src/cvp/static/app.js
git commit -m "feat: route crop editor open through modal root with preselect support"
```

---

### Task 4: Add document-level Esc keydown handler in app.js

**Files:**
- Modify: `src/cvp/static/app.js` (add new top-level listener, place it near the existing delegated click listener around line 240, before the DOMContentLoaded block at line 133)

- [ ] **Step 1: Decide on the listener location**

Find an empty line just above (or just below) the delegated click listener for `data-toggle-crop-editor`. The new listener is self-contained and only needs to be installed once at script load.

- [ ] **Step 2: Insert the Esc handler**

Add this block:

```javascript
// Esc closes the crop editor modal (ignores when typing in form fields).
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  var root = document.getElementById('crop-editor-modal-root');
  if (!root || root.children.length === 0) return;
  var tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  root.innerHTML = '';
  delete root.dataset.preselectCrop;
  document.body.classList.remove('overflow-hidden');
});
```

- [ ] **Step 3: Smoke-check**

Run `uv run dev`, open a matter, click **Edit crops**, press Esc. Expected: modal closes; body scroll restored. Press Esc again — no-op. Stop the dev server.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/static/app.js
git commit -m "feat: Esc closes crop editor modal and releases body scroll lock"
```

---

### Task 5: Update DOMContentLoaded deep-link to use new toggleCropEditor signature

**Files:**
- Modify: `src/cvp/static/app.js:130-160` (the existing `// ── Crop-edit deep-link auto-init` block)

- [ ] **Step 1: Read the current deep-link block**

Run: `sed -n '130,165p' src/cvp/static/app.js`
Expected: a `DOMContentLoaded` handler that reads `?file=&crop=` from `window.location.search`, calls `toggleCropEditor(fileId)`, then attempts to call `window['ceSelect_' + fileId.replace(/-/g, '_')](cropId)` via an `htmx:afterSettle` polling pattern.

- [ ] **Step 2: Replace the block**

Replace lines 130-160 (the entire `// ── Crop-edit deep-link auto-init ────────` section through to and including the last `});` of the DOMContentLoaded handler) with:

```javascript
// ── Crop-edit deep-link auto-init ────────────────────────────────────────────
// When the page is opened via the "Edit crop" thumbnail link (?file=&crop=#evidence),
// auto-open the modal for the evidence file and pre-select the item's crop.
// Preselect handling is consolidated in crop-editor.js (reads root.dataset.preselectCrop
// after htmx:afterSettle).
document.addEventListener('DOMContentLoaded', function () {
  var params = new URLSearchParams(window.location.search);
  var fileId = params.get('file');
  var cropId = params.get('crop');
  if (!fileId) return;
  // The hash is already #evidence (handled by initTabs).
  toggleCropEditor(fileId, cropId ? { preselectCropId: cropId } : {});
});
```

Notes:
- This is shorter than the previous block. The polling for `ceSelect_*` is no longer needed because `crop-editor.js` will read the preselect attribute directly after init (Task 6).

- [ ] **Step 3: Smoke-check**

We can't fully test this until Tasks 6 and 7 land (preselect consumption + Items button). The legacy URL behavior is verified in Task 9 manual checks. For now: run `uv run dev`, hit the page without query params — no errors in console. Stop the dev server.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/static/app.js
git commit -m "refactor: route deep-link crop preselect through toggleCropEditor opts"
```

---

### Task 6: Rewrite close handler and add preselect post-init in crop-editor.js

**Files:**
- Modify: `src/cvp/static/crop-editor.js:3-9` (close-button handler)
- Modify: `src/cvp/static/crop-editor.js:12-17` (htmx:afterSettle initializer block — append preselect consumption inside the init function or just after init)

- [ ] **Step 1: Read the current file**

Run: `sed -n '1,25p' src/cvp/static/crop-editor.js`
Expected: see the existing close-button handler and the `htmx:afterSettle` initializer.

- [ ] **Step 2: Replace the close-button handler**

Replace the existing block (currently at lines 3-9):

```javascript
  // Close button: data-crop-editor-close="<ef-id>" removes the editor container
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-crop-editor-close]');
    if (!btn) return;
    var container = document.getElementById('crop-editor-' + btn.dataset.cropEditorClose);
    if (container) container.remove();
  });
```

With:

```javascript
  // Close button: data-crop-editor-close="<ef-id>" clears the modal root.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-crop-editor-close]');
    if (!btn) return;
    var root = document.getElementById('crop-editor-modal-root');
    if (root) {
      root.innerHTML = '';
      delete root.dataset.preselectCrop;
    }
    document.body.classList.remove('overflow-hidden');
  });
```

- [ ] **Step 3: Update the htmx:afterSettle initializer to consume preselectCrop**

Find the existing block (currently at lines 12-17):

```javascript
  // Activate any crop editor containers swapped in by HTMX
  document.addEventListener('htmx:afterSettle', function () {
    document.querySelectorAll('[data-init="crop-editor"]:not([data-ready])').forEach(function (container) {
      container.dataset.ready = '1';
      initCropEditor(container);
    });
  });
```

Replace with:

```javascript
  // Activate any crop editor containers swapped in by HTMX
  document.addEventListener('htmx:afterSettle', function () {
    document.querySelectorAll('[data-init="crop-editor"]:not([data-ready])').forEach(function (container) {
      container.dataset.ready = '1';
      initCropEditor(container);
      // Consume preselect attribute if set by the trigger (Items tab button or deep-link).
      var root = document.getElementById('crop-editor-modal-root');
      if (root && root.dataset.preselectCrop) {
        var efId = container.dataset.efId;
        var fnName = 'ceSelect_' + efId.replace(/-/g, '_');
        var sel = window[fnName];
        if (typeof sel === 'function') {
          sel(root.dataset.preselectCrop);
        }
        delete root.dataset.preselectCrop;
      }
    });
  });
```

Notes:
- `ceSelect_<ef_id>` is an existing function exposed by `initCropEditor` (see `crop-editor.js` — search for `ceSelect`). It accepts a crop id and updates the canvas selection. We're now calling it inline at init time, which removes the need for the old DOMContentLoaded polling pattern from app.js.

- [ ] **Step 4: Verify `ceSelect_*` exists**

Run: `grep -n "ceSelect" src/cvp/static/crop-editor.js`
Expected: at least one line that defines or assigns `window['ceSelect_' + ...]` or similar. If the function is named differently in this codebase, update the `fnName` line in Step 3 to match.

If `ceSelect_*` is **not** defined anywhere, the deep-link preselect previously did not work either — note this and skip the preselect call (just leave the consumption attribute deletion). Open a question in the PR description.

- [ ] **Step 5: Smoke-check**

Run `uv run dev`. Open a matter, click **Edit crops** — modal opens. Click ✕ — modal closes. Press Esc on a new open — modal closes. Body scroll is locked while open, restored on close. Stop the dev server.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/static/crop-editor.js
git commit -m "feat: clear modal root on close and consume preselectCrop after init"
```

---

### Task 7: Convert Items tab "Edit crop" anchor to a button in _item_row.html

**Files:**
- Modify: `src/cvp/templates/_item_row.html:14-22`

- [ ] **Step 1: Read the current markup**

Run: `sed -n '8,27p' src/cvp/templates/_item_row.html`
Expected: see the `<a href="/matters/.../?file=...&crop=...#evidence" target="_blank">Edit crop</a>` inside a `<div class="relative group/thumb ...">` wrapping the thumbnail image.

- [ ] **Step 2: Replace the anchor with a button**

Replace:

```jinja
      <a href="/matters/{{ item.matter_id }}?file={{ item.crops[0].evidence_file_id }}&crop={{ item.crops[0].id }}#evidence"
         target="_blank"
         rel="noopener"
         aria-label="Edit crop for {{ item.description }}"
         class="absolute inset-x-0 bottom-0 flex items-center justify-center py-1
                bg-black/50 opacity-0 group-hover/thumb:opacity-100
                transition-opacity rounded-b text-white text-xs font-medium">
        Edit crop
      </a>
```

With:

```jinja
      <button type="button"
              data-toggle-crop-editor="{{ item.crops[0].evidence_file_id }}"
              data-preselect-crop="{{ item.crops[0].id }}"
              aria-label="Edit crop for {{ item.description }}"
              class="absolute inset-x-0 bottom-0 flex items-center justify-center py-1
                     bg-black/50 opacity-0 group-hover/thumb:opacity-100
                     transition-opacity rounded-b text-white text-xs font-medium border-0 cursor-pointer">
        Edit crop
      </button>
```

Notes:
- `border-0 cursor-pointer` overrides default browser button styling so the visual matches the previous anchor.
- No `target="_blank"`, no `rel`, no `href` — this is an in-page action now.

- [ ] **Step 3: Smoke-check**

Run `uv run dev`. Open a matter with items that have crops. Switch to the **Items** tab. Hover over a thumbnail — the "Edit crop" overlay appears (same hover styling). Click it. Expected: modal opens **on the Items tab** (no tab switch), the named crop is preselected in the editor sidebar/canvas. Close via ✕ or Esc — the Items table is at the same scroll position. Stop the dev server.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/templates/_item_row.html
git commit -m "feat: items tab Edit crop opens modal in-place instead of new tab"
```

---

### Task 8: Add integration test asserting modal shell + inner editor markup

**Files:**
- Create: `tests/test_crop_editor_modal.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crop_editor_modal.py` with the following content. The fixtures mirror the existing pattern in `tests/test_crops_router.py`:

```python
"""Integration test for the crop-editor route's modal markup."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cvp.dependencies as deps
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import Base, Category, EvidenceFile, Item, ItemCrop, Matter


@pytest.fixture(scope="module")
def tmp_base(tmp_path_factory):
    base = tmp_path_factory.mktemp("crop_editor_modal")
    (base / "uploads" / "ef1").mkdir(parents=True)
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    img.save(base / "uploads" / "ef1" / "photo.jpg", "JPEG")
    return base


@pytest.fixture(scope="module")
def db_engine(tmp_base):
    engine = create_engine(
        f"sqlite:///{tmp_base}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(Category(id=1, name="Test", useful_life_years=10, acv_floor_pct=0.20))
    db.add(Matter(id="m1", policyholder_name="Test"))
    db.add(
        EvidenceFile(
            id="ef1",
            matter_id="m1",
            filename="photo.jpg",
            stored_path="ef1/photo.jpg",
            kind="image",
            scanned=True,
        )
    )
    db.add(Item(id="item1", matter_id="m1", category_id=1, line_number=1, description="Lamp"))
    db.add(
        ItemCrop(
            id="crop1",
            item_id="item1",
            evidence_file_id="ef1",
            bbox_left=10,
            bbox_upper=10,
            bbox_right=90,
            bbox_lower=90,
            crop_path="ef1/crop1.jpg",
        )
    )
    db.commit()
    db.close()
    return engine


@pytest.fixture(scope="module")
def client(tmp_base, db_engine):
    import cvp.routers.crops as crops_mod

    Session = sessionmaker(bind=db_engine)
    app = FastAPI()
    app.include_router(crops_mod.router)

    async def mock_user() -> CurrentUser:
        return CurrentUser(
            id="test-user",
            email="test@test.com",
            system_role="system_admin",
            group_id="g1",
            group_kind="internal",
        )

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_active_user] = mock_user
    app.dependency_overrides[get_db] = override_get_db

    with (
        patch.object(crops_mod, "SessionLocal", Session),
        patch("cvp.config.settings.upload_dir", str(tmp_base / "uploads")),
        patch("cvp.config.settings.crop_dir", str(tmp_base / "crops")),
        patch.object(deps, "_check_matter_access", return_value=True),
    ):
        with TestClient(app) as c:
            yield c


def test_crop_editor_response_includes_modal_shell_and_inner_editor(client):
    resp = client.get("/api/evidence/ef1/crop-editor")
    assert resp.status_code == 200
    body = resp.text
    # Modal shell classes (backdrop)
    assert "fixed inset-0 z-50 bg-black/50" in body
    # Dialog card
    assert "max-w-5xl" in body
    assert "max-h-[90vh]" in body
    # Inner editor container that crop-editor.js initializes
    assert 'data-init="crop-editor"' in body
    assert 'id="crop-editor-ef1"' in body
    # Close button still present
    assert 'data-crop-editor-close="ef1"' in body
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/test_crop_editor_modal.py -v`
Expected: PASS. (Task 2 already added the modal shell to the partial; this test confirms the route response contains it.)

If it fails because the partial template wasn't actually updated, go back to Task 2 and confirm `_crop_editor.html` matches the spec.

- [ ] **Step 3: Commit**

```bash
git add tests/test_crop_editor_modal.py
git commit -m "test: assert crop editor route returns modal shell + inner editor markup"
```

---

### Task 9: Final lint, format, full test run, and manual verification

**Files:** none modified in this task — verification only.

- [ ] **Step 1: Run ruff format**

Per CLAUDE.md: ruff format runs before every commit.

Run: `uv run ruff format .`
Then: `uv run ruff format --check .`
Expected: `--check` reports zero files would be reformatted. If any file is reformatted by the first command, stage and amend the **last task's commit** that touched that file, or create a small follow-up commit:

```bash
git add -u && git commit -m "style: ruff format"
```

- [ ] **Step 2: Run ruff lint**

Run: `uv run ruff check .`
Expected: no errors. Fix any new lint warnings introduced by Task 8 before continuing.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest`
Expected: all tests pass. If `test_crops_router.py` tests fail because they had hard-coded assertions on the old outer markup of `_crop_editor.html`, update those assertions to match the new shell. (None expected — that file's tests are on `/adjust-bbox`, `/clear-bbox`, `/recrop`, not on the editor partial markup.)

- [ ] **Step 4: Manual smoke checklist via dev server**

Run `uv run dev` in another shell. For each case below, observe the described behavior:

  - [ ] Open a matter with at least one scanned evidence image and at least one item-with-crop. Switch to **Evidence** tab. Scroll the grid until at least one image is below the fold. Click **Edit crops** on a card. Modal opens centered with backdrop. Image and boxes render. Press Esc — modal closes. Grid scroll position is the same as before.
  - [ ] Same setup. Click **Edit crops**. Click ✕. Modal closes. Body scroll behind is no longer locked (try scrolling).
  - [ ] Switch to **Items** tab. Scroll the items table. Hover a thumbnail — "Edit crop" overlay appears. Click it. Modal opens **on the Items tab** (URL hash is still `#items`). Correct crop is preselected in the sidebar. Close via ✕ — Items tab scroll/sort/filter preserved.
  - [ ] In a fresh browser tab, visit `/matters/<id>?file=<ef_id>&crop=<crop_id>#evidence` for a known image + crop. Page loads on Evidence tab; modal auto-opens with the correct crop preselected.
  - [ ] Open the modal, then while it's open click **Edit crops** on another grid card via keyboard navigation (Tab to it + Enter, since the backdrop blocks pointer events). The second open is a no-op (re-entrancy guard).
  - [ ] In the modal, edit a crop box, click **Re-crop adjusted items** — request succeeds and existing flow refreshes the grid behind the modal as it did before.
  - [ ] Resize the browser window to ~400px wide and ~600px tall. Open the modal on a tall image. Dialog scrolls internally; layout does not break.

Stop the dev server.

- [ ] **Step 5: Final commit (if any cleanup was needed in Step 1/2)**

If no further changes, this task ends with verification only. Otherwise:

```bash
git add -u
git commit -m "chore: lint/format cleanup post-implementation"
```

---

## Done criteria

- All tasks above are checked off.
- `uv run pytest` is green.
- `uv run ruff format --check .` and `uv run ruff check .` are clean.
- Manual checklist in Task 9 Step 4 passes.
- The seven manual cases in Task 9 Step 4 are reproducible in a fresh clone after a clean `uv sync`.
