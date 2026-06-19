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
    db.add(
        Category(
            id=1,
            name="Miscellaneous household goods",
            useful_life_years=8,
            acv_floor_pct=0.20,
        )
    )
    db.add(
        Category(
            id=21,
            name="Electronics, TVs and displays",
            useful_life_years=7,
            acv_floor_pct=0.20,
        )
    )
    db.add(
        VisionModel(
            slug="anthropic/claude-opus-4",
            display_name="Claude Opus 4",
            adapter="pixel_passthrough",
            supports_bbox=True,
            is_default=True,
            is_enabled=True,
            recommended=True,
        )
    )
    db.add(
        VisionModel(
            slug="openai/gpt-4o",
            display_name="GPT-4o",
            adapter="none",
            supports_bbox=False,
            is_default=False,
            is_enabled=True,
            recommended=False,
        )
    )
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
        type(
            "S",
            (),
            {
                "upload_dir": str(tmp_path),
                "crop_dir": str(tmp_path),
                "openrouter_api_key": "test-key",
                "openrouter_referer": "",
                "openrouter_app_title": "",
            },
        )(),
    )


def test_process_one_image_creates_items_and_crops(
    matter_with_job, isolated_db, monkeypatch, tmp_path
):
    matter_id, job_image_id = matter_with_job
    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    fake_response = json.dumps(
        [
            {
                "description": "Samsung 65-inch QLED TV",
                "brand": "Samsung",
                "model": "QN65Q80C",
                "category_hint": "Electronics, TVs and displays",
                "quantity": 1,
                "condition": "average",
                "search_hint": "Samsung 65 QLED QN65Q80C",
                "room_hint": "Living Room",
                "confidence": "high",
                "bounding_box": [10, 10, 100, 100],
            }
        ]
    )

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

    isolated_db.expire_all()
    ji = isolated_db.get(VisionJobImage, job_image_id)
    job = isolated_db.get(VisionJob, ji.job_id)
    assert job.status == "done"


def test_process_one_image_releases_connection_during_api_call(
    matter_with_job, isolated_db, monkeypatch, tmp_path
):
    """Regression: the worker held a DB transaction across the OpenRouter HTTP
    call, pegging a pool slot for the full ~30s API duration. Under bulk-scan
    load this exhausted the 5+5 Postgres pool. The fix commits before the API
    call so the connection returns to the pool during the request."""
    _, job_image_id = matter_with_job
    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    in_tx_at_call: list[bool] = []

    def _capture_tx_state(**_kwargs) -> str:
        in_tx_at_call.append(isolated_db.in_transaction())
        return "[]"

    with patch("cvp.services.vision.openrouter.call_vision", side_effect=_capture_tx_state):
        vision_svc.process_one_image(job_image_id)

    assert in_tx_at_call == [False], (
        "process_one_image must commit before openrouter.call_vision so the "
        "DB connection is released to the pool during the API call"
    )


def test_process_one_image_skips_crop_when_adapter_none(
    matter_with_job, isolated_db, monkeypatch, tmp_path
):
    matter_id, job_image_id = matter_with_job
    ji = isolated_db.get(VisionJobImage, job_image_id)
    job = isolated_db.get(VisionJob, ji.job_id)
    job.model_slug = "openai/gpt-4o"
    isolated_db.commit()

    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    fake_response = json.dumps(
        [
            {
                "description": "Coffee table",
                "category_hint": "Miscellaneous household goods",
                "quantity": 1,
                "condition": "average",
            }
        ]
    )

    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response):
        vision_svc.process_one_image(job_image_id)

    items = isolated_db.query(Item).filter_by(matter_id=matter_id).all()
    assert len(items) == 1
    crops = isolated_db.query(ItemCrop).all()
    assert len(crops) == 0


def test_process_one_image_marks_error_on_api_failure(
    matter_with_job, isolated_db, monkeypatch, tmp_path
):
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


def test_estimate_cost_known_model(isolated_db, monkeypatch):
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: isolated_db)
    # Seed has null pricing -> should return "~$?"
    result = vision_svc.estimate_cost(3, "anthropic/claude-opus-4")
    assert result == "~$?"


