# Crop Adjustment Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow specialists to drag-resize item crop bounding boxes on the Evidence tab, then re-generate JPEG crops from the adjusted coordinates.

**Architecture:** Four `adjusted_bbox_*` nullable columns on `ItemCrop` + `effective_bbox` property; a `recrop_item_crop` service function extracted from `vision.py`; four API endpoints in a new `crops` router; a canvas-based editor partial loaded via HTMX into the Evidence tab.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), Pillow (image crop), HTMX + vanilla JS canvas (frontend), Alembic (migration), pytest (tests)

---

### Task 1: Data model — add adjusted_bbox_* columns and effective_bbox property

**Files:**
- Modify: `src/cvp/models.py` (`ItemCrop` class, after line 217)
- Create: `tests/test_item_crop_bbox.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_item_crop_bbox.py
"""Unit tests for ItemCrop.effective_bbox property."""
from cvp.models import ItemCrop


def _make_crop(**kwargs) -> ItemCrop:
    defaults = dict(
        id="crop-1",
        item_id="item-1",
        evidence_file_id="ef-1",
        bbox_left=10,
        bbox_upper=20,
        bbox_right=100,
        bbox_lower=200,
        crop_path="ef-1/crop-1.jpg",
        adjusted_bbox_left=None,
        adjusted_bbox_upper=None,
        adjusted_bbox_right=None,
        adjusted_bbox_lower=None,
    )
    defaults.update(kwargs)
    crop = ItemCrop.__new__(ItemCrop)
    crop.__dict__.update(defaults)
    return crop


def test_effective_bbox_returns_claude_bbox_when_no_adjustment():
    crop = _make_crop()
    assert crop.effective_bbox == (10, 20, 100, 200)


def test_effective_bbox_returns_adjusted_when_all_four_set():
    crop = _make_crop(
        adjusted_bbox_left=5,
        adjusted_bbox_upper=15,
        adjusted_bbox_right=95,
        adjusted_bbox_lower=195,
    )
    assert crop.effective_bbox == (5, 15, 95, 195)


def test_effective_bbox_falls_back_if_any_adjusted_is_none():
    crop = _make_crop(
        adjusted_bbox_left=5,
        adjusted_bbox_upper=None,
        adjusted_bbox_right=95,
        adjusted_bbox_lower=195,
    )
    assert crop.effective_bbox == (10, 20, 100, 200)


def test_effective_bbox_treats_zero_as_valid():
    """Zero is a valid pixel coordinate, not 'unset'."""
    crop = _make_crop(
        adjusted_bbox_left=0,
        adjusted_bbox_upper=0,
        adjusted_bbox_right=50,
        adjusted_bbox_lower=50,
    )
    assert crop.effective_bbox == (0, 0, 50, 50)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/cmondor/consulting/tor
source .venv/bin/activate && uv run pytest tests/test_item_crop_bbox.py -v
```

Expected: `AttributeError` — `ItemCrop` has no attribute `adjusted_bbox_left`

- [ ] **Step 3: Add columns and property to ItemCrop in models.py**

In `src/cvp/models.py`, replace:

```python
    bbox_lower: Mapped[int] = mapped_column(Integer, default=0)
    crop_path: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

With:

```python
    bbox_lower: Mapped[int] = mapped_column(Integer, default=0)
    adjusted_bbox_left: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_bbox_upper: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_bbox_right: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_bbox_lower: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crop_path: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def effective_bbox(self) -> tuple[int, int, int, int]:
        if all(
            v is not None
            for v in (
                self.adjusted_bbox_left,
                self.adjusted_bbox_upper,
                self.adjusted_bbox_right,
                self.adjusted_bbox_lower,
            )
        ):
            return (
                self.adjusted_bbox_left,
                self.adjusted_bbox_upper,
                self.adjusted_bbox_right,
                self.adjusted_bbox_lower,
            )
        return (self.bbox_left, self.bbox_upper, self.bbox_right, self.bbox_lower)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_item_crop_bbox.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/cvp/models.py tests/test_item_crop_bbox.py
git commit -m "feat: add adjusted_bbox_* columns and effective_bbox property to ItemCrop"
```

---

### Task 2: Alembic migration — add adjusted_bbox_* to item_crops table

**Files:**
- Create: `migrations/versions/<timestamp>_item_crops_adjusted_bbox.py` (generated by Alembic)

- [ ] **Step 1: Generate the migration**

```bash
cd /Users/cmondor/consulting/tor
source .venv/bin/activate && uv run alembic revision --autogenerate -m "item_crops_adjusted_bbox"
```

Expected: new file created in `migrations/versions/`

- [ ] **Step 2: Open and verify the generated file**

Confirm `upgrade()` contains exactly these four `add_column` calls (nothing more):

```python
def upgrade() -> None:
    op.add_column('item_crops', sa.Column('adjusted_bbox_left', sa.Integer(), nullable=True))
    op.add_column('item_crops', sa.Column('adjusted_bbox_upper', sa.Integer(), nullable=True))
    op.add_column('item_crops', sa.Column('adjusted_bbox_right', sa.Integer(), nullable=True))
    op.add_column('item_crops', sa.Column('adjusted_bbox_lower', sa.Integer(), nullable=True))
