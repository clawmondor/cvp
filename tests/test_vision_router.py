"""Tests for vision scan router — model_slug validation and cost estimate."""

import inspect
import os
import tempfile
from unittest.mock import patch

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
from cvp.models import Base, EvidenceFile, Matter
from cvp.models_auth import User
from cvp.models_vision import VisionModel

CONTRIBUTOR_EMAIL = "contrib@test.com"
CONTRIBUTOR_ID = "contrib-id"
MATTER_ID = "matter-123"
FILE_ID = "file-456"

# The dependency function instance actually registered on the router endpoints.
# require_matter_role() is a factory — each call returns a NEW closure, so we
# must grab the exact object that was wired into start_scan / poll_scan /
# estimate to use as the override key.
def _dep(fn: object) -> object:
    return inspect.signature(fn).parameters["user"].default.dependency  # type: ignore[union-attr]


_start_scan_user_dep = _dep(vision_router.start_scan)
_poll_scan_user_dep = _dep(vision_router.poll_scan)
_estimate_user_dep = _dep(vision_router.estimate)


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

    # Seed vision model
    db.add(
        VisionModel(
            slug="anthropic/claude-opus-4",
            display_name="Claude Opus 4",
            adapter="pixel_passthrough",
            supports_bbox=True,
            is_default=True,
            is_enabled=True,
            recommended=True,
            prompt_image_cost_cents=3,
        )
    )
    # Seed user
    db.add(
        User(
            id=CONTRIBUTOR_ID,
            email=CONTRIBUTOR_EMAIL,
            display_name="Contributor",
            system_role="internal_user",
        )
    )
    # Seed matter
    db.add(
        Matter(
            id=MATTER_ID,
            policyholder_name="Test Owner",
            loss_type="total_loss",
        )
    )
    # Seed evidence file — write a tiny real JPEG so the scan path can open it
    tmp = tempfile.mktemp(suffix=".jpg")
    PILImage.new("RGB", (200, 200), "white").save(tmp)
    db.add(
        EvidenceFile(
            id=FILE_ID,
            matter_id=MATTER_ID,
            filename="test.jpg",
            stored_path=tmp,
            mime_type="image/jpeg",
            kind="image",
            size_bytes=os.path.getsize(tmp),
        )
    )
    db.commit()
    yield db
    db.close()


@pytest.fixture
def client_contributor(db_session):
    async def mock_contributor():
        return CurrentUser(
            id=CONTRIBUTOR_ID,
            email=CONTRIBUTOR_EMAIL,
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    # Override the exact dependency closures used by each endpoint
    app.dependency_overrides[_start_scan_user_dep] = mock_contributor
    app.dependency_overrides[_poll_scan_user_dep] = mock_contributor
    app.dependency_overrides[_estimate_user_dep] = mock_contributor
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_start_scan_rejects_unknown_model(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    resp = client_contributor.post(
        f"/api/matters/{MATTER_ID}/vision-scan",
        data={"evidence_file_ids": FILE_ID, "model_slug": "made/up"},
    )
    assert resp.status_code == 400


def test_start_scan_records_last_used(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: db_session)
    with patch("cvp.services.vision.openrouter.call_vision", return_value="[]"):
        resp = client_contributor.post(
            f"/api/matters/{MATTER_ID}/vision-scan",
            data={"evidence_file_ids": FILE_ID, "model_slug": "anthropic/claude-opus-4"},
        )
    assert resp.status_code == 200
    db_session.expire_all()
    u = db_session.query(User).filter_by(id=CONTRIBUTOR_ID).one()
    assert u.last_vision_model_slug == "anthropic/claude-opus-4"


def test_cost_estimate_endpoint(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("cvp.services.vision.SessionLocal", lambda: db_session)
    resp = client_contributor.get(
        f"/api/matters/{MATTER_ID}/vision-scan-estimate"
        "?count=4&model_slug=anthropic/claude-opus-4"
    )
    assert resp.status_code == 200
    assert "$" in resp.text
    assert "0.12" in resp.text  # 4 * 3 cents = 12 cents = $0.12
