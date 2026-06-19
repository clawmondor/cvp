# Region Rescan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a specialist draw a box over a region the vision scan missed and scan just that sub-region, creating new draft items positioned correctly on the full evidence image.

**Architecture:** Reuse the existing async vision pipeline. A region scan is a one-image `VisionJob` whose `VisionJobImage` carries four nullable region-bbox columns. The worker, when those columns are set, crops the original image to the region, sends the crop to the vision model as a standalone image, then translates returned bounding boxes back into original-image coordinates (scale-up from any downscale, then offset by the region origin). The crop editor gains a "draw region → scan" mode; JS polls a JSON status endpoint and reloads the editor when the scan finishes so new item boxes appear.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x + Alembic, Pillow, vanilla JS canvas + HTMX, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-06-18-region-rescan-design.md`

---

## File Structure

- **Modify** `src/cvp/models.py` — add 4 region columns + `region_bbox` property to `VisionJobImage`.
- **Create** `migrations/versions/<rev>_vision_job_image_region.py` — additive migration.
- **Modify** `src/cvp/services/vision.py` — region-aware branch in `process_one_image`.
- **Modify** `src/cvp/routers/vision.py` — `POST /api/evidence/{file_id}/region-scan` + `GET /api/matters/{matter_id}/vision-scan/{job_id}/status`.
- **Modify** `src/cvp/templates/_crop_editor.html` — draw/scan controls.
- **Modify** `src/cvp/static/crop-editor.js` — draw-region mode, scan trigger, poll, reload.
- **Tests** `tests/test_vision_service.py`, `tests/test_vision_router.py`, `tests/test_item_groups_model.py`-style model test in `tests/test_vision_worker.py`.

Each task ends green (tests pass, `ruff format` + `ruff check` clean) and is committed.

---

## Task 1: Region columns on VisionJobImage

**Files:**
- Modify: `src/cvp/models.py:272-296` (the `VisionJobImage` class)
- Create: `migrations/versions/<rev>_vision_job_image_region.py`
- Test: `tests/test_vision_worker.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/test_vision_worker.py`:

```python
def test_region_bbox_property():
    from cvp.models import VisionJobImage

    none_set = VisionJobImage(job_id="j", evidence_file_id="ef1")
    assert none_set.region_bbox is None

    all_set = VisionJobImage(
        job_id="j",
        evidence_file_id="ef1",
        region_left=10,
        region_upper=20,
        region_right=110,
        region_lower=120,
    )
    assert all_set.region_bbox == (10, 20, 110, 120)

    partial = VisionJobImage(job_id="j", evidence_file_id="ef1", region_left=10)
    assert partial.region_bbox is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vision_worker.py::test_region_bbox_property -v`
Expected: FAIL — `TypeError: 'region_left' is an invalid keyword argument` (column doesn't exist yet).

- [ ] **Step 3: Add the columns + property**

In `src/cvp/models.py`, inside `class VisionJobImage`, add these columns immediately after the `items_created` column (around line 291):

```python
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    # Region rescan: when all four are set, the worker scans only this
    # sub-rectangle of the evidence image (original-image pixel coords).
    region_left: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_upper: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_right: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_lower: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Then add this property to the same class, just before the `job` relationship (around line 296):

```python
    @property
    def region_bbox(self) -> tuple[int, int, int, int] | None:
        vals = (self.region_left, self.region_upper, self.region_right, self.region_lower)
        if all(v is not None for v in vals):
            return (
                self.region_left,
                self.region_upper,
                self.region_right,
                self.region_lower,
            )
        return None

    job: Mapped["VisionJob"] = relationship("VisionJob", back_populates="images")
```