```

And `downgrade()` drops all four. If Alembic generated anything extra, delete those lines.

- [ ] **Step 3: Apply the migration**

```bash
uv run alembic upgrade head
```

Expected: no error; output ends with `Running upgrade cf42abfe3ff8 -> <new_rev>`

- [ ] **Step 4: Smoke-check the schema**

```bash
source .venv/bin/activate && python -c "
from cvp.models import ItemCrop
cols = [c.name for c in ItemCrop.__table__.columns]
assert 'adjusted_bbox_left' in cols, cols
print('OK:', [c for c in cols if 'adjusted' in c])
"
```

Expected: `OK: ['adjusted_bbox_left', 'adjusted_bbox_upper', 'adjusted_bbox_right', 'adjusted_bbox_lower']`

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/
git commit -m "feat: migration — add adjusted_bbox_* columns to item_crops"
```

---

### Task 3: Crop service + refactor vision.py

**Files:**
- Create: `src/cvp/services/crop.py`
- Modify: `src/cvp/services/vision.py` (replace inline crop block with `recrop_item_crop` call)
- Create: `tests/test_crop_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_crop_service.py
"""Unit tests for recrop_item_crop service."""
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from cvp.models import EvidenceFile, ItemCrop
from cvp.services.crop import recrop_item_crop


def _make_ef(ef_id: str, stored_path: str) -> EvidenceFile:
    ef = EvidenceFile.__new__(EvidenceFile)
    ef.id = ef_id
    ef.stored_path = stored_path
    return ef


def _make_crop(crop_id: str, *, left=0, upper=0, right=50, lower=50,
               adj_left=None, adj_upper=None, adj_right=None, adj_lower=None) -> ItemCrop:
    crop = ItemCrop.__new__(ItemCrop)
    crop.id = crop_id
    crop.bbox_left = left
    crop.bbox_upper = upper
    crop.bbox_right = right
    crop.bbox_lower = lower
    crop.adjusted_bbox_left = adj_left
    crop.adjusted_bbox_upper = adj_upper
    crop.adjusted_bbox_right = adj_right
    crop.adjusted_bbox_lower = adj_lower
    return crop


@pytest.fixture
def tmp_dirs(tmp_path):
    upload = tmp_path / "uploads"
    crops = tmp_path / "crops"
    upload.mkdir()
    crops.mkdir()
    return upload, crops


def _write_image(path: Path, w: int = 200, h: int = 200) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), color=(128, 64, 32)).save(path, "JPEG")


def test_recrop_saves_jpeg_and_returns_relative_path(tmp_dirs):
    upload, crop_base = tmp_dirs
    _write_image(upload / "ef1" / "photo.jpg")

    ef = _make_ef("ef1", "ef1/photo.jpg")
    crop = _make_crop("crop1", left=10, upper=10, right=60, lower=60)

    result = recrop_item_crop(crop, ef, upload, crop_base)

    assert result == "ef1/crop1.jpg"
    assert (crop_base / "ef1" / "crop1.jpg").exists()
    assert not result.startswith("/")


def test_recrop_uses_adjusted_bbox_when_all_four_set(tmp_dirs):
    upload, crop_base = tmp_dirs
    _write_image(upload / "ef2" / "photo.jpg")

    ef = _make_ef("ef2", "ef2/photo.jpg")
    # Claude bbox is 10×10; adjusted bbox is 80×80 — output size should differ
    crop = _make_crop(
        "crop2",
        left=0, upper=0, right=10, lower=10,
        adj_left=10, adj_upper=10, adj_right=90, adj_lower=90,
    )

    recrop_item_crop(crop, ef, upload, crop_base)

    saved = Image.open(crop_base / "ef2" / "crop2.jpg")
    w, h = saved.size
    assert w > 20 and h > 20  # 80×80 adjusted bbox, not the 10×10 Claude bbox


def test_recrop_uses_claude_bbox_when_adjustment_incomplete(tmp_dirs):
    upload, crop_base = tmp_dirs
    _write_image(upload / "ef3" / "photo.jpg")

    ef = _make_ef("ef3", "ef3/photo.jpg")
    crop = _make_crop(
        "crop3",
        left=0, upper=0, right=20, lower=20,
        adj_left=50, adj_upper=None, adj_right=100, adj_lower=100,  # adj_upper is None
    )

    recrop_item_crop(crop, ef, upload, crop_base)

    saved = Image.open(crop_base / "ef3" / "crop3.jpg")
    w, h = saved.size
    assert w == 20 and h == 20  # Claude bbox used (20×20), not the 50×100 range
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_crop_service.py -v
```

Expected: `ModuleNotFoundError` — `cvp.services.crop` does not exist

- [ ] **Step 3: Create src/cvp/services/crop.py**

