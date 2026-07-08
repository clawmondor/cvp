"""Integration test for the crop-editor route's modal markup."""

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
    db.add(Claim(id="m1", policyholder_name="Test"))
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
