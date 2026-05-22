# Bulk Evidence Scan and Remove Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Scan all unscanned" and "Remove all images" bulk actions to the evidence tab, replacing the fragile in-memory job dict with a DB-backed queue and an idle-stopping worker thread.

**Architecture:** Two new ORM tables (`vision_jobs`, `vision_job_images`) store scan job state persistently. A single daemon thread processes images sequentially (500ms pause, CLAUDE.md rule #8) and blocks on a `threading.Event` when idle. Evidence delete (single and bulk) now cascades to orphaned Items and ItemCrops via a shared helper.

**Tech Stack:** SQLAlchemy 2.x, Alembic, FastAPI BackgroundTasks, HTMX, Pillow, threading.Event, existing OpenRouter client.

**Spec:** `docs/superpowers/specs/2026-05-22-bulk-evidence-scan-and-remove-design.md`

---

### Task 0: Create feature branch

**Files:** none

- [ ] **Step 1: Create and check out branch**

```bash
git checkout -b feat/bulk-evidence-scan-and-remove
```

Expected: `Switched to a new branch 'feat/bulk-evidence-scan-and-remove'`

---

### Task 1: Add VisionJob and VisionJobImage ORM models

**Files:**
- Modify: `src/cvp/models.py`

- [ ] **Step 1: Write a failing test proving the tables don't exist yet**

```bash
source .venv/bin/activate && python -c "
from cvp.models import VisionJob
"
```

Expected: `ImportError: cannot import name 'VisionJob'`

- [ ] **Step 2: Add `Index` to the sqlalchemy import in `models.py`**

In `src/cvp/models.py`, change:
```python
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
```
to:
```python
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
```

- [ ] **Step 3: Append VisionJob and VisionJobImage classes after VisionRun in `models.py`**

After the `VisionRun` class (which ends around line 211), add:

```python
class VisionJob(Base):
    """A batch vision scan job — groups one or more VisionJobImages."""

    __tablename__ = "vision_jobs"
    __table_args__ = (Index("ix_vision_jobs_matter_created", "matter_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    model_slug: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="running")  # running | done | error
    created_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    images: Mapped[list["VisionJobImage"]] = relationship(
        "VisionJobImage", back_populates="job", cascade="all, delete-orphan"
    )


class VisionJobImage(Base):
    """One image within a VisionJob, tracking its individual scan status."""

    __tablename__ = "vision_job_images"
    __table_args__ = (
        Index("ix_vision_job_images_status_created", "status", "created_at"),
        Index("ix_vision_job_images_evidence_file_id", "evidence_file_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    job_id: Mapped[str] = mapped_column(
        String, ForeignKey("vision_jobs.id", ondelete="CASCADE"), nullable=False
    )
    evidence_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_files.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | running | done | error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped["VisionJob"] = relationship("VisionJob", back_populates="images")
```

- [ ] **Step 4: Verify import works**

```bash
source .venv/bin/activate && python -c "
from cvp.models import VisionJob, VisionJobImage
print('ok')
"
```

Expected: `ok`

- [ ] **Step 5: Run existing tests to confirm no regressions**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -20
```

Expected: all tests pass (new tables auto-created in SQLite in-memory test DBs via existing `Base.metadata.create_all`).

- [ ] **Step 6: Commit**

```bash
git add src/cvp/models.py
git commit -m "feat: add VisionJob and VisionJobImage ORM models"
```

---

### Task 2: Alembic migration for vision_jobs and vision_job_images

**Files:**
- Create: `migrations/versions/<timestamp>_add_vision_job_tables.py`

- [ ] **Step 1: Generate the migration**

```bash
source .venv/bin/activate && uv run alembic revision --autogenerate -m "add_vision_job_tables"
```

Expected: a new file in `migrations/versions/` like `20260522_XXXXXXXX_add_vision_job_tables.py`.

- [ ] **Step 2: Verify the generated migration contains both tables**

Open the generated file and confirm `upgrade()` contains `op.create_table('vision_jobs', ...)` and `op.create_table('vision_job_images', ...)` plus the three indexes. If `downgrade()` is missing `op.drop_table` calls, add them:

```python
def downgrade() -> None:
    op.drop_index("ix_vision_job_images_evidence_file_id", table_name="vision_job_images")
    op.drop_index("ix_vision_job_images_status_created", table_name="vision_job_images")
    op.drop_table("vision_job_images")
    op.drop_index("ix_vision_jobs_matter_created", table_name="vision_jobs")
    op.drop_table("vision_jobs")
```

- [ ] **Step 3: Apply migration**

```bash
source .venv/bin/activate && uv run alembic upgrade head
```

Expected: no errors, ends with `Running upgrade ... -> <rev>`.

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/
git commit -m "feat: migration — add vision_jobs and vision_job_images tables"
```

---

### Task 3: Create evidence_cleanup.py cascade-delete service

**Files:**
- Create: `src/cvp/services/evidence_cleanup.py`
- Create: `tests/test_evidence_cleanup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evidence_cleanup.py`:

```python
"""Tests for evidence_cleanup.delete_evidence_file cascade helper."""

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, EvidenceFile, Item, ItemCrop, Matter, VisionRun
from cvp.models_vision import VisionModel


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(Category(id=1, name="Misc", useful_life_years=8, acv_floor_pct=0.2))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def matter(db):
    m = Matter(policyholder_name="Test", loss_type="total_loss")
    db.add(m)
    db.commit()
    return m


def _make_jpeg(path):
    Image.new("RGB", (10, 10), "white").save(path, "JPEG")


def test_delete_removes_evidence_file_from_disk(db, matter, tmp_path):
    from pathlib import Path
    from cvp.services.evidence_cleanup import delete_evidence_file

    img = tmp_path / "photo.jpg"
    _make_jpeg(img)
    ef = EvidenceFile(
        matter_id=matter.id, filename="photo.jpg",
        stored_path=str(img), mime_type="image/jpeg",
        kind="image", size_bytes=img.stat().st_size,
    )
    db.add(ef)
    db.commit()

    delete_evidence_file(db, ef, tmp_path, tmp_path)

    assert not img.exists()
    assert db.get(EvidenceFile, ef.id) is None


def test_delete_cascades_to_orphan_item_and_crop(db, matter, tmp_path):
    from pathlib import Path
    from cvp.services.evidence_cleanup import delete_evidence_file

    img = tmp_path / "photo2.jpg"
    _make_jpeg(img)
    ef = EvidenceFile(
        matter_id=matter.id, filename="photo2.jpg",
        stored_path=str(img), mime_type="image/jpeg",
        kind="image", size_bytes=img.stat().st_size,
    )
    db.add(ef)
    db.flush()

    item = Item(
        matter_id=matter.id, category_id=1, line_number=1,
        description="TV", quantity=1, age_years=0.0, condition="average",
        rcv_unit_cents=0, rcv_total_cents=0, acv_total_cents=0, confirmed=False,
    )
    db.add(item)
    db.flush()

    crop_file = tmp_path / f"{ef.id}" / f"{str(uuid.uuid4())}.jpg"
    crop_file.parent.mkdir(parents=True, exist_ok=True)
    _make_jpeg(crop_file)

    crop = ItemCrop(
        id=str(uuid.uuid4()), item_id=item.id, evidence_file_id=ef.id,
        bbox_left=0, bbox_upper=0, bbox_right=5, bbox_lower=5,
        crop_path=str(crop_file.relative_to(tmp_path)),
    )
    db.add(crop)
    db.commit()

    delete_evidence_file(db, ef, tmp_path, tmp_path)

    assert db.get(Item, item.id) is None
    assert db.get(ItemCrop, crop.id) is None
    assert not crop_file.exists()


def test_delete_keeps_item_with_crop_from_other_file(db, matter, tmp_path):
    from pathlib import Path
    from cvp.services.evidence_cleanup import delete_evidence_file

    img1 = tmp_path / "photo_a.jpg"
    img2 = tmp_path / "photo_b.jpg"
    _make_jpeg(img1)
    _make_jpeg(img2)

    ef1 = EvidenceFile(
        matter_id=matter.id, filename="photo_a.jpg",
        stored_path=str(img1), mime_type="image/jpeg", kind="image", size_bytes=1,
    )
    ef2 = EvidenceFile(
        matter_id=matter.id, filename="photo_b.jpg",
        stored_path=str(img2), mime_type="image/jpeg", kind="image", size_bytes=1,
    )
    db.add_all([ef1, ef2])
    db.flush()

    item = Item(
        matter_id=matter.id, category_id=1, line_number=1,
        description="Sofa", quantity=1, age_years=0.0, condition="average",
        rcv_unit_cents=0, rcv_total_cents=0, acv_total_cents=0, confirmed=False,
    )
    db.add(item)
    db.flush()

    crop1 = ItemCrop(
        id=str(uuid.uuid4()), item_id=item.id, evidence_file_id=ef1.id,
        bbox_left=0, bbox_upper=0, bbox_right=5, bbox_lower=5, crop_path="",
    )
    crop2 = ItemCrop(
        id=str(uuid.uuid4()), item_id=item.id, evidence_file_id=ef2.id,
        bbox_left=0, bbox_upper=0, bbox_right=5, bbox_lower=5, crop_path="",
    )
    db.add_all([crop1, crop2])
    db.commit()

    delete_evidence_file(db, ef1, tmp_path, tmp_path)

    # Item still exists — it has a crop from ef2
    assert db.get(Item, item.id) is not None
    # crop1 gone, crop2 remains
    assert db.get(ItemCrop, crop1.id) is None
    assert db.get(ItemCrop, crop2.id) is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && uv run pytest tests/test_evidence_cleanup.py -v 2>&1 | tail -20
```

Expected: `ImportError` or `ModuleNotFoundError` for `cvp.services.evidence_cleanup`.

- [ ] **Step 3: Create `src/cvp/services/evidence_cleanup.py`**

```python
"""Cascade-delete helper for removing evidence files and their dependents."""

from pathlib import Path

from sqlalchemy.orm import Session

from cvp.models import EvidenceFile, Item, ItemCrop


def delete_evidence_file(
    db: Session,
    ef: EvidenceFile,
    upload_base: Path,
    crop_base: Path,
) -> None:
    """Delete an EvidenceFile and cascade to orphaned Items, ItemCrops, and disk files.

    Commits on completion. Safe to call in a loop — each call is its own transaction.
    """
    upload_base = upload_base.resolve()
    crop_base = crop_base.resolve()

    # Collect crop info before ORM deletes wipe the rows.
    crops = db.query(ItemCrop).filter_by(evidence_file_id=ef.id).all()

    # Items whose ONLY crop points at this file should be deleted.
    item_ids_to_delete: set[str] = set()
    for crop in crops:
        other_count = (
            db.query(ItemCrop)
            .filter(
                ItemCrop.item_id == crop.item_id,
                ItemCrop.evidence_file_id != ef.id,
            )
            .count()
        )
        if other_count == 0:
            item_ids_to_delete.add(crop.item_id)

    # Delete crop image files from disk.
    for crop in crops:
        if crop.crop_path:
            crop_file = (crop_base / crop.crop_path).resolve()
            if str(crop_file).startswith(str(crop_base)) and crop_file.exists():
                crop_file.unlink()

    # Delete evidence file from disk.
    dest = (upload_base / ef.stored_path).resolve()
    if str(dest).startswith(str(upload_base)) and dest.exists():
        dest.unlink()

    # ORM delete cascades to ItemCrop rows and VisionRun rows.
    db.delete(ef)
    db.flush()

    # Delete orphaned Item rows (crops already gone via cascade above).
    for item_id in item_ids_to_delete:
        item = db.get(Item, item_id)
        if item is not None:
            db.delete(item)

    db.commit()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && uv run pytest tests/test_evidence_cleanup.py -v 2>&1 | tail -20
```

Expected: 3 tests pass.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/services/evidence_cleanup.py tests/test_evidence_cleanup.py
git commit -m "feat: evidence_cleanup cascade-delete helper with tests"
```

---

### Task 4: Update single-image delete to use cascade helper

**Files:**
- Modify: `src/cvp/routers/evidence.py`

- [ ] **Step 1: Replace the body of `delete_evidence` to use the helper**

In `src/cvp/routers/evidence.py`, replace the `delete_evidence` function body:

```python
@router.delete("/api/evidence/{file_id}", response_class=HTMLResponse)
def delete_evidence(
    request: Request,
    file_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None:
            raise HTTPException(status_code=404, detail="File not found")
        upload_base = Path(settings.upload_dir).resolve()
        crop_base = Path(settings.crop_dir).resolve()
        dest = (upload_base / ef.stored_path).resolve()
        if not str(dest).startswith(str(upload_base)):
            raise HTTPException(status_code=400, detail="Invalid path")
        matter_id = ef.matter_id
        from cvp.services.evidence_cleanup import delete_evidence_file
        delete_evidence_file(db, ef, upload_base, crop_base)
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.delete",
        resource_type="evidence",
        resource_id=file_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
```

- [ ] **Step 2: Run full test suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add src/cvp/routers/evidence.py
git commit -m "feat: single-image delete now cascades to Items and ItemCrops"
```

---

### Task 5: Add remove-all-images endpoint

**Files:**
- Modify: `src/cvp/routers/evidence.py`
- Create: `tests/test_evidence_remove_all.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_evidence_remove_all.py`:

```python
"""Tests for POST /api/matters/{matter_id}/evidence/remove-all-images."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, EvidenceFile, Matter

MANAGER_ID = "mgr-1"
MATTER_ID = "matter-rem"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    from cvp.models_auth import User
    db.add(User(id=MANAGER_ID, email="mgr@test.com", display_name="Mgr", system_role="internal_user"))
    db.add(Matter(id=MATTER_ID, policyholder_name="Owner", loss_type="total_loss"))
    db.commit()
    yield db
    db.close()


@pytest.fixture
def client_manager(db_session):
    import inspect
    import cvp.routers.evidence as ev_router

    async def mock_manager():
        return CurrentUser(
            id=MANAGER_ID, email="mgr@test.com",
            system_role="internal_user", group_id=None, group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(ev_router.remove_all_images).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_manager
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _add_image(db, matter_id, path):
    PILImage.new("RGB", (10, 10), "white").save(path, "JPEG")
    ef = EvidenceFile(
        matter_id=matter_id, filename=os.path.basename(path),
        stored_path=path, mime_type="image/jpeg", kind="image",
        size_bytes=os.path.getsize(path),
    )
    db.add(ef)
    db.commit()
    return ef


def test_remove_all_images_deletes_images_leaves_pdfs(client_manager, db_session, monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr(
        "cvp.routers.evidence.settings",
        type("S", (), {"upload_dir": str(tmp_path), "crop_dir": str(tmp_path)})(),
    )
    monkeypatch.setattr(
        "cvp.services.evidence_cleanup.Path",
        Path,  # passthrough — real Path
    )

    img1 = str(tmp_path / "a.jpg")
    img2 = str(tmp_path / "b.jpg")
    _add_image(db_session, MATTER_ID, img1)
    _add_image(db_session, MATTER_ID, img2)

    # Add a PDF (should survive)
    pdf = EvidenceFile(
        matter_id=MATTER_ID, filename="doc.pdf",
        stored_path="doc.pdf", mime_type="application/pdf",
        kind="pdf", size_bytes=100,
    )
    db_session.add(pdf)
    db_session.commit()

    monkeypatch.setattr("cvp.routers.evidence.SessionLocal", lambda: db_session)

    resp = client_manager.post(
        f"/api/matters/{MATTER_ID}/evidence/remove-all-images",
        data={"confirm_count": "2"},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    remaining = db_session.query(EvidenceFile).filter_by(matter_id=MATTER_ID).all()
    assert len(remaining) == 1
    assert remaining[0].kind == "pdf"


def test_remove_all_images_rejects_mismatched_count(client_manager, db_session, monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr(
        "cvp.routers.evidence.settings",
        type("S", (), {"upload_dir": str(tmp_path), "crop_dir": str(tmp_path)})(),
    )
    monkeypatch.setattr("cvp.routers.evidence.SessionLocal", lambda: db_session)

    img1 = str(tmp_path / "c.jpg")
    _add_image(db_session, MATTER_ID, img1)

    resp = client_manager.post(
        f"/api/matters/{MATTER_ID}/evidence/remove-all-images",
        data={"confirm_count": "99"},
    )
    assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && uv run pytest tests/test_evidence_remove_all.py -v 2>&1 | tail -10
```

Expected: `AttributeError` — `remove_all_images` doesn't exist yet.

- [ ] **Step 3: Add the endpoint to `evidence.py`**

Add these imports at the top of `src/cvp/routers/evidence.py`:

```python
from fastapi import Form
from cvp.services.evidence_cleanup import delete_evidence_file
```

Then add the new endpoint after `delete_evidence`:

```python
@router.post(
    "/api/matters/{matter_id}/evidence/remove-all-images", response_class=HTMLResponse
)
def remove_all_images(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    confirm_count: int = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        image_files = (
            db.query(EvidenceFile)
            .filter_by(matter_id=matter_id, kind="image")
            .order_by(EvidenceFile.created_at)
            .all()
        )
        if len(image_files) != confirm_count:
            return HTMLResponse(
                '<p class="text-sm text-red-600">Count mismatch — please refresh and try again.</p>',
                status_code=409,
            )

        upload_base = Path(settings.upload_dir).resolve()
        crop_base = Path(settings.crop_dir).resolve()
        file_ids = [ef.id for ef in image_files]
        deleted_count = len(file_ids)

        for file_id in file_ids:
            ef = db.get(EvidenceFile, file_id)
            if ef is not None:
                delete_evidence_file(db, ef, upload_base, crop_base)

        evidence_files = (
            db.query(EvidenceFile)
            .filter_by(matter_id=matter_id)
            .order_by(EvidenceFile.created_at.desc())
            .all()
        )
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.remove_all_images",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
        detail=f"count={deleted_count}",
    )
    return HTMLResponse(
        templates.get_template("_evidence_grid.html").render(
            evidence_files=evidence_files, matter_id=matter_id
        )
    )
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && uv run pytest tests/test_evidence_remove_all.py tests/test_evidence_cleanup.py -v 2>&1 | tail -15
```

Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/routers/evidence.py tests/test_evidence_remove_all.py
git commit -m "feat: add remove-all-images endpoint with cascade delete"
```

---

### Task 6: Refactor vision.py service — DB-backed jobs + downscaling

**Files:**
- Modify: `src/cvp/services/vision.py`
- Modify: `tests/test_vision_service.py`
- Create: `tests/test_vision_downscale.py`

The old `create_job / get_job / run_scan` API is replaced by `process_one_image / get_job_data`. The worker (Task 7) calls `process_one_image`.

- [ ] **Step 1: Write the downscale unit tests**

Create `tests/test_vision_downscale.py`:

```python
"""Unit tests for vision._downscale."""

import io

import pytest
from PIL import Image


def _make_jpeg_bytes(w: int, h: int, size_hint_mb: float = 0) -> bytes:
    """Create a JPEG image. If size_hint_mb > 0, pad to exceed that many bytes."""
    img = Image.new("RGB", (w, h), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    data = buf.getvalue()
    if size_hint_mb > 0:
        # Pad so len > 1MB by appending a comment-like block (harmless extra bytes)
        target = int(size_hint_mb * 1_000_000)
        while len(data) < target:
            data = data + b"\x00" * 10_000
    return data


def test_downscale_large_image_resizes():
    from cvp.services.vision import _downscale

    big_bytes = _make_jpeg_bytes(3000, 2000, size_hint_mb=1.1)
    result_bytes, mime = _downscale(big_bytes)

    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(result_bytes)) as img:
        w, h = img.size
        assert max(w, h) <= 1568


def test_downscale_small_image_preserves_dimensions():
    from cvp.services.vision import _downscale

    small_bytes = _make_jpeg_bytes(800, 600)
    result_bytes, mime = _downscale(small_bytes)

    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(result_bytes)) as img:
        assert img.size == (800, 600)


def test_downscale_portrait_respects_long_edge():
    from cvp.services.vision import _downscale

    tall_bytes = _make_jpeg_bytes(400, 3000, size_hint_mb=1.1)
    result_bytes, _ = _downscale(tall_bytes)

    with Image.open(io.BytesIO(result_bytes)) as img:
        w, h = img.size
        assert h <= 1568  # portrait: height is long edge
        assert w < h
```

- [ ] **Step 2: Run downscale tests to confirm they fail**

```bash
source .venv/bin/activate && uv run pytest tests/test_vision_downscale.py -v 2>&1 | tail -10
```

Expected: `ImportError` — `_downscale` not yet exported.

- [ ] **Step 3: Rewrite `src/cvp/services/vision.py`**

Replace the entire file with:

```python
"""Vision scan service — sequential image processing via OpenRouter."""

import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.models import (
    Category,
    EvidenceFile,
    Item,
    ItemCrop,
    VisionJob,
    VisionJobImage,
    VisionRun,
)
from cvp.models_vision import VisionModel
from cvp.services import openrouter
from cvp.services.crop import recrop_item_crop
from cvp.services.vision_adapters import resolve as resolve_adapter
from cvp.services.vision_prompts import SCAN_PROMPT_VERSION, build_scan_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Image downscaling
# ---------------------------------------------------------------------------


def _downscale(image_bytes: bytes) -> tuple[bytes, str]:
    """Resize long-edge to ≤1568px, re-encode as JPEG quality 85."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        w, h = img.size
        max_side = max(w, h)
        if max_side > 1568:
            scale = 1568 / max_side
            resized = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
        else:
            resized = img.copy()
        buf = io.BytesIO()
        resized.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------


def _match_category_id(hint: str | None, categories: list[Category]) -> int:
    if not hint or not categories:
        return categories[-1].id if categories else 1
    hint_lower = hint.lower()
    for cat in categories:
        if hint_lower in cat.name.lower() or cat.name.lower() in hint_lower:
            return cat.id
    hint_words = set(hint_lower.split())
    best_id, best_score = categories[-1].id, 0
    for cat in categories:
        cat_words = set(cat.name.lower().split(",")[0].split())
        score = len(hint_words & cat_words)
        if score > best_score:
            best_score, best_id = score, cat.id
    return best_id


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return []


# ---------------------------------------------------------------------------
# Job status query
# ---------------------------------------------------------------------------


def get_job_data(job_id: str) -> dict:
    """Return progress dict compatible with _scan_progress.html template vars."""
    db = SessionLocal()
    try:
        job = db.get(VisionJob, job_id)
        if job is None:
            return {
                "status": "error",
                "progress": 0,
                "total": 0,
                "items_created": 0,
                "errors": ["Job not found"],
            }
        images = db.query(VisionJobImage).filter_by(job_id=job_id).all()
        total = len(images)
        progress = sum(1 for i in images if i.status in ("done", "error"))
        items_created = sum(i.items_created for i in images)
        errors = [i.error_message for i in images if i.status == "error" and i.error_message]
        return {
            "status": job.status,
            "progress": progress,
            "total": total,
            "items_created": items_created,
            "errors": errors,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Core scan logic — called by vision_worker per image
# ---------------------------------------------------------------------------


def _maybe_complete_job(db: Session, job_id: str) -> None:
    """Mark the VisionJob done/error when all images are in a terminal state."""
    pending = (
        db.query(VisionJobImage)
        .filter(
            VisionJobImage.job_id == job_id,
            VisionJobImage.status.in_(["pending", "running"]),
        )
        .count()
    )
    if pending > 0:
        return
    job = db.get(VisionJob, job_id)
    if job is None:
        return
    has_errors = (
        db.query(VisionJobImage).filter_by(job_id=job_id, status="error").count()
    )
    job.status = "error" if has_errors else "done"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()


def process_one_image(job_image_id: str) -> None:
    """Process one VisionJobImage. Opens its own DB session. Marks status done or error."""
    upload_base = Path(settings.upload_dir).resolve()
    crop_base = Path(settings.crop_dir).resolve()

    db = SessionLocal()
    try:
        job_image = db.get(VisionJobImage, job_image_id)
        if job_image is None:
            return

        job_id = job_image.job_id
        job = db.get(VisionJob, job_id)
        if job is None:
            return

        ef = db.get(EvidenceFile, job_image.evidence_file_id)

        if ef is None or ef.kind != "image":
            job_image.status = "done"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

        # Restart recovery: already successfully scanned in a prior run.
        if ef.scanned:
            job_image.status = "done"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

        vm = db.query(VisionModel).filter_by(slug=job.model_slug, is_enabled=True).first()
        if vm is None:
            job_image.status = "error"
            job_image.error_message = f"unknown or disabled model: {job.model_slug}"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

        adapter_fn = resolve_adapter(vm.adapter)
        categories = db.query(Category).order_by(Category.id).all()

        image_path = Path(ef.stored_path)
        if not image_path.is_absolute():
            image_path = (upload_base / ef.stored_path).resolve()
        if not image_path.exists():
            job_image.status = "error"
            job_image.error_message = "image file not found on disk"
            job_image.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, job_id)
            return

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

        raw_text = openrouter.call_vision(
            model_slug=job.model_slug,
            image_bytes=image_bytes,
            mime_type=mime,
            prompt=build_scan_prompt(scan_w, scan_h),
        )
        parsed = _parse_response(raw_text)

        max_line = (
            db.query(sqlfunc.max(Item.line_number))
            .filter(Item.matter_id == job.matter_id)
            .scalar()
            or 0
        )
        items_this_file = 0

        for raw_item in parsed:
            if not isinstance(raw_item, dict):
                continue
            description = str(raw_item.get("description") or "").strip()
            if not description:
                continue

            cat_id = _match_category_id(raw_item.get("category_hint"), categories)
            qty = max(1, int(raw_item.get("quantity") or 1))
            condition = str(raw_item.get("condition") or "average")
            if condition not in ("excellent", "above_average", "average", "below_average"):
                condition = "average"
            search_hint = str(raw_item.get("search_hint") or "").strip() or None

            max_line += 1
            item = Item(
                matter_id=job.matter_id,
                category_id=cat_id,
                line_number=max_line,
                description=description,
                brand=str(raw_item.get("brand") or "").strip() or None,
                model=str(raw_item.get("model") or "").strip() or None,
                quantity=qty,
                age_years=0.0,
                condition=condition,
                rcv_unit_cents=0,
                rcv_total_cents=0,
                acv_total_cents=0,
                confirmed=False,
                search_hint=search_hint,
                notes=(
                    f"room_hint:{raw_item.get('room_hint') or ''}"
                    f"|confidence:{raw_item.get('confidence') or 'medium'}"
                ),
            )
            db.add(item)
            db.flush()

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
                item_crop = ItemCrop(
                    id=str(uuid.uuid4()),
                    item_id=item.id,
                    evidence_file_id=ef.id,
                    bbox_left=left,
                    bbox_upper=upper,
                    bbox_right=right,
                    bbox_lower=lower,
                )
                item_crop.crop_path = recrop_item_crop(item_crop, ef, upload_base, crop_base)
                db.add(item_crop)

            items_this_file += 1

        vr = VisionRun(
            matter_id=job.matter_id,
            evidence_file_id=ef.id,
            model=job.model_slug,
            prompt_version=SCAN_PROMPT_VERSION,
            raw_response=raw_text,
            items_created=items_this_file,
            adapter=vm.adapter,
            cost_cents_estimated=vm.prompt_image_cost_cents,
        )
        db.add(vr)
        ef.scanned = True
        job_image.status = "done"
        job_image.items_created = items_this_file
        job_image.completed_at = datetime.now(timezone.utc)
        db.commit()
        _maybe_complete_job(db, job_id)

    except openrouter.OpenRouterError as exc:
        db.rollback()
        ji = db.get(VisionJobImage, job_image_id)
        if ji:
            ji.status = "error"
            ji.error_message = f"API error — {exc.status} {exc.message}"
            ji.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, ji.job_id)
    except httpx.TimeoutException:
        db.rollback()
        ji = db.get(VisionJobImage, job_image_id)
        if ji:
            ji.status = "error"
            ji.error_message = "timeout"
            ji.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, ji.job_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("vision scan failure for job_image %s", job_image_id)
        ji = db.get(VisionJobImage, job_image_id)
        if ji:
            ji.status = "error"
            ji.error_message = str(exc)[:500]
            ji.completed_at = datetime.now(timezone.utc)
            db.commit()
            _maybe_complete_job(db, ji.job_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Cost estimate (unchanged)
# ---------------------------------------------------------------------------


def estimate_cost(n_images: int, model_slug: str) -> str:
    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug).first()
    finally:
        db.close()
    if vm is None or vm.prompt_image_cost_cents is None:
        return "~$?"
    total_cents = n_images * vm.prompt_image_cost_cents
    return f"~${total_cents / 100:.2f}"
```

- [ ] **Step 4: Update `tests/test_vision_service.py` to use the new API**

Replace the test file with:

```python
"""Integration tests for vision.process_one_image — OpenRouter mocked."""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import (
    Base,
    Category,
    EvidenceFile,
    Item,
    ItemCrop,
    Matter,
    VisionJob,
    VisionJobImage,
    VisionRun,
)
from cvp.models_vision import VisionModel
from cvp.services import vision as vision_svc


@pytest.fixture
def isolated_db(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(Category(id=1, name="Miscellaneous household goods", useful_life_years=8, acv_floor_pct=0.20))
    db.add(Category(id=21, name="Electronics, TVs and displays", useful_life_years=7, acv_floor_pct=0.20))
    db.add(VisionModel(
        slug="anthropic/claude-opus-4", display_name="Claude Opus 4",
        adapter="pixel_passthrough", supports_bbox=True,
        is_default=True, is_enabled=True, recommended=True,
    ))
    db.add(VisionModel(
        slug="openai/gpt-4o", display_name="GPT-4o",
        adapter="none", supports_bbox=False,
        is_default=False, is_enabled=True, recommended=False,
    ))
    db.commit()
    yield db
    db.close()


@pytest.fixture
def matter_with_job(isolated_db, tmp_path):
    """Returns (matter_id, job_image_id) for a matter with one image ready to scan."""
    from PIL import Image

    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (200, 200), color="white").save(img_path)

    matter = Matter(policyholder_name="Test Owner", loss_type="total_loss")
    isolated_db.add(matter)
    isolated_db.flush()

    ef = EvidenceFile(
        matter_id=matter.id,
        filename="test.jpg",
        stored_path=str(img_path),
        mime_type="image/jpeg",
        kind="image",
        size_bytes=img_path.stat().st_size,
    )
    isolated_db.add(ef)
    isolated_db.flush()

    job = VisionJob(matter_id=matter.id, model_slug="anthropic/claude-opus-4", status="running")
    isolated_db.add(job)
    isolated_db.flush()

    job_image = VisionJobImage(job_id=job.id, evidence_file_id=ef.id, status="running")
    isolated_db.add(job_image)
    isolated_db.commit()
    return matter.id, job_image.id


def _monkeypatch_vision(monkeypatch, isolated_db, tmp_path):
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: isolated_db)
    monkeypatch.setattr(
        "cvp.config.settings",
        type("S", (), {
            "upload_dir": str(tmp_path),
            "crop_dir": str(tmp_path),
            "openrouter_api_key": "test-key",
            "openrouter_referer": "",
            "openrouter_app_title": "",
        })(),
    )


def test_process_one_image_creates_items_and_crops(matter_with_job, isolated_db, monkeypatch, tmp_path):
    matter_id, job_image_id = matter_with_job
    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    fake_response = json.dumps([{
        "description": "Samsung 65-inch QLED TV",
        "brand": "Samsung", "model": "QN65Q80C",
        "category_hint": "Electronics, TVs and displays",
        "quantity": 1, "condition": "average",
        "search_hint": "Samsung 65 QLED QN65Q80C",
        "room_hint": "Living Room", "confidence": "high",
        "bounding_box": [10, 10, 100, 100],
    }])

    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response):
        vision_svc.process_one_image(job_image_id)

    items = isolated_db.query(Item).filter_by(matter_id=matter_id).all()
    assert len(items) == 1
    assert items[0].description == "Samsung 65-inch QLED TV"

    crops = isolated_db.query(ItemCrop).filter_by(item_id=items[0].id).all()
    assert len(crops) == 1

    runs = isolated_db.query(VisionRun).filter_by(matter_id=matter_id).all()
    assert len(runs) == 1
    assert runs[0].model == "anthropic/claude-opus-4"

    job_image = isolated_db.get(VisionJobImage, job_image_id)
    assert job_image.status == "done"
    assert job_image.items_created == 1


def test_process_one_image_skips_crop_when_adapter_none(matter_with_job, isolated_db, monkeypatch, tmp_path):
    matter_id, job_image_id = matter_with_job
    # Update job to use the no-bbox model
    ji = isolated_db.get(VisionJobImage, job_image_id)
    job = isolated_db.get(VisionJob, ji.job_id)
    job.model_slug = "openai/gpt-4o"
    isolated_db.commit()

    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    fake_response = json.dumps([{
        "description": "Coffee table",
        "category_hint": "Miscellaneous household goods",
        "quantity": 1, "condition": "average",
    }])

    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response):
        vision_svc.process_one_image(job_image_id)

    items = isolated_db.query(Item).filter_by(matter_id=matter_id).all()
    assert len(items) == 1
    crops = isolated_db.query(ItemCrop).all()
    assert len(crops) == 0


def test_process_one_image_marks_error_on_api_failure(matter_with_job, isolated_db, monkeypatch, tmp_path):
    _, job_image_id = matter_with_job
    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    from cvp.services.openrouter import OpenRouterError

    with patch(
        "cvp.services.vision.openrouter.call_vision",
        side_effect=OpenRouterError(429, "rate limit"),
    ):
        vision_svc.process_one_image(job_image_id)

    isolated_db.expire_all()
    ji = isolated_db.get(VisionJobImage, job_image_id)
    assert ji.status == "error"
    assert "429" in ji.error_message


def test_process_skips_already_scanned_file(matter_with_job, isolated_db, monkeypatch, tmp_path):
    _, job_image_id = matter_with_job
    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    ji = isolated_db.get(VisionJobImage, job_image_id)
    ef = isolated_db.get(EvidenceFile, ji.evidence_file_id)
    ef.scanned = True
    isolated_db.commit()

    with patch("cvp.services.vision.openrouter.call_vision") as mock_call:
        vision_svc.process_one_image(job_image_id)
        mock_call.assert_not_called()

    isolated_db.expire_all()
    ji = isolated_db.get(VisionJobImage, job_image_id)
    assert ji.status == "done"
```

- [ ] **Step 5: Run vision service tests**

```bash
source .venv/bin/activate && uv run pytest tests/test_vision_service.py tests/test_vision_downscale.py -v 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 6: Run full suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass (router tests for vision will fail until Task 8 — if so, skip with `-k "not test_vision_router"`).

- [ ] **Step 7: Commit**

```bash
git add src/cvp/services/vision.py tests/test_vision_service.py tests/test_vision_downscale.py
git commit -m "feat: refactor vision service — DB-backed jobs, process_one_image, downscaling"
```

---

### Task 7: Create vision_worker.py idle-stopping worker

**Files:**
- Create: `src/cvp/services/vision_worker.py`
- Create: `tests/test_vision_worker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_vision_worker.py`:

```python
"""Tests for vision_worker — recover, claim, idle-stop behavior."""

import time
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, EvidenceFile, Matter, VisionJob, VisionJobImage


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(Matter(id="m1", policyholder_name="T", loss_type="total_loss"))
    session.add(EvidenceFile(
        id="ef1", matter_id="m1", filename="a.jpg",
        stored_path="/tmp/a.jpg", mime_type="image/jpeg", kind="image", size_bytes=1,
    ))
    session.commit()
    yield session
    session.close()


def _add_job_image(db, status="pending"):
    job = VisionJob(matter_id="m1", model_slug="some/model", status="running")
    db.add(job)
    db.flush()
    ji = VisionJobImage(job_id=job.id, evidence_file_id="ef1", status=status)
    db.add(ji)
    db.commit()
    return ji.id


def test_recover_stale_jobs_resets_running_to_pending(db, monkeypatch):
    from cvp.services import vision_worker
    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    ji_id = _add_job_image(db, status="running")

    vision_worker.recover_stale_jobs()

    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "pending"
    assert ji.started_at is None


def test_recover_leaves_done_rows_unchanged(db, monkeypatch):
    from cvp.services import vision_worker
    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    ji_id = _add_job_image(db, status="done")
    vision_worker.recover_stale_jobs()

    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "done"


def test_claim_next_pending_marks_running(db, monkeypatch):
    from cvp.services import vision_worker
    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    ji_id = _add_job_image(db, status="pending")
    claimed = vision_worker._claim_next_pending()

    assert claimed == ji_id
    db.expire_all()
    ji = db.get(VisionJobImage, ji_id)
    assert ji.status == "running"
    assert ji.started_at is not None


def test_claim_next_pending_returns_none_when_empty(db, monkeypatch):
    from cvp.services import vision_worker
    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    result = vision_worker._claim_next_pending()
    assert result is None


def test_worker_processes_pending_row(db, monkeypatch):
    from cvp.services import vision_worker
    monkeypatch.setattr("cvp.services.vision_worker.SessionLocal", lambda: db)

    processed = []

    def fake_process(job_image_id):
        ji = db.get(VisionJobImage, job_image_id)
        ji.status = "done"
        db.commit()
        processed.append(job_image_id)

    monkeypatch.setattr("cvp.services.vision_worker._process_fn", fake_process)
    monkeypatch.setattr("cvp.services.vision_worker._SLEEP_SECONDS", 0)

    ji_id = _add_job_image(db, status="pending")

    vision_worker.start_worker()
    vision_worker.wake()

    deadline = time.time() + 3.0
    while time.time() < deadline and ji_id not in processed:
        time.sleep(0.05)

    assert ji_id in processed
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && uv run pytest tests/test_vision_worker.py -v 2>&1 | tail -10
```

Expected: `ImportError`.

- [ ] **Step 3: Create `src/cvp/services/vision_worker.py`**

```python
"""Single-threaded vision scan worker. Idles via threading.Event; zero CPU when empty."""

import logging
import threading
import time
from datetime import datetime, timezone

from cvp.db import SessionLocal
from cvp.models import VisionJobImage

logger = logging.getLogger(__name__)

_wake = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()

_SLEEP_SECONDS: float = 0.5  # overridable in tests


def _process_fn(job_image_id: str) -> None:
    """Default process function — swappable in tests via monkeypatch."""
    from cvp.services.vision import process_one_image
    process_one_image(job_image_id)


def wake() -> None:
    """Signal the worker that new work is available."""
    _wake.set()


def recover_stale_jobs() -> None:
    """On startup, reset any rows stuck in 'running' (from a prior crash) to 'pending'."""
    db = SessionLocal()
    try:
        count = (
            db.query(VisionJobImage)
            .filter_by(status="running")
            .update({"status": "pending", "started_at": None})
        )
        db.commit()
        if count > 0:
            logger.info("vision_worker: reset %d stale running rows to pending", count)
    finally:
        db.close()
    wake()


def _claim_next_pending() -> str | None:
    """Atomically claim the oldest pending row; return its ID or None."""
    db = SessionLocal()
    try:
        row = (
            db.query(VisionJobImage)
            .filter_by(status="pending")
            .order_by(VisionJobImage.created_at)
            .first()
        )
        if row is None:
            return None
        row.status = "running"
        row.started_at = datetime.now(timezone.utc)
        db.commit()
        return row.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _loop() -> None:
    while True:
        try:
            job_image_id = _claim_next_pending()
            if job_image_id is None:
                _wake.clear()
                # Re-check after clearing to avoid missing a signal set between the
                # initial claim attempt and the clear.
                job_image_id = _claim_next_pending()
                if job_image_id is None:
                    _wake.wait()
                    continue
            _process_fn(job_image_id)
        except Exception:
            logger.exception("vision_worker: unexpected error in loop")
            time.sleep(1.0)
            continue
        time.sleep(_SLEEP_SECONDS)


def start_worker() -> None:
    """Start the background worker thread if not already running."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, daemon=True, name="vision-worker")
        _thread.start()
```

- [ ] **Step 4: Run worker tests**

```bash
source .venv/bin/activate && uv run pytest tests/test_vision_worker.py -v 2>&1 | tail -15
```

Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass (vision router tests may still fail — acceptable until Task 8).

- [ ] **Step 6: Commit**

```bash
git add src/cvp/services/vision_worker.py tests/test_vision_worker.py
git commit -m "feat: vision_worker idle-stopping worker thread with tests"
```

---

### Task 8: Update vision router — DB-backed start_scan, poll_scan, new scan-all

**Files:**
- Modify: `src/cvp/routers/vision.py`
- Modify: `tests/test_vision_router.py`
- Create: `tests/test_vision_scan_all.py`

- [ ] **Step 1: Rewrite `src/cvp/routers/vision.py`**

```python
"""Vision scan endpoints — start scan, poll progress, estimate cost."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import EvidenceFile, VisionJob, VisionJobImage
from cvp.models_auth import User
from cvp.models_vision import VisionModel
from cvp.services import vision as vision_svc
from cvp.services import vision_worker
from cvp.services.audit import get_client_ip, write_audit_log

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()

_SCAN_ALL_CAP = 250


@router.post("/api/matters/{matter_id}/vision-scan", response_class=HTMLResponse)
async def start_scan(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("contributor")),
    evidence_file_ids: list[str] = Form(default=[]),
    model_slug: str = Form(...),
) -> HTMLResponse:
    if not evidence_file_ids:
        return HTMLResponse(
            '<p class="text-sm text-red-600">Select at least one image to scan.</p>'
        )

    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug, is_enabled=True).first()
        if vm is None:
            raise HTTPException(400, f"unknown or disabled vision model: {model_slug}")

        files = (
            db.query(EvidenceFile)
            .filter(
                EvidenceFile.id.in_(evidence_file_ids),
                EvidenceFile.matter_id == matter_id,
                EvidenceFile.kind == "image",
            )
            .all()
        )
        if not files:
            return HTMLResponse('<p class="text-sm text-red-600">No image files selected.</p>')

        u = db.query(User).filter_by(id=user.id).first()
        if u is not None:
            u.last_vision_model_slug = model_slug

        job = VisionJob(
            matter_id=matter_id,
            model_slug=model_slug,
            status="running",
            created_by_user_id=user.id,
        )
        db.add(job)
        db.flush()
        for ef in files:
            db.add(VisionJobImage(job_id=job.id, evidence_file_id=ef.id))
        db.commit()
        job_id = job.id
    finally:
        db.close()

    vision_worker.wake()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="vision.run",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
        detail=f"model={model_slug}",
    )
    job_data = vision_svc.get_job_data(job_id)
    return HTMLResponse(
        templates.get_template("_scan_progress.html").render(
            job_id=job_id, matter_id=matter_id, **job_data
        )
    )


@router.post("/api/matters/{matter_id}/vision-scan-all", response_class=HTMLResponse)
async def start_scan_all(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("contributor")),
    model_slug: str = Form(...),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        vm = db.query(VisionModel).filter_by(slug=model_slug, is_enabled=True).first()
        if vm is None:
            raise HTTPException(400, f"unknown or disabled vision model: {model_slug}")

        files = (
            db.query(EvidenceFile)
            .filter_by(matter_id=matter_id, kind="image", scanned=False)
            .order_by(EvidenceFile.created_at)
            .all()
        )
        if not files:
            return HTMLResponse(
                '<p class="text-sm text-gray-500">No unscanned images found.</p>'
            )
        if len(files) > _SCAN_ALL_CAP:
            return HTMLResponse(
                f'<p class="text-sm text-red-600">Too many unscanned images ({len(files)}). '
                f"Maximum per job is {_SCAN_ALL_CAP}. Scan in batches.</p>"
            )

        u = db.query(User).filter_by(id=user.id).first()
        if u is not None:
            u.last_vision_model_slug = model_slug

        job = VisionJob(
            matter_id=matter_id,
            model_slug=model_slug,
            status="running",
            created_by_user_id=user.id,
        )
        db.add(job)
        db.flush()
        for ef in files:
            db.add(VisionJobImage(job_id=job.id, evidence_file_id=ef.id))
        db.commit()
        job_id = job.id
        n_files = len(files)
    finally:
        db.close()

    vision_worker.wake()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="vision.run_all",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
        detail=f"model={model_slug} count={n_files}",
    )
    job_data = vision_svc.get_job_data(job_id)
    return HTMLResponse(
        templates.get_template("_scan_progress.html").render(
            job_id=job_id, matter_id=matter_id, **job_data
        )
    )


@router.get("/api/matters/{matter_id}/vision-scan/{job_id}", response_class=HTMLResponse)
def poll_scan(
    matter_id: str,
    job_id: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    job_data = vision_svc.get_job_data(job_id)
    if job_data["status"] == "error" and job_data["total"] == 0:
        return HTMLResponse('<p class="text-sm text-red-600">Scan job not found.</p>')
    return HTMLResponse(
        templates.get_template("_scan_progress.html").render(
            job_id=job_id, matter_id=matter_id, **job_data
        )
    )


@router.get("/api/matters/{matter_id}/vision-scan-estimate", response_class=HTMLResponse)
def estimate(
    matter_id: str,
    count: int,
    model_slug: str,
    user: CurrentUser = Depends(require_matter_role("contributor")),
) -> HTMLResponse:
    label = vision_svc.estimate_cost(count, model_slug)
    return HTMLResponse(f'<span id="cost-estimate" class="text-xs text-gray-500">{label}</span>')
```

- [ ] **Step 2: Update `tests/test_vision_router.py`**

Replace the file with:

```python
"""Tests for vision scan router — model validation, last-used recording, cost estimate."""

import inspect
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
import cvp.routers.vision as vision_router
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, EvidenceFile, Matter, VisionJob, VisionJobImage
from cvp.models_auth import User
from cvp.models_vision import VisionModel

CONTRIBUTOR_EMAIL = "contrib@test.com"
CONTRIBUTOR_ID = "contrib-id"
MATTER_ID = "matter-123"
FILE_ID = "file-456"


def _dep(fn):
    return inspect.signature(fn).parameters["user"].default.dependency


_start_scan_dep = _dep(vision_router.start_scan)
_start_scan_all_dep = _dep(vision_router.start_scan_all)
_poll_scan_dep = _dep(vision_router.poll_scan)
_estimate_dep = _dep(vision_router.estimate)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(VisionModel(
        slug="anthropic/claude-opus-4", display_name="Claude Opus 4",
        adapter="pixel_passthrough", supports_bbox=True,
        is_default=True, is_enabled=True, recommended=True, prompt_image_cost_cents=3,
    ))
    db.add(User(id=CONTRIBUTOR_ID, email=CONTRIBUTOR_EMAIL, display_name="C", system_role="internal_user"))
    db.add(Matter(id=MATTER_ID, policyholder_name="Owner", loss_type="total_loss"))
    tmp = tempfile.mktemp(suffix=".jpg")
    PILImage.new("RGB", (200, 200), "white").save(tmp)
    db.add(EvidenceFile(
        id=FILE_ID, matter_id=MATTER_ID, filename="test.jpg",
        stored_path=tmp, mime_type="image/jpeg", kind="image",
        size_bytes=os.path.getsize(tmp),
    ))
    db.commit()
    yield db
    db.close()


@pytest.fixture
def client_contributor(db_session):
    async def mock_contributor():
        return CurrentUser(
            id=CONTRIBUTOR_ID, email=CONTRIBUTOR_EMAIL,
            system_role="internal_user", group_id=None, group_kind="internal",
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[_start_scan_dep] = mock_contributor
    app.dependency_overrides[_start_scan_all_dep] = mock_contributor
    app.dependency_overrides[_poll_scan_dep] = mock_contributor
    app.dependency_overrides[_estimate_dep] = mock_contributor
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_start_scan_rejects_unknown_model(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.services.vision_worker.wake", lambda: None)
    resp = client_contributor.post(
        f"/api/matters/{MATTER_ID}/vision-scan",
        data={"evidence_file_ids": FILE_ID, "model_slug": "made/up"},
    )
    assert resp.status_code == 400


def test_start_scan_records_last_used_and_creates_job(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.services.vision_worker.wake", lambda: None)
    resp = client_contributor.post(
        f"/api/matters/{MATTER_ID}/vision-scan",
        data={"evidence_file_ids": FILE_ID, "model_slug": "anthropic/claude-opus-4"},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    u = db_session.query(User).filter_by(id=CONTRIBUTOR_ID).one()
    assert u.last_vision_model_slug == "anthropic/claude-opus-4"

    jobs = db_session.query(VisionJob).filter_by(matter_id=MATTER_ID).all()
    assert len(jobs) == 1
    images = db_session.query(VisionJobImage).filter_by(job_id=jobs[0].id).all()
    assert len(images) == 1


def test_cost_estimate_endpoint(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: db_session)
    resp = client_contributor.get(
        f"/api/matters/{MATTER_ID}/vision-scan-estimate?count=4&model_slug=anthropic/claude-opus-4"
    )
    assert resp.status_code == 200
    assert "0.12" in resp.text
```

- [ ] **Step 3: Create `tests/test_vision_scan_all.py`**

```python
"""Tests for POST /api/matters/{matter_id}/vision-scan-all."""

import inspect
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
import cvp.routers.vision as vision_router
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, EvidenceFile, Matter, VisionJob, VisionJobImage
from cvp.models_auth import User
from cvp.models_vision import VisionModel

CONTRIBUTOR_ID = "contrib-sa"
MATTER_ID = "matter-sa"
FILE_ID = "file-sa"


def _dep(fn):
    return inspect.signature(fn).parameters["user"].default.dependency


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(VisionModel(
        slug="anthropic/claude-opus-4", display_name="Claude Opus 4",
        adapter="pixel_passthrough", supports_bbox=True,
        is_default=True, is_enabled=True, recommended=True,
    ))
    db.add(User(id=CONTRIBUTOR_ID, email="c@t.com", display_name="C", system_role="internal_user"))
    db.add(Matter(id=MATTER_ID, policyholder_name="Owner", loss_type="total_loss"))
    tmp = tempfile.mktemp(suffix=".jpg")
    PILImage.new("RGB", (10, 10), "white").save(tmp)
    db.add(EvidenceFile(
        id=FILE_ID, matter_id=MATTER_ID, filename="test.jpg",
        stored_path=tmp, mime_type="image/jpeg", kind="image",
        size_bytes=os.path.getsize(tmp), scanned=False,
    ))
    db.commit()
    yield db
    db.close()


@pytest.fixture
def client_contributor(db_session):
    async def mock_contrib():
        return CurrentUser(
            id=CONTRIBUTOR_ID, email="c@t.com",
            system_role="internal_user", group_id=None, group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = _dep(vision_router.start_scan_all)
    app.dependency_overrides[dep] = mock_contrib
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_scan_all_creates_job_for_unscanned(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.services.vision_worker.wake", lambda: None)

    resp = client_contributor.post(
        f"/api/matters/{MATTER_ID}/vision-scan-all",
        data={"model_slug": "anthropic/claude-opus-4"},
    )
    assert resp.status_code == 200

    jobs = db_session.query(VisionJob).filter_by(matter_id=MATTER_ID).all()
    assert len(jobs) == 1
    images = db_session.query(VisionJobImage).filter_by(job_id=jobs[0].id).all()
    assert len(images) == 1
    assert images[0].evidence_file_id == FILE_ID


def test_scan_all_returns_empty_message_when_nothing_to_scan(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.services.vision_worker.wake", lambda: None)

    ef = db_session.get(EvidenceFile, FILE_ID)
    ef.scanned = True
    db_session.commit()

    resp = client_contributor.post(
        f"/api/matters/{MATTER_ID}/vision-scan-all",
        data={"model_slug": "anthropic/claude-opus-4"},
    )
    assert resp.status_code == 200
    assert "No unscanned" in resp.text


def test_scan_all_rejects_over_cap(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.services.vision_worker.wake", lambda: None)
    monkeypatch.setattr("cvp.routers.vision._SCAN_ALL_CAP", 2)

    for i in range(3):
        db_session.add(EvidenceFile(
            matter_id=MATTER_ID, filename=f"extra_{i}.jpg",
            stored_path=f"/tmp/fake_{i}.jpg", mime_type="image/jpeg",
            kind="image", size_bytes=100, scanned=False,
        ))
    db_session.commit()

    resp = client_contributor.post(
        f"/api/matters/{MATTER_ID}/vision-scan-all",
        data={"model_slug": "anthropic/claude-opus-4"},
    )
    assert resp.status_code == 200
    assert "Too many" in resp.text
```

- [ ] **Step 4: Run all vision router tests**

```bash
source .venv/bin/activate && uv run pytest tests/test_vision_router.py tests/test_vision_scan_all.py -v 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/routers/vision.py tests/test_vision_router.py tests/test_vision_scan_all.py
git commit -m "feat: update vision router — DB-backed jobs, scan-all endpoint"
```

---

### Task 9: Wire up lifespan startup and matter_detail context

**Files:**
- Modify: `src/cvp/main.py`
- Modify: `src/cvp/routers/matters.py`

- [ ] **Step 1: Add lifespan startup to `main.py`**

In `src/cvp/main.py`, add the lifespan import and function, then pass it to `FastAPI`:

Add to imports:
```python
from contextlib import asynccontextmanager
from cvp.services import vision_worker
```

Add before `app = FastAPI(...)`:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    vision_worker.recover_stale_jobs()
    vision_worker.start_worker()
    yield
```

Change:
```python
app = FastAPI(title="Contents Valuation Platform")
```
to:
```python
app = FastAPI(title="Contents Valuation Platform", lifespan=lifespan)
```

- [ ] **Step 2: Add scan_errors and latest_scan_job to the matter_detail route**

In `src/cvp/routers/matters.py`, add to imports:
```python
from cvp.models import Category, Item, Matter, VisionJob, VisionJobImage
```

Inside the `matter_detail` route, after the existing evidence/vision queries (around line 150, before `db.close()`), add:

```python
        # Scan error badges per image card
        scan_errors: dict[str, str] = {}
        error_rows = (
            db.query(VisionJobImage.evidence_file_id, VisionJobImage.error_message)
            .join(VisionJob, VisionJobImage.job_id == VisionJob.id)
            .filter(
                VisionJob.matter_id == matter_id,
                VisionJobImage.status == "error",
            )
            .order_by(VisionJobImage.created_at.asc())
            .all()
        )
        for row in error_rows:
            if row.error_message:
                scan_errors[row.evidence_file_id] = row.error_message

        # Banner for latest completed job with errors
        latest_scan_job: dict | None = None
        latest_job = (
            db.query(VisionJob)
            .filter(
                VisionJob.matter_id == matter_id,
                VisionJob.status.in_(["done", "error"]),
            )
            .order_by(VisionJob.created_at.desc())
            .first()
        )
        if latest_job:
            job_images = db.query(VisionJobImage).filter_by(job_id=latest_job.id).all()
            error_count = sum(1 for i in job_images if i.status == "error")
            if error_count > 0:
                latest_scan_job = {
                    "job_id": latest_job.id,
                    "total": len(job_images),
                    "success_count": sum(1 for i in job_images if i.status == "done"),
                    "error_count": error_count,
                }
```

Add `scan_errors` and `latest_scan_job` to the template context dict:
```python
            "scan_errors": scan_errors,
            "latest_scan_job": latest_scan_job,
```

- [ ] **Step 3: Run full suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/cvp/main.py src/cvp/routers/matters.py
git commit -m "feat: wire vision_worker startup and add scan context to matter_detail"
```

---

### Task 10: Update templates and app.js

**Files:**
- Modify: `src/cvp/templates/_tab_evidence.html`
- Modify: `src/cvp/templates/_evidence_grid.html`
- Modify: `src/cvp/static/app.js`

- [ ] **Step 1: Update `_tab_evidence.html` — add bulk action bar and banner**

Replace the entire file contents of `src/cvp/templates/_tab_evidence.html` with:

```html
<div class="space-y-4">

  <!-- Upload zone -->
  <form id="evidence-form"
        hx-post="/api/matters/{{ matter.id }}/evidence"
        hx-target="#evidence-grid"
        hx-swap="outerHTML"
        hx-encoding="multipart/form-data">
    <div id="drop-zone"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white px-6 py-10 text-center transition-colors hover:border-indigo-400 cursor-pointer">
      <svg class="mx-auto mb-3 h-10 w-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/>
      </svg>
      <p class="text-sm font-medium text-gray-600">Drop files here or <span class="text-indigo-600">browse</span></p>
      <p class="mt-1 text-xs text-gray-400">Photos, PDFs, videos — any file type accepted</p>
      <input id="evidence-input" name="files" type="file" multiple class="hidden">
    </div>
  </form>

  {% set image_files = evidence_files | selectattr("kind", "equalto", "image") | list %}
  {% set unscanned_files = image_files | rejectattr("scanned") | list %}
  {% set image_count = image_files | length %}
  {% set unscanned_count = unscanned_files | length %}

  <!-- Scan-errors banner for most recent completed bulk job -->
  {% if latest_scan_job is defined and latest_scan_job %}
  <div id="scan-banner-{{ latest_scan_job.job_id }}"
       data-job-id="{{ latest_scan_job.job_id }}"
       class="rounded-lg border border-amber-200 bg-amber-50 p-3 flex items-start justify-between gap-2">
    <div>
      <p class="text-sm font-medium text-amber-800">
        Last bulk scan: {{ latest_scan_job.success_count }} of {{ latest_scan_job.total }} succeeded,
        {{ latest_scan_job.error_count }} failed.
      </p>
      <p class="text-xs text-amber-700 mt-0.5">Failed images show details below — click Scan Now to retry.</p>
    </div>
    <button onclick="dismissScanBanner('{{ latest_scan_job.job_id }}')"
            class="shrink-0 text-amber-500 hover:text-amber-700 text-lg leading-none">✕</button>
  </div>
  {% endif %}

  <!-- Bulk action bar -->
  {% if image_count > 0 %}
  <div class="flex flex-wrap items-center gap-3">
    {% if unscanned_count > 0 %}
    <form hx-post="/api/matters/{{ matter.id }}/vision-scan-all"
          hx-target="#scan-all-progress"
          hx-swap="innerHTML"
          hx-include="#model_slug">
      <button type="submit"
              class="rounded border border-violet-200 px-3 py-1.5 text-sm text-violet-700 hover:bg-violet-50">
        Scan all unscanned ({{ unscanned_count }})
      </button>
    </form>
    {% endif %}
    <button type="button"
            onclick="confirmRemoveAll({{ image_count }})"
            class="rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50">
      Remove all images ({{ image_count }})
    </button>
    <form id="remove-all-form"
          hx-post="/api/matters/{{ matter.id }}/evidence/remove-all-images"
          hx-target="#evidence-grid"
          hx-swap="outerHTML">
      <input type="hidden" name="confirm_count" id="remove-all-confirm-count" value="0">
    </form>
  </div>
  {% endif %}

  <!-- Scan-all progress area -->
  <div id="scan-all-progress"></div>

  <!-- File grid -->
  {% set matter_id = matter.id %}
  {% include "_evidence_grid.html" %}
</div>
```

- [ ] **Step 2: Update `_evidence_grid.html` — add per-card error badge**

Replace the per-image card scan section. Find this block in `_evidence_grid.html`:

```html
      {% if f.kind == "image" %}
        {% if f.scanned %}
        <button data-toggle-crop-editor="{{ f.id }}"
                class="mt-1 rounded border border-indigo-200 px-1.5 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50">
          Edit crops
        </button>
        {% else %}
        <form hx-post="/api/matters/{{ matter_id }}/vision-scan"
              hx-target="#scan-progress-{{ f.id }}"
              hx-include="#model_slug"
              hx-swap="innerHTML"
              class="mt-1">
          <input type="hidden" name="evidence_file_ids" value="{{ f.id }}">
          <button type="submit"
                  class="rounded border border-violet-200 px-1.5 py-0.5 text-xs text-violet-600 hover:bg-violet-50">
            Scan Now
          </button>
        </form>
        <div id="scan-progress-{{ f.id }}"></div>
        {% endif %}
      {% endif %}
```

Replace it with:

```html
      {% if f.kind == "image" %}
        {% if f.scanned %}
        <button data-toggle-crop-editor="{{ f.id }}"
                class="mt-1 rounded border border-indigo-200 px-1.5 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50">
          Edit crops
        </button>
        {% else %}
        <form hx-post="/api/matters/{{ matter_id }}/vision-scan"
              hx-target="#scan-progress-{{ f.id }}"
              hx-include="#model_slug"
              hx-swap="innerHTML"
              class="mt-1">
          <input type="hidden" name="evidence_file_ids" value="{{ f.id }}">
          <button type="submit"
                  class="rounded border border-violet-200 px-1.5 py-0.5 text-xs text-violet-600 hover:bg-violet-50">
            Scan Now
          </button>
        </form>
        {% if scan_errors is defined and f.id in scan_errors %}
        <p class="mt-0.5 truncate text-xs text-red-600"
           title="{{ scan_errors[f.id] }}">
          Scan failed: {{ scan_errors[f.id][:60] }}
        </p>
        {% endif %}
        <div id="scan-progress-{{ f.id }}"></div>
        {% endif %}
      {% endif %}
```

- [ ] **Step 3: Add JS helper functions to `src/cvp/static/app.js`**

Append to the end of `src/cvp/static/app.js`:

```js
// ── Bulk evidence actions ────────────────────────────────────────────────

function confirmRemoveAll(count) {
  var input = prompt(
    'This will permanently remove all ' + count + ' images and their scanned items.\n' +
    'Type ' + count + ' to confirm:'
  );
  if (input !== null && parseInt(input, 10) === count) {
    document.getElementById('remove-all-confirm-count').value = count;
    htmx.trigger(document.getElementById('remove-all-form'), 'submit');
  }
}

function dismissScanBanner(jobId) {
  try { sessionStorage.setItem('dismissed_banner_' + jobId, '1'); } catch (_) {}
  var el = document.getElementById('scan-banner-' + jobId);
  if (el) el.remove();
}

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-job-id]').forEach(function (el) {
    var jobId = el.dataset.jobId;
    try {
      if (sessionStorage.getItem('dismissed_banner_' + jobId)) el.remove();
    } catch (_) {}
  });
});
```

- [ ] **Step 4: Run full test suite**

```bash
source .venv/bin/activate && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 5: Lint**

```bash
source .venv/bin/activate && uv run ruff check . && uv run ruff format --check . 2>&1 | tail -10
```

Fix any issues with `uv run ruff format .` then re-check.

- [ ] **Step 6: Commit**

```bash
git add src/cvp/templates/_tab_evidence.html src/cvp/templates/_evidence_grid.html src/cvp/static/app.js
git commit -m "feat: bulk scan/remove UI — scan-all button, remove-all confirm, error badges, banner"
```

---

### Task 11: Push branch and open PR

**Files:** none

- [ ] **Step 1: Run final full test suite and lint**

```bash
source .venv/bin/activate && uv run pytest tests/ -q 2>&1 | tail -10
source .venv/bin/activate && uv run ruff check . 2>&1 | tail -5
```

Expected: all tests pass, no lint errors.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/bulk-evidence-scan-and-remove
```

- [ ] **Step 3: Open PR**

```bash
gh pr create \
  --title "feat: bulk evidence scan and remove" \
  --body "$(cat <<'EOF'
## Summary

- Adds **Scan all unscanned** and **Remove all images** bulk actions to the evidence tab
- Replaces fragile in-memory `_jobs` dict with DB-backed `vision_jobs` + `vision_job_images` tables; scan progress now survives Railway worker restarts and page refreshes
- Single idle-stopping worker thread (`threading.Event`) processes images sequentially with 500ms pause (CLAUDE.md rule #8); zero CPU when queue is empty
- Images >1 MB are downscaled to long-edge 1568px before vision API call; bbox coordinates scaled back to original dimensions for crop storage
- Evidence delete (single and bulk) now cascades to orphaned Items, ItemCrops, and crop files on disk — fixes a latent bug where deleting an image left orphan Item rows
- Per-card scan failure badge and dismissible matter-level banner surface errors that persist across page reloads

## Test plan

- [ ] All new services have unit tests (`test_vision_worker`, `test_evidence_cleanup`, `test_vision_downscale`)
- [ ] Router tests updated for new DB-backed API (`test_vision_router`, `test_vision_scan_all`, `test_evidence_remove_all`)
- [ ] Full suite passes: `uv run pytest tests/ -q`
- [ ] Manual: upload 3+ images to a matter, click "Scan all unscanned", verify progress bar and items created
- [ ] Manual: click "Remove all images", type count, verify images + items deleted, PDFs untouched
- [ ] Manual: simulate scan failure (disconnect network), verify error badge appears on card after page reload

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Note the PR URL**

Copy the URL printed by `gh pr create` and share it.