```python
"""Crop image service — re-crop an ItemCrop using its effective_bbox."""

from pathlib import Path

from PIL import Image

from cvp.models import EvidenceFile, ItemCrop


def recrop_item_crop(
    item_crop: ItemCrop,
    evidence_file: EvidenceFile,
    upload_base: Path,
    crop_base: Path,
) -> str:
    """
    Re-crop the item using effective_bbox (adjusted if set, else Claude's original).

    Opens the original evidence image, crops to effective_bbox, saves JPEG at quality 85
    to <crop_base>/<evidence_file.id>/<item_crop.id>.jpg.
    Returns the relative crop_path string (no leading slash).
    No additional padding is applied — coordinates are the final crop boundary.
    """
    image_path = (upload_base / evidence_file.stored_path).resolve()
    left, upper, right, lower = item_crop.effective_bbox

    crop_dir = crop_base / evidence_file.id
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_filename = f"{item_crop.id}.jpg"

    with Image.open(image_path) as img:
        cropped = img.crop((left, upper, right, lower)).convert("RGB")
        cropped.save(crop_dir / crop_filename, "JPEG", quality=85)

    return f"{evidence_file.id}/{crop_filename}"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_crop_service.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Refactor vision.py to use recrop_item_crop**

In `src/cvp/services/vision.py`:

**a)** Add the import after the existing local imports (after line 18):

```python
from cvp.services.crop import recrop_item_crop
```

**b)** Remove the now-unused `crop_dir` variable (line 201: `crop_dir = crop_base / file_id`). Delete that line entirely.

**c)** Replace the inline crop block (lines 251–269, the `# Attempt crop` block) with:

```python
                        # Attempt crop
                        bbox = _parse_bbox(raw_item.get("bounding_box"), img_width, img_height)
                        if bbox:
                            left, upper, right, lower = bbox
                            item_crop = ItemCrop(
                                item_id=item.id,
                                evidence_file_id=file_id,
                                bbox_left=left,
                                bbox_upper=upper,
                                bbox_right=right,
                                bbox_lower=lower,
                            )
                            item_crop.crop_path = recrop_item_crop(
                                item_crop, ef, upload_base, crop_base
                            )
                            db.add(item_crop)
```

Note: `item_crop.id` is generated by `_new_uuid` at construction time, so no `db.flush()` is needed before calling `recrop_item_crop`.

- [ ] **Step 6: Run lint**

```bash
uv run ruff check src/cvp/services/vision.py src/cvp/services/crop.py
```

Expected: no output. Fix any issues reported.

- [ ] **Step 7: Commit**

```bash
git add src/cvp/services/crop.py src/cvp/services/vision.py tests/test_crop_service.py
git commit -m "feat: extract recrop_item_crop service; refactor vision.py to use it"
```

---

### Task 4: Crops router + registration in main.py

**Files:**
- Create: `src/cvp/routers/crops.py`
- Modify: `src/cvp/main.py`
- Create: `tests/test_crops_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_crops_router.py
"""Integration tests for crops router."""
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cvp.models import Base, Category, EvidenceFile, Item, ItemCrop, Matter


@pytest.fixture(scope="module")
def tmp_base(tmp_path_factory):
    base = tmp_path_factory.mktemp("crops_router")
    (base / "uploads" / "ef1").mkdir(parents=True)
    (base / "crops" / "ef1").mkdir(parents=True)
    # Write a real 200×200 test image
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    img.save(base / "uploads" / "ef1" / "photo.jpg", "JPEG")
    # Write a placeholder crop file (router tests don't verify pixel content)
    img.save(base / "crops" / "ef1" / "crop1.jpg", "JPEG")
    return base


@pytest.fixture(scope="module")
def db_engine(tmp_base):
    engine = create_engine(f"sqlite:///{tmp_base}/test.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    db.add(Category(id=1, name="Test", useful_life_years=10, acv_floor_pct=0.20))
    db.add(Matter(id="m1", policyholder_name="Test"))
    db.add(EvidenceFile(
        id="ef1", matter_id="m1", filename="photo.jpg",
        stored_path="ef1/photo.jpg", kind="image", scanned=True,
    ))
    db.add(Item(id="item1", matter_id="m1", category_id=1, line_number=1, description="Lamp"))
    db.add(ItemCrop(
        id="crop1", item_id="item1", evidence_file_id="ef1",
        bbox_left=10, bbox_upper=10, bbox_right=90, bbox_lower=90,
        crop_path="ef1/crop1.jpg",
    ))
    db.commit()
    db.close()
    return engine


@pytest.fixture(scope="module")
def client(tmp_base, db_engine):
    import cvp.routers.crops as crops_mod

    Session = sessionmaker(bind=db_engine)

    app = FastAPI()
    app.include_router(crops_mod.router)

    with (
        patch.object(crops_mod, "SessionLocal", Session),
        patch("cvp.config.settings.upload_dir", str(tmp_base / "uploads")),
        patch("cvp.config.settings.crop_dir", str(tmp_base / "crops")),
    ):
        with TestClient(app) as c:
            yield c, Session


def test_adjust_bbox_stores_values(client):
    c, Session = client
    resp = c.post(
        "/api/item-crops/crop1/adjust-bbox",
        json={"left": 5, "upper": 5, "right": 80, "lower": 80},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    db = Session()
    crop = db.get(ItemCrop, "crop1")
    assert crop.adjusted_bbox_left == 5
    assert crop.adjusted_bbox_upper == 5
    assert crop.adjusted_bbox_right == 80
    assert crop.adjusted_bbox_lower == 80
    db.close()


def test_adjust_bbox_rejects_left_gte_right(client):
    c, _ = client
    resp = c.post(
        "/api/item-crops/crop1/adjust-bbox",
        json={"left": 100, "upper": 5, "right": 50, "lower": 80},
    )
    assert resp.status_code == 422


def test_adjust_bbox_rejects_out_of_bounds(client):
    c, _ = client
    resp = c.post(
        "/api/item-crops/crop1/adjust-bbox",
        json={"left": 0, "upper": 0, "right": 9999, "lower": 9999},
    )
    assert resp.status_code == 422


def test_adjust_bbox_404_for_unknown_crop(client):
    c, _ = client
    resp = c.post(
        "/api/item-crops/nonexistent/adjust-bbox",
        json={"left": 5, "upper": 5, "right": 80, "lower": 80},
    )
    assert resp.status_code == 404


def test_clear_bbox_removes_values(client):
    c, Session = client
    # Ensure values are set first
    c.post(
        "/api/item-crops/crop1/adjust-bbox",
        json={"left": 5, "upper": 5, "right": 80, "lower": 80},
    )
    resp = c.delete("/api/item-crops/crop1/adjust-bbox")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    db = Session()
    crop = db.get(ItemCrop, "crop1")
    assert crop.adjusted_bbox_left is None
    assert crop.adjusted_bbox_upper is None
    assert crop.adjusted_bbox_right is None
    assert crop.adjusted_bbox_lower is None
    db.close()


def test_recrop_regenerates_crop_file(client, tmp_base):
    c, Session = client
    # Set adjustment
    c.post(
        "/api/item-crops/crop1/adjust-bbox",
        json={"left": 20, "upper": 20, "right": 80, "lower": 80},
    )
    resp = c.post("/api/evidence/ef1/recrop")
    assert resp.status_code == 200
    data = resp.json()
    assert "crop1" in data["recropped"]
    assert (tmp_base / "crops" / "ef1" / "crop1.jpg").exists()


def test_recrop_skips_items_without_adjustment(client):
    c, _ = client
    # Clear all adjustments
    c.delete("/api/item-crops/crop1/adjust-bbox")
    resp = c.post("/api/evidence/ef1/recrop")
    assert resp.status_code == 200
    assert resp.json()["recropped"] == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_crops_router.py -v
```

