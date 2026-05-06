"""Integration tests for vision.run_scan — OpenRouter mocked."""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, EvidenceFile, Item, ItemCrop, VisionRun
from cvp.models_vision import VisionModel
from cvp.services import vision as vision_svc


@pytest.fixture
def isolated_db(tmp_path):
    """In-memory DB with all tables + a seeded VisionModel and Category."""
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
def matter_with_image(isolated_db, tmp_path):
    """Inserts a Matter + EvidenceFile + tiny JPEG on disk. Returns (matter_id, file_id)."""
    from PIL import Image

    from cvp.models import Matter

    # Create tiny test image
    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (200, 200), color="white").save(img_path)

    matter = Matter(
        policyholder_name="Test Owner",
        loss_type="total_loss",
    )
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
    isolated_db.commit()
    return matter.id, ef.id


def test_run_scan_creates_items_and_crops(matter_with_image, isolated_db, monkeypatch, tmp_path):
    matter_id, file_id = matter_with_image

    # Patch SessionLocal to return our isolated_db session
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: isolated_db)
    # Point crop_dir to tmp_path so recrop_item_crop can write files
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

    job_id = vision_svc.create_job([file_id])
    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response):
        vision_svc.run_scan(job_id, matter_id, [file_id], "anthropic/claude-opus-4")

    items = isolated_db.query(Item).filter_by(matter_id=matter_id).all()
    assert len(items) == 1
    assert items[0].description == "Samsung 65-inch QLED TV"

    crops = isolated_db.query(ItemCrop).filter_by(item_id=items[0].id).all()
    assert len(crops) == 1

    runs = isolated_db.query(VisionRun).filter_by(matter_id=matter_id).all()
    assert len(runs) == 1
    assert runs[0].model == "anthropic/claude-opus-4"
    assert runs[0].adapter == "pixel_passthrough"


def test_run_scan_skips_crop_when_adapter_none(
    matter_with_image, isolated_db, monkeypatch, tmp_path
):
    matter_id, file_id = matter_with_image
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

    fake_response = json.dumps(
        [
            {
                "description": "Anything",
                "category_hint": "Miscellaneous household goods",
                "quantity": 1,
                "condition": "average",
                "bounding_box": [0, 0, 100, 100],
            }
        ]
    )

    job_id = vision_svc.create_job([file_id])
    with patch("cvp.services.vision.openrouter.call_vision", return_value=fake_response):
        vision_svc.run_scan(job_id, matter_id, [file_id], "openai/gpt-4o")

    items = isolated_db.query(Item).filter_by(matter_id=matter_id).all()
    assert len(items) == 1
    crops = isolated_db.query(ItemCrop).filter_by(item_id=items[0].id).all()
    assert len(crops) == 0  # adapter=none -> no crop


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
