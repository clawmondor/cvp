"""Integration tests for crops router."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import claimos.dependencies as deps
from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_active_user
from claimos.models import Base, Category, Claim, EvidenceFile, Item, ItemCrop


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
    engine = create_engine(
        f"sqlite:///{tmp_base}/test.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    db.add(Category(id=1, name="Test", useful_life_years=10, acv_floor_pct=0.20))
    db.add(Claim(id="m1", policyholder_name="Test", nickname="Test Claim"))
    db.add(
        EvidenceFile(
            id="ef1",
            claim_id="m1",
            filename="photo.jpg",
            stored_path="ef1/photo.jpg",
            kind="image",
            scanned=True,
        )
    )
    db.add(Item(id="item1", claim_id="m1", category_id=1, line_number=1, description="Lamp"))
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
    import claimos.routers.crops as crops_mod

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
        patch("claimos.config.settings.upload_dir", str(tmp_base / "uploads")),
        patch("claimos.config.settings.crop_dir", str(tmp_base / "crops")),
        patch.object(deps, "_check_claim_access", return_value=True),
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