Expected: `ModuleNotFoundError` — `cvp.routers.crops` does not exist

- [ ] **Step 3: Create src/cvp/routers/crops.py**

```python
"""Crop adjustment and re-crop endpoints."""

import json as _json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import EvidenceFile, ItemCrop
from cvp.services.crop import recrop_item_crop

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


class BboxBody(BaseModel):
    left: int
    upper: int
    right: int
    lower: int


@router.post("/api/item-crops/{crop_id}/adjust-bbox")
def adjust_bbox(crop_id: str, body: BboxBody) -> JSONResponse:
    db = SessionLocal()
    try:
        crop = db.get(ItemCrop, crop_id)
        if crop is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        ef = db.get(EvidenceFile, crop.evidence_file_id)
        if ef is None:
            return JSONResponse({"error": "evidence file not found"}, status_code=404)

        upload_base = Path(settings.upload_dir).resolve()
        with Image.open((upload_base / ef.stored_path).resolve()) as img:
            img_w, img_h = img.size

        if body.left >= body.right or body.upper >= body.lower:
            return JSONResponse(
                {"error": "left must be < right and upper must be < lower"}, status_code=422
            )
        if not (0 <= body.left <= img_w and 0 <= body.right <= img_w):
            return JSONResponse(
                {"error": f"x coordinates out of range [0, {img_w}]"}, status_code=422
            )
        if not (0 <= body.upper <= img_h and 0 <= body.lower <= img_h):
            return JSONResponse(
                {"error": f"y coordinates out of range [0, {img_h}]"}, status_code=422
            )

        crop.adjusted_bbox_left = body.left
        crop.adjusted_bbox_upper = body.upper
        crop.adjusted_bbox_right = body.right
        crop.adjusted_bbox_lower = body.lower
        db.commit()
    finally:
        db.close()
    return JSONResponse({"ok": True})


@router.delete("/api/item-crops/{crop_id}/adjust-bbox")
def clear_bbox(crop_id: str) -> JSONResponse:
    db = SessionLocal()
    try:
        crop = db.get(ItemCrop, crop_id)
        if crop is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        crop.adjusted_bbox_left = None
        crop.adjusted_bbox_upper = None
        crop.adjusted_bbox_right = None
        crop.adjusted_bbox_lower = None
        db.commit()
    finally:
        db.close()
    return JSONResponse({"ok": True})


@router.get("/api/evidence/{file_id}/crop-editor", response_class=HTMLResponse)
def crop_editor(request: Request, file_id: str) -> HTMLResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None:
            return HTMLResponse("Evidence file not found", status_code=404)

        crops = (
            db.query(ItemCrop)
            .filter(ItemCrop.evidence_file_id == file_id)
            .options(selectinload(ItemCrop.item))
            .all()
        )

        upload_base = Path(settings.upload_dir).resolve()
        with Image.open((upload_base / ef.stored_path).resolve()) as img:
            img_w, img_h = img.size

        crops_json = _json.dumps([
            {
                "id": c.id,
                "description": (c.item.description if c.item else None) or f"Item {i + 1}",
                "bbox": list(c.effective_bbox),
                "claude_bbox": [c.bbox_left, c.bbox_upper, c.bbox_right, c.bbox_lower],
                "adjusted": all(
                    v is not None
                    for v in (
                        c.adjusted_bbox_left,
                        c.adjusted_bbox_upper,
                        c.adjusted_bbox_right,
                        c.adjusted_bbox_lower,
                    )
                ),
            }
            for i, c in enumerate(crops)
        ])

        stored_path = ef.stored_path
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="_crop_editor.html",
        context={
            "evidence_file": ef,
            "img_w": img_w,
            "img_h": img_h,
            "crops_json": crops_json,
            "stored_path": stored_path,
        },
    )


@router.post("/api/evidence/{file_id}/recrop")
def recrop_evidence(file_id: str) -> JSONResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        crops = (
            db.query(ItemCrop)
            .filter(
                ItemCrop.evidence_file_id == file_id,
                or_(
                    ItemCrop.adjusted_bbox_left.isnot(None),
                    ItemCrop.adjusted_bbox_upper.isnot(None),
                    ItemCrop.adjusted_bbox_right.isnot(None),
                    ItemCrop.adjusted_bbox_lower.isnot(None),
                ),
            )
            .all()
        )

        upload_base = Path(settings.upload_dir).resolve()
        crop_base = Path(settings.crop_dir).resolve()
        recropped_ids = []

        for crop in crops:
            crop.crop_path = recrop_item_crop(crop, ef, upload_base, crop_base)
            recropped_ids.append(crop.id)

        db.commit()
    finally:
        db.close()

    return JSONResponse({"recropped": recropped_ids})
```