(Keep the existing `job` relationship line — shown here for placement only.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vision_worker.py::test_region_bbox_property -v`
Expected: PASS.

- [ ] **Step 5: Generate the migration**

Run: `uv run alembic revision --autogenerate -m "vision_job_image region columns"`

Open the new file in `migrations/versions/`. Confirm `upgrade()` contains exactly four `op.add_column('vision_job_images', sa.Column('region_*', sa.Integer(), nullable=True))` calls and `downgrade()` drops them. Remove any unrelated auto-generated noise (e.g., spurious index/type changes the autogenerate picked up) so the migration only touches these four columns. Expected `upgrade()`:

```python
def upgrade() -> None:
    op.add_column('vision_job_images', sa.Column('region_left', sa.Integer(), nullable=True))
    op.add_column('vision_job_images', sa.Column('region_upper', sa.Integer(), nullable=True))
    op.add_column('vision_job_images', sa.Column('region_right', sa.Integer(), nullable=True))
    op.add_column('vision_job_images', sa.Column('region_lower', sa.Integer(), nullable=True))
```

- [ ] **Step 6: Apply and verify the migration round-trips**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: no errors; ends at head.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/cvp/models.py migrations/versions/ tests/test_vision_worker.py
git commit -m "feat: region columns on VisionJobImage

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Region-aware worker

**Files:**
- Modify: `src/cvp/services/vision.py:253-259` (skip guard), `:287-298` (image load), `:362-372` (bbox scale)
- Test: `tests/test_vision_service.py`

- [ ] **Step 1: Write the failing test**

Add to the end of `tests/test_vision_service.py`:

```python
def test_process_one_image_region_scan_offsets_bbox(isolated_db, monkeypatch, tmp_path):
    """A region scan crops the original image, scans it, and offsets returned
    bboxes back into original-image coords. It must run even when the file is
    already marked scanned."""
    from PIL import Image

    img_path = tmp_path / "big.jpg"
    Image.new("RGB", (400, 400), color="white").save(img_path)

    matter = Matter(policyholder_name="Owner", loss_type="total_loss")
    isolated_db.add(matter)
    isolated_db.flush()

    ef = EvidenceFile(
        matter_id=matter.id,
        filename="big.jpg",
        stored_path=str(img_path),
        mime_type="image/jpeg",
        kind="image",
        size_bytes=img_path.stat().st_size,
        scanned=True,  # region scans bypass the already-scanned skip guard
    )
    isolated_db.add(ef)
    isolated_db.flush()

    job = VisionJob(matter_id=matter.id, model_slug="anthropic/claude-opus-4", status="running")
    isolated_db.add(job)
    isolated_db.flush()
    ji = VisionJobImage(
        job_id=job.id,
        evidence_file_id=ef.id,
        status="running",
        region_left=100,
        region_upper=100,
        region_right=300,
        region_lower=300,
    )
    isolated_db.add(ji)
    isolated_db.commit()
    ji_id = ji.id

    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    # bbox spans the full 200x200 crop; pixel_passthrough's 15% padding clamps
    # back to the crop bounds, so after the region offset the crop lands exactly
    # on (100, 100, 300, 300) in original-image coords.
    fake_response = json.dumps(
        [
            {
                "description": "Floor lamp",
                "category_hint": "Miscellaneous household goods",
                "quantity": 1,
                "condition": "average",
                "bounding_box": [0, 0, 200, 200],
            }
        ]
    )

    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response) as mock_call:
        vision_svc.process_one_image(ji_id)
        mock_call.assert_called_once()

    items = isolated_db.query(Item).filter_by(matter_id=matter.id).all()
    assert len(items) == 1
    crop = isolated_db.query(ItemCrop).filter_by(item_id=items[0].id).one()
    assert (crop.bbox_left, crop.bbox_upper, crop.bbox_right, crop.bbox_lower) == (
        100,
        100,
        300,
        300,
    )

    isolated_db.expire_all()
    ji = isolated_db.get(VisionJobImage, ji_id)
    assert ji.status == "done"
    assert ji.items_created == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vision_service.py::test_process_one_image_region_scan_offsets_bbox -v`
Expected: FAIL — the file is `scanned=True`, so the current guard marks the image `done` and creates no items (assertion `len(items) == 1` fails).

- [ ] **Step 3a: Relax the skip guard for region images**

In `src/cvp/services/vision.py`, replace the restart-recovery guard (currently lines 253-259):

```python
        # Restart recovery: already successfully scanned in a prior run.
        if ef.scanned:
```

with:

```python
        # Restart recovery: a whole-image scan that already succeeded is skipped.
        # Region rescans run even when the file is already marked scanned —
        # their idempotency comes from the claimed VisionJobImage status.
        if ef.scanned and job_image.region_bbox is None:
```

- [ ] **Step 3b: Crop to the region before scanning**

Replace the image-load + downscale block (currently lines 287-298):

```python
        with Image.open(image_path) as img:
            orig_w, orig_h = img.size

        mime = ef.mime_type or "image/jpeg"
        image_bytes = image_path.read_bytes()

        # Downscale only if >1 MB.
        scan_w, scan_h = orig_w, orig_h
        if len(image_bytes) > 1_000_000:
            image_bytes, mime = _downscale(image_bytes)
            with Image.open(io.BytesIO(image_bytes)) as small:
                scan_w, scan_h = small.size
```

with:

```python
        # `base_*` is the coordinate space the model sees before any downscale:
        # the full image for a whole-image scan, or the region crop for a region
        # scan. `offset_*` shifts region-relative coords back into the original.
        region = job_image.region_bbox
        with Image.open(image_path) as img:
            orig_w, orig_h = img.size
            if region is not None:
                region_img = img.crop(region).convert("RGB")
                buf = io.BytesIO()
                region_img.save(buf, "JPEG", quality=90)
                image_bytes = buf.getvalue()
                mime = "image/jpeg"
                base_w, base_h = region[2] - region[0], region[3] - region[1]
                offset_x, offset_y = region[0], region[1]
            else:
                image_bytes = image_path.read_bytes()
                mime = ef.mime_type or "image/jpeg"
                base_w, base_h = orig_w, orig_h
                offset_x, offset_y = 0, 0

        # Downscale only if >1 MB.
        scan_w, scan_h = base_w, base_h
        if len(image_bytes) > 1_000_000:
            image_bytes, mime = _downscale(image_bytes)
            with Image.open(io.BytesIO(image_bytes)) as small:
                scan_w, scan_h = small.size
```

- [ ] **Step 3c: Scale back to base coords, then offset into the original**

Replace the bbox scale block (currently lines 362-372):

```python
            # Scale bbox from downscaled coords back to original image coords.
            bbox = adapter_fn(raw_item.get("bounding_box"), scan_w, scan_h)
            if bbox is not None:
                left, upper, right, lower = bbox
                if scan_w != orig_w:
                    sx = orig_w / scan_w
                    sy = orig_h / scan_h
                    left = round(left * sx)
                    upper = round(upper * sy)
                    right = round(right * sx)
                    lower = round(lower * sy)
```

with:

```python
            # Scale bbox from downscaled coords back to the scanned image's
            # coordinate space, then offset into the original (region scans).
            bbox = adapter_fn(raw_item.get("bounding_box"), scan_w, scan_h)
            if bbox is not None:
                left, upper, right, lower = bbox
                if scan_w != base_w:
                    sx = base_w / scan_w
                    sy = base_h / scan_h
                    left = round(left * sx)
                    upper = round(upper * sy)
                    right = round(right * sx)
                    lower = round(lower * sy)
                left += offset_x
                right += offset_x
                upper += offset_y
                lower += offset_y
```

(The following `item_crop = ItemCrop(...)` block is unchanged.)

- [ ] **Step 4: Run the region test + the full vision service suite**

Run: `uv run pytest tests/test_vision_service.py -v`
Expected: the new test PASSES and all existing tests still PASS (whole-image path is behavior-preserving: `offset` is 0 and `base_*` equals `orig_*`).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/cvp/services/vision.py tests/test_vision_service.py
git commit -m "feat: region-aware vision scan in worker

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Region-scan + status endpoints

**Files:**
- Modify: `src/cvp/routers/vision.py` (imports + two new routes)
- Test: `tests/test_vision_router.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_vision_router.py`. First extend the dep-override list near the top (after line 36) and in the `client_contributor` fixture:

```python
_region_scan_dep = _dep(vision_router.region_scan)
_poll_status_dep = _dep(vision_router.poll_scan_status)
```

In `client_contributor`, add before `with TestClient(app) as c:`:

```python
    app.dependency_overrides[_region_scan_dep] = mock_contributor
    app.dependency_overrides[_poll_status_dep] = mock_contributor