def test_estimate_cost_with_pricing(isolated_db, monkeypatch):
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: isolated_db)
    isolated_db.query(VisionModel).filter_by(slug="anthropic/claude-opus-4").update(
        {"prompt_image_cost_cents": 3}
    )
    isolated_db.commit()
    result = vision_svc.estimate_cost(4, "anthropic/claude-opus-4")
    assert result == "~$0.12"  # 4 * 3 cents = 12 cents


def test_estimate_cost_unknown_model(isolated_db, monkeypatch):
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: isolated_db)
    result = vision_svc.estimate_cost(1, "unknown/model")
    assert result == "~$?"


def test_region_scan_uses_drawn_region_as_crop(isolated_db, monkeypatch, tmp_path):
    """A region scan ignores the model's per-item bounding box and uses the
    user-drawn region as the crop bbox, so no second model-derived box appears
    on the image. It must run even when the file is already marked scanned."""
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
    matter_id = matter.id  # capture before session is closed by process_one_image

    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    # The model returns a small partial box inside the crop; the worker must
    # ignore it and use the full drawn region (100, 100, 300, 300) as the crop.
    fake_response = json.dumps(
        [
            {
                "description": "Floor lamp",
                "category_hint": "Miscellaneous household goods",
                "quantity": 1,
                "condition": "average",
                "bounding_box": [10, 10, 60, 60],
            }
        ]
    )

    with patch(
        "cvp.services.vision.openrouter.call_vision", return_value=fake_response
    ) as mock_call:
        vision_svc.process_one_image(ji_id)
        mock_call.assert_called_once()

    items = isolated_db.query(Item).filter_by(matter_id=matter_id).all()
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


def test_region_scan_crop_equals_region_regardless_of_model_box(isolated_db, monkeypatch, tmp_path):
    """Even when the model reports several boxes far from the drawn region, every
    item from a region scan gets the drawn region as its crop bbox."""
    from PIL import Image

    img_path = tmp_path / "big.jpg"
    Image.new("RGB", (800, 800), color="white").save(img_path)

    matter = Matter(policyholder_name="Owner", loss_type="total_loss")
    isolated_db.add(matter)
    isolated_db.flush()
    matter_id = matter.id

    ef = EvidenceFile(
        matter_id=matter_id,
        filename="big.jpg",
        stored_path=str(img_path),
        mime_type="image/jpeg",
        kind="image",
        size_bytes=img_path.stat().st_size,
    )
    isolated_db.add(ef)
    isolated_db.flush()

    job = VisionJob(matter_id=matter_id, model_slug="anthropic/claude-opus-4", status="running")
    isolated_db.add(job)
    isolated_db.flush()
    region = (300, 300, 500, 500)
    ji = VisionJobImage(
        job_id=job.id,
        evidence_file_id=ef.id,
        status="running",
        region_left=region[0],
        region_upper=region[1],
        region_right=region[2],
        region_lower=region[3],
    )
    isolated_db.add(ji)
    isolated_db.commit()
    ji_id = ji.id

    _monkeypatch_vision(monkeypatch, isolated_db, tmp_path)

    # Two items with different model boxes; both must end up cropped to `region`.
    fake_response = json.dumps(
        [
            {
                "description": "Table lamp",
                "category_hint": "Miscellaneous household goods",
                "quantity": 1,
                "condition": "average",
                "bounding_box": [0, 0, 40, 40],
            },
            {
                "description": "Picture frame",
                "category_hint": "Miscellaneous household goods",
                "quantity": 1,
                "condition": "average",
                "bounding_box": [150, 150, 200, 200],
            },
        ]
    )

    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response):
        vision_svc.process_one_image(ji_id)

    crops = (
        isolated_db.query(ItemCrop)
        .join(Item, ItemCrop.item_id == Item.id)
        .filter(Item.matter_id == matter_id)
        .all()
    )
    assert len(crops) == 2
    for crop in crops:
        assert (crop.bbox_left, crop.bbox_upper, crop.bbox_right, crop.bbox_lower) == region