- [ ] **Step 4: Register in main.py**

In `src/cvp/main.py`, change:

```python
from cvp.routers import evidence, exports, items, matters, rooms, serp, vision
```

to:

```python
from cvp.routers import crops, evidence, exports, items, matters, rooms, serp, vision
```

And after `app.include_router(serp.router)`, add:

```python
app.include_router(crops.router)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_crops_router.py -v
```

Expected: all tests pass. If `test_adjust_bbox_rejects_out_of_bounds` fails due to x/y check order, verify the image is 200×200 and 9999 exceeds both dimensions.

- [ ] **Step 6: Lint**

```bash
uv run ruff check src/cvp/routers/crops.py
```

Expected: no output. Fix any reported issues.

- [ ] **Step 7: Commit**

```bash
git add src/cvp/routers/crops.py src/cvp/main.py tests/test_crops_router.py
git commit -m "feat: crops router — adjust-bbox, clear-bbox, crop-editor, recrop endpoints"
```

---

### Task 5: UI — crop editor panel, evidence grid button, app.js

**Files:**
- Create: `src/cvp/templates/_crop_editor.html`
- Modify: `src/cvp/templates/_evidence_grid.html`
- Modify: `src/cvp/static/app.js`

No automated tests — verify manually.

- [ ] **Step 1: Add toggleCropEditor to app.js**

Append to `src/cvp/static/app.js` after the `showCropPanel` function:

```javascript
// ── Crop editor toggle ───────────────────────────────────────────────────
function toggleCropEditor(fileId) {
  const existing = document.getElementById('crop-editor-' + fileId);
  if (existing) {
    existing.remove();
    return;
  }
  htmx.ajax('GET', '/api/evidence/' + fileId + '/crop-editor', {
    target: document.getElementById('evidence-grid'),
    swap: 'afterend',
  });
}
```

- [ ] **Step 2: Add "Edit crops" button to _evidence_grid.html**

Replace the entire contents of `src/cvp/templates/_evidence_grid.html` with:

```html
<div id="evidence-grid"
     class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
  {% for f in evidence_files %}
  <div data-file-card class="group relative rounded-lg border border-gray-200 bg-white overflow-hidden shadow-sm">
    {% if f.kind == "image" %}
    <img src="/files/{{ f.stored_path }}"
         alt="{{ f.filename }}"
         class="h-32 w-full object-cover">
    {% elif f.kind == "pdf" %}
    <div class="flex h-32 items-center justify-center bg-red-50 text-4xl">📄</div>
    {% elif f.kind == "video" %}
    <div class="flex h-32 items-center justify-center bg-purple-50 text-4xl">🎬</div>
    {% else %}
    <div class="flex h-32 items-center justify-center bg-gray-50 text-4xl">📎</div>
    {% endif %}

    <div class="px-2 py-1.5">
      <p class="truncate text-xs font-medium text-gray-700" title="{{ f.filename }}">{{ f.filename }}</p>
      <p class="text-xs text-gray-400">{{ (f.size_bytes / 1024) | round(1) }} KB</p>
      {% if f.kind == "image" and f.scanned %}
      <button onclick="toggleCropEditor('{{ f.id }}')"
              class="mt-1 rounded border border-indigo-200 px-1.5 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50">
        Edit crops
      </button>
      {% endif %}
    </div>

    <button
      hx-delete="/api/evidence/{{ f.id }}"
      hx-target="closest [data-file-card]"
      hx-swap="outerHTML"
      hx-confirm="Delete {{ f.filename }}?"
      class="absolute right-1 top-1 hidden rounded bg-red-600 px-1.5 py-0.5 text-xs font-semibold text-white opacity-90 group-hover:block hover:bg-red-700">
      ✕
    </button>
  </div>
  {% endfor %}
</div>
```