```

Then add these tests at the end of the file:

```python
def test_region_scan_creates_job_with_region(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.services.vision_worker.wake", lambda: None)

    db_session.query(User).filter_by(id=CONTRIBUTOR_ID).update(
        {"last_vision_model_slug": "anthropic/claude-opus-4"}
    )
    db_session.commit()

    resp = client_contributor.post(
        f"/api/evidence/{FILE_ID}/region-scan",
        json={"left": 10, "upper": 10, "right": 110, "lower": 110},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matter_id"] == MATTER_ID
    job_id = body["job_id"]

    images = db_session.query(VisionJobImage).filter_by(job_id=job_id).all()
    assert len(images) == 1
    img = images[0]
    assert (img.region_left, img.region_upper, img.region_right, img.region_lower) == (
        10,
        10,
        110,
        110,
    )


def test_region_scan_rejects_out_of_bounds(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    db_session.query(User).filter_by(id=CONTRIBUTOR_ID).update(
        {"last_vision_model_slug": "anthropic/claude-opus-4"}
    )
    db_session.commit()
    # Image is 200x200; right=500 is out of range.
    resp = client_contributor.post(
        f"/api/evidence/{FILE_ID}/region-scan",
        json={"left": 10, "upper": 10, "right": 500, "lower": 110},
    )
    assert resp.status_code == 422


def test_region_scan_requires_last_used_model(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    # User has no last_vision_model_slug set.
    resp = client_contributor.post(
        f"/api/evidence/{FILE_ID}/region-scan",
        json={"left": 10, "upper": 10, "right": 110, "lower": 110},
    )
    assert resp.status_code == 400


def test_poll_scan_status_returns_json(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: db_session)
    job = VisionJob(matter_id=MATTER_ID, model_slug="anthropic/claude-opus-4", status="done")
    db_session.add(job)
    db_session.flush()
    db_session.add(
        VisionJobImage(job_id=job.id, evidence_file_id=FILE_ID, status="done", items_created=2)
    )
    db_session.commit()

    resp = client_contributor.get(f"/api/matters/{MATTER_ID}/vision-scan/{job.id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["items_created"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vision_router.py -k "region_scan or poll_scan_status" -v`
Expected: FAIL — `AttributeError: module 'cvp.routers.vision' has no attribute 'region_scan'` (collection error before the endpoints exist).

- [ ] **Step 3: Add imports**

In `src/cvp/routers/vision.py`, update the imports. The `fastapi.responses` import currently brings in `HTMLResponse`; add `JSONResponse`. Add `BaseModel` and `Image`, `VisionModel`, `User`, `settings`:

```python
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import EvidenceFile, VisionJob, VisionJobImage
from cvp.models_auth import User
from cvp.models_vision import VisionModel
from cvp.services import vision as vision_svc
from cvp.services import vision_worker
from cvp.services.audit import get_client_ip, write_audit_log
```

(`User`, `VisionModel`, `HTTPException`, `Form` are already imported in the existing file — keep them; this list is the full intended import block.)

- [ ] **Step 4: Add the endpoints**

Append to `src/cvp/routers/vision.py`:

```python
class RegionScanBody(BaseModel):
    left: int
    upper: int
    right: int
    lower: int


@router.post("/api/evidence/{file_id}/region-scan")
async def region_scan(
    request: Request,
    file_id: str,
    body: RegionScanBody,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> JSONResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None or ef.kind != "image":
            return JSONResponse({"error": "image not found"}, status_code=404)

        upload_base = Path(settings.upload_dir).resolve()
        with Image.open((upload_base / ef.stored_path).resolve()) as img:
            img_w, img_h = img.size

        if body.left >= body.right or body.upper >= body.lower:
            return JSONResponse(
                {"error": "left must be < right and upper must be < lower"}, status_code=422
            )
        if not (0 <= body.left <= img_w and 0 <= body.right <= img_w):
            return JSONResponse({"error": f"x out of range [0, {img_w}]"}, status_code=422)
        if not (0 <= body.upper <= img_h and 0 <= body.lower <= img_h):
            return JSONResponse({"error": f"y out of range [0, {img_h}]"}, status_code=422)

        u = db.query(User).filter_by(id=user.id).first()
        model_slug = u.last_vision_model_slug if u else None
        if not model_slug:
            return JSONResponse(
                {"error": "No model selected yet — run a full scan first to choose one."},
                status_code=400,
            )
        vm = db.query(VisionModel).filter_by(slug=model_slug, is_enabled=True).first()
        if vm is None:
            return JSONResponse(
                {"error": f"Last-used model unavailable: {model_slug}"}, status_code=400
            )

        matter_id = ef.matter_id
        job = VisionJob(
            matter_id=matter_id,
            model_slug=model_slug,
            status="running",
            created_by_user_id=user.id,
        )
        db.add(job)
        db.flush()
        db.add(
            VisionJobImage(
                job_id=job.id,
                evidence_file_id=ef.id,
                region_left=body.left,
                region_upper=body.upper,
                region_right=body.right,
                region_lower=body.lower,
            )
        )
        db.commit()
        job_id = job.id
    finally:
        db.close()

    vision_worker.wake()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="vision.region",
        resource_type="evidence_file",
        resource_id=file_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
        detail={"model": model_slug, "region": [body.left, body.upper, body.right, body.lower]},
    )
    return JSONResponse({"job_id": job_id, "matter_id": matter_id})


@router.get("/api/matters/{matter_id}/vision-scan/{job_id}/status")
def poll_scan_status(
    matter_id: str,
    job_id: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> JSONResponse:
    return JSONResponse(vision_svc.get_job_data(job_id))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_vision_router.py -v`
Expected: all PASS (new and existing).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff format --check . && uv run ruff check .
git add src/cvp/routers/vision.py tests/test_vision_router.py
git commit -m "feat: region-scan and status endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Crop editor draw-region UI

No JS unit tests exist in this repo; this task is implementation + manual verification. All interactivity uses `addEventListener` in `crop-editor.js` (a static JS file, CSP-safe) and `data-*` attributes — never inline `on*` handlers.

**Files:**
- Modify: `src/cvp/templates/_crop_editor.html`
- Modify: `src/cvp/static/crop-editor.js`

- [ ] **Step 1: Add the draw/scan controls to the template**

In `src/cvp/templates/_crop_editor.html`, inside the sidebar's `<div class="mt-auto pt-2 border-t border-gray-100">` block, immediately after the existing `<p id="ce-status-...">` line and before the closing `</div>`, add:

```html
            <div class="mt-3 pt-2 border-t border-gray-100">
              <button id="ce-draw-toggle-{{ evidence_file.id }}"
                      data-ce-draw-toggle="{{ evidence_file.id }}"
                      class="w-full rounded border border-emerald-500 px-3 py-1.5 text-sm font-semibold text-emerald-700 hover:bg-emerald-50">
                Draw scan region
              </button>
              <button id="ce-scan-region-btn-{{ evidence_file.id }}"
                      disabled
                      class="mt-1 w-full rounded bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed">
                Scan this region
              </button>
              <p id="ce-region-status-{{ evidence_file.id }}" class="mt-1 text-xs text-gray-400"></p>
            </div>
```

- [ ] **Step 2: Add draw-mode state + button refs in crop-editor.js**

In `src/cvp/static/crop-editor.js`, inside `initCropEditor`, after the line `var statusEl = document.getElementById('ce-status-' + EF_ID);` (~line 52), add:

```javascript
    var drawToggleBtn = document.getElementById('ce-draw-toggle-' + EF_ID);
    var scanRegionBtn = document.getElementById('ce-scan-region-btn-' + EF_ID);
    var regionStatusEl = document.getElementById('ce-region-status-' + EF_ID);
    var drawMode = false;
    var pendingRegion = null;
```

- [ ] **Step 3: Render the pending region in draw()**

In the `draw()` function, just before its closing `}` (after the `boxes.forEach(...)` block, ~line 130), add:

```javascript
      if (pendingRegion) {
        var pl = tc(pendingRegion.left), pu = tc(pendingRegion.upper);
        var pw = tc(pendingRegion.right) - pl, ph = tc(pendingRegion.lower) - pu;
        ctx.fillStyle = 'rgba(16,185,129,0.15)';
        ctx.fillRect(pl, pu, pw, ph);
        ctx.strokeStyle = '#10b981';
        ctx.setLineDash([6, 3]);
        ctx.lineWidth = 2;
        ctx.strokeRect(pl, pu, pw, ph);
        ctx.setLineDash([]);
      }
```

- [ ] **Step 4: Handle draw-mode in mousedown**

Replace the `canvas.addEventListener('mousedown', ...)` handler (~lines 144-164) with:

```javascript
    canvas.addEventListener('mousedown', function (e) {
      var rect = canvas.getBoundingClientRect();
      var cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      if (drawMode) {
        drag = {type: 'region', startX: cx, startY: cy};
        selectedIdx = null;
        pendingRegion = null;
        scanRegionBtn.disabled = true;
        return;
      }
      if (selectedIdx !== null) {
        var hi = hitHandle(boxes[selectedIdx], cx, cy);
        if (hi >= 0) {
          drag = {type: 'handle', handleIdx: hi, startX: cx, startY: cy, origBox: Object.assign({}, boxes[selectedIdx])};
          return;
        }
      }
      for (var i = boxes.length - 1; i >= 0; i--) {
        if (hitBox(boxes[i], cx, cy)) {
          selectedIdx = i;
          drag = {type: 'move', startX: cx, startY: cy, origBox: Object.assign({}, boxes[i])};
          draw();
          updateSidebar();
          return;
        }
      }
      selectedIdx = null; drag = null; draw(); updateSidebar();
    });
```

- [ ] **Step 5: Handle region drag in mousemove**

In the `canvas.addEventListener('mousemove', ...)` handler, immediately after the `var dx = ...; var dy = ...;` lines are computed — actually insert the region branch *before* them, right after `var cx = e.clientX - rect.left, cy = e.clientY - rect.top;` (~line 169):

```javascript
      if (drag.type === 'region') {
        var rl = fc(Math.min(drag.startX, cx)), ru = fc(Math.min(drag.startY, cy));
        var rr = fc(Math.max(drag.startX, cx)), rlo = fc(Math.max(drag.startY, cy));
        pendingRegion = {
          left: Math.max(0, Math.min(IMG_W, rl)),
          upper: Math.max(0, Math.min(IMG_H, ru)),
          right: Math.max(0, Math.min(IMG_W, rr)),
          lower: Math.max(0, Math.min(IMG_H, rlo)),
        };
        draw();
        return;
      }
```

- [ ] **Step 6: Finalize region in mouseup**

Replace the `canvas.addEventListener('mouseup', ...)` handler (~lines 190-194) with:

```javascript
    canvas.addEventListener('mouseup', function () {
      if (!drag) return;
      var wasRegion = (drag.type === 'region');
      drag = null;
      if (wasRegion) {
        var ok = pendingRegion &&
          (pendingRegion.right - pendingRegion.left) >= MIN_SIZE &&
          (pendingRegion.lower - pendingRegion.upper) >= MIN_SIZE;
        if (!ok) pendingRegion = null;
        scanRegionBtn.disabled = !ok;
        draw();
        return;
      }
      if (selectedIdx !== null) autosave(selectedIdx);
    });
```

- [ ] **Step 7: Wire the toggle + scan buttons + poll**

Just before the final `updateRecropButton(); draw();` lines at the end of `initCropEditor` (~line 336), add:

```javascript
    drawToggleBtn.addEventListener('click', function () {
      drawMode = !drawMode;
      drawToggleBtn.classList.toggle('bg-emerald-600', drawMode);
      drawToggleBtn.classList.toggle('text-white', drawMode);
      drawToggleBtn.textContent = drawMode ? 'Drawing… click + drag a box' : 'Draw scan region';
      if (!drawMode) {
        pendingRegion = null;
        scanRegionBtn.disabled = true;
        draw();
      }
    });

    function pollRegionJob(matterId, jobId) {
      var iv = setInterval(function () {
        fetch('/api/matters/' + matterId + '/vision-scan/' + jobId + '/status')
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.status === 'running') {
              regionStatusEl.textContent = 'Scanning region… ' + d.progress + '/' + d.total;
              return;
            }
            clearInterval(iv);
            regionStatusEl.textContent =
              (d.status === 'error' ? 'Finished with errors — ' : 'Done — ') +
              d.items_created + ' item(s) created.';
            if (window.htmx) {
              htmx.ajax('GET', '/api/evidence/' + EF_ID + '/crop-editor',
                {target: '#crop-editor-modal-root', swap: 'innerHTML'});
            }
          })
          .catch(function () {
            clearInterval(iv);
            regionStatusEl.textContent = 'Error polling scan — check console.';
          });
      }, 2000);
    }

    scanRegionBtn.addEventListener('click', function () {
      if (!pendingRegion) return;
      scanRegionBtn.disabled = true;
      regionStatusEl.textContent = 'Starting scan…';
      fetch('/api/evidence/' + EF_ID + '/region-scan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()},
        body: JSON.stringify(pendingRegion),
      })
        .then(function (r) { return r.json().then(function (d) { return {ok: r.ok, d: d}; }); })
        .then(function (res) {
          if (!res.ok) {
            regionStatusEl.textContent = res.d.error || 'Error starting scan.';
            scanRegionBtn.disabled = false;
            return;
          }
          pollRegionJob(res.d.matter_id, res.d.job_id);
        })
        .catch(function () {
          regionStatusEl.textContent = 'Error — check console.';
          scanRegionBtn.disabled = false;
        });
    });
```

- [ ] **Step 8: Manual verification**

Run: `uv run dev` (in a background shell), then in the browser:
1. Open a matter, go to the **Evidence** tab, click **Edit crops** on a scanned image.
2. Click **Draw scan region**; click-and-drag a box over a region with an undetected item. Confirm a dashed green box appears and **Scan this region** enables.
3. Click **Scan this region**. Confirm the status shows "Scanning region…", then "Done — N item(s) created", and the editor reloads with new item box(es) drawn.
4. Switch to the **Items** tab and confirm the new draft item(s) appear (unconfirmed, RCV 0).
5. Confirm existing crop adjust/recrop still works (regression check).

Expected: all steps behave as described; no CSP errors in the browser console.

- [ ] **Step 9: Commit**

```bash
git add src/cvp/templates/_crop_editor.html src/cvp/static/crop-editor.js
git commit -m "feat: draw-region scan in crop editor

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification

- [ ] **Step 1: Run the entire test suite + lint**

Run: `uv run pytest && uv run ruff format --check . && uv run ruff check .`
Expected: all tests PASS; format check reports zero files to reformat; lint clean.

- [ ] **Step 2: Confirm migration is current**

Run: `uv run alembic upgrade head`
Expected: no pending migrations / "already at head".

If anything fails, fix before considering the feature complete. No commit needed if Tasks 1-4 already committed and this step is green.

---

## Self-Review Notes

- **Spec coverage:** data model (Task 1), worker region branch + skip-guard fix + coord translation (Task 2), `region-scan` endpoint + last-used model + bbox validation + audit (Task 3), status endpoint for in-modal polling (Task 3), crop-editor draw/scan/redraw UI (Task 4). Item-group inheritance and `VisionRun` audit row are unchanged worker code, exercised by the existing pipeline. All spec sections map to a task.
- **Out of scope (per spec):** batched multi-region, per-scan model picker, re-running a region — not implemented.
- **Type consistency:** `region_bbox` returns `tuple[int,int,int,int] | None`; worker reads it once into `region`; endpoint writes the four columns directly; JS `pendingRegion` keys (`left/upper/right/lower`) match `RegionScanBody` fields.