- [ ] **Step 3: Create _crop_editor.html**

Create `src/cvp/templates/_crop_editor.html` with the full content below.

The JS is wrapped in an IIFE to prevent scope pollution when HTMX loads multiple panels. Element IDs are suffixed with the evidence file ID to avoid DOM collisions.

```html
<div id="crop-editor-{{ evidence_file.id }}"
     class="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">

  <div class="flex items-center justify-between mb-3">
    <h3 class="text-sm font-semibold text-gray-800">Edit crops — {{ evidence_file.filename }}</h3>
    <button onclick="document.getElementById('crop-editor-{{ evidence_file.id }}').remove()"
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

<script>
(function () {
  var EF_ID = {{ evidence_file.id | tojson }};
  var IMG_W = {{ img_w }};
  var IMG_H = {{ img_h }};
  var CROPS = {{ crops_json | safe }};

  var canvas = document.getElementById('ce-canvas-' + EF_ID);
  var ctx = canvas.getContext('2d');
  var sidebar = document.getElementById('ce-sidebar-' + EF_ID);
  var recropBtn = document.getElementById('ce-recrop-btn-' + EF_ID);
  var statusEl = document.getElementById('ce-status-' + EF_ID);

  var MAX_W = 600;
  var scale = Math.min(1, MAX_W / IMG_W);
  canvas.width = Math.round(IMG_W * scale);
  canvas.height = Math.round(IMG_H * scale);

  var bgImg = new Image();
  bgImg.src = '/files/{{ stored_path }}';
  bgImg.onload = draw;

  var HANDLE_SIZE = 8;
  var MIN_SIZE = 10;

  var boxes = CROPS.map(function(c) {
    return {
      id: c.id,
      description: c.description,
      left: c.bbox[0], upper: c.bbox[1], right: c.bbox[2], lower: c.bbox[3],
      claudeLeft: c.claude_bbox[0], claudeUpper: c.claude_bbox[1],
      claudeRight: c.claude_bbox[2], claudeLower: c.claude_bbox[3],
      adjusted: c.adjusted,
    };
  });

  var selectedIdx = null;
  var drag = null;

  function tc(px) { return Math.round(px * scale); }
  function fc(cx) { return Math.round(cx / scale); }

  function getHandles(box) {
    var l = tc(box.left), u = tc(box.upper), r = tc(box.right), lo = tc(box.lower);
    var mx = Math.round((l + r) / 2), my = Math.round((u + lo) / 2);
    return [
      {x:l,y:u}, {x:mx,y:u}, {x:r,y:u}, {x:r,y:my},
      {x:r,y:lo}, {x:mx,y:lo}, {x:l,y:lo}, {x:l,y:my},
    ];
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (bgImg.complete && bgImg.naturalWidth) ctx.drawImage(bgImg, 0, 0, canvas.width, canvas.height);
    boxes.forEach(function(box, i) {
      var l = tc(box.left), u = tc(box.upper);
      var w = tc(box.right) - l, h = tc(box.lower) - u;
      ctx.strokeStyle = box.adjusted ? '#f59e0b' : '#6366f1';
      ctx.lineWidth = (i === selectedIdx) ? 2 : 1.5;
      ctx.strokeRect(l, u, w, h);
      ctx.fillStyle = box.adjusted ? '#f59e0b' : '#6366f1';
      ctx.font = 'bold 11px sans-serif';
      ctx.fillText(String(i + 1), l + 3, u + 13);
      if (i === selectedIdx) {
        getHandles(box).forEach(function(h) {
          ctx.fillStyle = '#fff';
          ctx.fillRect(h.x - HANDLE_SIZE/2, h.y - HANDLE_SIZE/2, HANDLE_SIZE, HANDLE_SIZE);
          ctx.strokeStyle = '#6366f1';
          ctx.lineWidth = 1;
          ctx.strokeRect(h.x - HANDLE_SIZE/2, h.y - HANDLE_SIZE/2, HANDLE_SIZE, HANDLE_SIZE);
        });
      }
    });
  }

  function hitHandle(box, cx, cy) {
    return getHandles(box).findIndex(function(h) {
      return Math.abs(cx - h.x) <= HANDLE_SIZE && Math.abs(cy - h.y) <= HANDLE_SIZE;
    });
  }

  function hitBox(box, cx, cy) {
    return cx >= tc(box.left) && cx <= tc(box.right) &&
           cy >= tc(box.upper) && cy <= tc(box.lower);
  }

  canvas.addEventListener('mousedown', function(e) {
    var rect = canvas.getBoundingClientRect();
    var cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    if (selectedIdx !== null) {
      var hi = hitHandle(boxes[selectedIdx], cx, cy);
      if (hi >= 0) {
        drag = {type:'handle', handleIdx:hi, startX:cx, startY:cy, origBox: Object.assign({}, boxes[selectedIdx])};
        return;
      }
    }
    for (var i = boxes.length - 1; i >= 0; i--) {
      if (hitBox(boxes[i], cx, cy)) {
        selectedIdx = i;
        drag = {type:'move', startX:cx, startY:cy, origBox: Object.assign({}, boxes[i])};
        draw();
        updateSidebar();
        return;
      }
    }
    selectedIdx = null; drag = null; draw(); updateSidebar();
  });

  canvas.addEventListener('mousemove', function(e) {
    if (!drag) return;
    var rect = canvas.getBoundingClientRect();
    var cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    var dx = fc(cx - drag.startX), dy = fc(cy - drag.startY);
    var ob = drag.origBox, box = boxes[selectedIdx];
    if (drag.type === 'move') {
      var w = ob.right - ob.left, h = ob.lower - ob.upper;
      box.left  = Math.max(0, Math.min(IMG_W - w, ob.left + dx));
      box.upper = Math.max(0, Math.min(IMG_H - h, ob.upper + dy));
      box.right = box.left + w;
      box.lower = box.upper + h;
    } else {
      var hi = drag.handleIdx;
      var l = ob.left, u = ob.upper, r = ob.right, lo = ob.lower;
      if ([0,6,7].indexOf(hi) >= 0) l = Math.max(0,          Math.min(r - MIN_SIZE, ob.left  + dx));
      if ([2,3,4].indexOf(hi) >= 0) r = Math.min(IMG_W,      Math.max(l + MIN_SIZE, ob.right + dx));
      if ([0,1,2].indexOf(hi) >= 0) u = Math.max(0,          Math.min(lo- MIN_SIZE, ob.upper + dy));
      if ([4,5,6].indexOf(hi) >= 0) lo= Math.min(IMG_H,      Math.max(u + MIN_SIZE, ob.lower + dy));
      box.left = l; box.upper = u; box.right = r; box.lower = lo;
    }
    updateSidebarInputs(); draw();
  });

  canvas.addEventListener('mouseup', function() {
    if (!drag) return;
    drag = null;
    if (selectedIdx !== null) autosave(selectedIdx);
  });

  function updateSidebar() {
    if (selectedIdx === null) {
      sidebar.innerHTML = '<p class="text-xs text-gray-400">Click a box to select it.</p>';
      return;
    }
    var box = boxes[selectedIdx];
    var fnKey = 'ceReset_' + EF_ID.replace(/-/g, '_');
    sidebar.innerHTML =
      '<p class="text-xs font-semibold text-gray-700 mb-2">#' + (selectedIdx+1) + ' ' + box.description + '</p>' +
      '<div class="grid grid-cols-2 gap-1 text-xs">' +
        '<label class="text-gray-500 self-center">Left</label>'  +
        '<input id="ce-left-'  + EF_ID + '" type="number" value="' + box.left  + '" min="0" max="' + IMG_W + '" class="border rounded px-1 py-0.5 text-right">' +
        '<label class="text-gray-500 self-center">Upper</label>' +
        '<input id="ce-upper-' + EF_ID + '" type="number" value="' + box.upper + '" min="0" max="' + IMG_H + '" class="border rounded px-1 py-0.5 text-right">' +
        '<label class="text-gray-500 self-center">Right</label>' +
        '<input id="ce-right-' + EF_ID + '" type="number" value="' + box.right + '" min="0" max="' + IMG_W + '" class="border rounded px-1 py-0.5 text-right">' +
        '<label class="text-gray-500 self-center">Lower</label>' +
        '<input id="ce-lower-' + EF_ID + '" type="number" value="' + box.lower + '" min="0" max="' + IMG_H + '" class="border rounded px-1 py-0.5 text-right">' +
      '</div>' +
      '<p id="ce-err-' + EF_ID + '" class="mt-1 text-xs text-red-500 hidden"></p>' +
      '<button onclick="' + fnKey + '()" class="mt-2 text-xs text-indigo-500 hover:underline">Reset to Claude bbox</button>';
    ['left','upper','right','lower'].forEach(function(f) {
      var el = document.getElementById('ce-' + f + '-' + EF_ID);
      if (!el) return;
      el.addEventListener('blur', commitInputs);
      el.addEventListener('keydown', function(ev) { if (ev.key === 'Enter') commitInputs(); });
    });
  }

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

  function updateSidebarInputs() {
    if (selectedIdx === null) return;
    var box = boxes[selectedIdx];
    ['left','upper','right','lower'].forEach(function(f) {
      var el = document.getElementById('ce-' + f + '-' + EF_ID);
      if (el) el.value = box[f];
    });
  }

  function commitInputs() {
    if (selectedIdx === null) return;
    var box = boxes[selectedIdx];
    var l  = parseInt(document.getElementById('ce-left-'  + EF_ID).value, 10);
    var u  = parseInt(document.getElementById('ce-upper-' + EF_ID).value, 10);
    var r  = parseInt(document.getElementById('ce-right-' + EF_ID).value, 10);
    var lo = parseInt(document.getElementById('ce-lower-' + EF_ID).value, 10);
    var errEl = document.getElementById('ce-err-' + EF_ID);
    if (l >= r || u >= lo) {
      errEl.textContent = 'left < right and upper < lower required';
      errEl.classList.remove('hidden');
      return;
    }
    errEl.classList.add('hidden');
    box.left = l; box.upper = u; box.right = r; box.lower = lo;
    draw(); autosave(selectedIdx);
  }

  function autosave(idx) {
    var box = boxes[idx];
    fetch('/api/item-crops/' + box.id + '/adjust-bbox', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({left: box.left, upper: box.upper, right: box.right, lower: box.lower}),
    }).then(function(r) {
      if (r.ok) { box.adjusted = true; draw(); updateRecropButton(); }
    });
  }

  function updateRecropButton() {
    var n = boxes.filter(function(b) { return b.adjusted; }).length;
    recropBtn.textContent = 'Re-crop adjusted items (' + n + ')';
    recropBtn.disabled = n === 0;
  }

  recropBtn.addEventListener('click', function() {
    recropBtn.disabled = true;
    statusEl.textContent = 'Re-cropping\u2026';
    fetch('/api/evidence/' + EF_ID + '/recrop', {method:'POST'})
      .then(function(r) { return r.json(); })
      .then(function(data) {
        statusEl.textContent = 'Done \u2014 ' + data.recropped.length + ' crop(s) updated.';
        var ts = Date.now();
        data.recropped.forEach(function(cropId) {
          document.querySelectorAll('img[src*="' + cropId + '"]').forEach(function(img) {
            img.src = img.src.split('?')[0] + '?v=' + ts;
          });
        });
        updateRecropButton();
      })
      .catch(function() {
        statusEl.textContent = 'Error \u2014 check console.';
        recropBtn.disabled = false;
      });
  });

  updateRecropButton();
  draw();
})();
</script>
```

- [ ] **Step 4: Start dev server and verify manually**

```bash
uv run dev
```

Open http://localhost:8000 in a browser and verify:

1. Navigate to a matter with at least one scanned evidence image
2. Click the **Evidence** tab
3. Confirm "Edit crops" button appears on scanned image cards only
4. Click "Edit crops" — editor panel appears below the grid
5. Canvas shows the evidence photo with colored bounding boxes (indigo = Claude bbox, amber = adjusted)
6. Click a box — sidebar shows item name and `Left / Upper / Right / Lower` inputs
7. Drag box body — moves; mouseup auto-saves (check DevTools Network for `POST /api/item-crops/.../adjust-bbox`)
8. Drag a corner handle — resizes two edges; edge handle resizes one edge
9. Type new numbers in sidebar, press Enter — canvas updates, auto-saves
10. Click "Reset to Claude bbox" — box returns to original, amber color gone
11. "Re-crop adjusted items (N)" button enables when N > 0
12. Click "Re-crop" — status shows "Done — N crop(s) updated"
13. Click "Edit crops" again — panel closes

- [ ] **Step 5: Commit**

```bash
git add src/cvp/templates/_crop_editor.html src/cvp/templates/_evidence_grid.html src/cvp/static/app.js
git commit -m "feat: canvas-based crop adjustment editor on Evidence tab"
```

---

## Spec coverage

| Requirement | Task |
|---|---|
| `adjusted_bbox_*` nullable columns on `ItemCrop` | 1, 2 |
| `effective_bbox` property (falls back if any `None`; zero is valid) | 1 |
| Alembic migration, no backfill | 2 |
| `recrop_item_crop` service, no padding | 3 |
| `vision.py` refactored to use service | 3 |
| `POST /api/item-crops/{id}/adjust-bbox` with validation | 4 |
| `DELETE /api/item-crops/{id}/adjust-bbox` | 4 |
| `GET /api/evidence/{id}/crop-editor` HTML partial | 4 |
| `POST /api/evidence/{id}/recrop` | 4 |
| Router registered in `main.py` | 4 |
| "Edit crops" button on scanned image cards | 5 |
| `toggleCropEditor(fileId)` in `app.js` | 5 |
| Canvas with indigo/amber boxes, index labels | 5 |
| 8 resize handles on selected box | 5 |
| Drag body = move; drag handle = resize; min 10×10; clamped | 5 |
| Sidebar: name, 4 inputs, reset link, error line, re-crop button | 5 |
| Auto-save on `mouseup` and input `blur`/`Enter` | 5 |
| Re-crop button cache-busts SERP panel thumbnails | 5 |
| Unit tests for `effective_bbox` | 1 |
| Unit tests for `recrop_item_crop` | 3 |
| Integration tests for crops router | 4 |
