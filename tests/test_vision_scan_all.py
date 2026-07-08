"""Tests for POST /api/claims/{claim_id}/vision-scan-all."""

import inspect
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_vision  # noqa: F401
import claimos.routers.vision as vision_router
from claimos.db import get_db
from claimos.dependencies import CurrentUser
from claimos.main import app
from claimos.models import Base, Claim, EvidenceFile, VisionJob, VisionJobImage
from claimos.models_auth import User
from claimos.models_vision import VisionModel

CONTRIBUTOR_ID = "contrib-sa"
CLAIM_ID = "claim-sa"
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
    db.add(User(id=CONTRIBUTOR_ID, email="c@t.com", display_name="C", system_role="internal_user"))
    db.add(Claim(id=CLAIM_ID, policyholder_name="Owner", loss_type="total_loss"))
    tmp = tempfile.mktemp(suffix=".jpg")
    PILImage.new("RGB", (10, 10), "white").save(tmp)
    db.add(
        EvidenceFile(
            id=FILE_ID,
            claim_id=CLAIM_ID,
            filename="test.jpg",
            stored_path=tmp,
            mime_type="image/jpeg",
            kind="image",
            size_bytes=os.path.getsize(tmp),
            scanned=False,
        )
    )
    db.commit()
    yield db
    db.close()


@pytest.fixture
def client_contributor(db_session):
    async def mock_contrib():
        return CurrentUser(
            id=CONTRIBUTOR_ID,
            email="c@t.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
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
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("claimos.services.vision_worker.wake", lambda: None)

    resp = client_contributor.post(
        f"/api/claims/{CLAIM_ID}/vision-scan-all",
        data={"model_slug": "anthropic/claude-opus-4"},
    )
    assert resp.status_code == 200

    jobs = db_session.query(VisionJob).filter_by(claim_id=CLAIM_ID).all()
    assert len(jobs) == 1
    images = db_session.query(VisionJobImage).filter_by(job_id=jobs[0].id).all()
    assert len(images) == 1
    assert images[0].evidence_file_id == FILE_ID


def test_scan_all_returns_empty_message_when_nothing_to_scan(
    client_contributor, db_session, monkeypatch
):
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("claimos.services.vision_worker.wake", lambda: None)

    ef = db_session.get(EvidenceFile, FILE_ID)
    ef.scanned = True
    db_session.commit()

    resp = client_contributor.post(
        f"/api/claims/{CLAIM_ID}/vision-scan-all",
        data={"model_slug": "anthropic/claude-opus-4"},
    )
    assert resp.status_code == 200
    assert "No unscanned" in resp.text


def test_scan_all_rejects_over_cap(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("claimos.services.vision_worker.wake", lambda: None)
    monkeypatch.setattr("claimos.routers.vision._SCAN_ALL_CAP", 2)

    for i in range(3):
        db_session.add(
            EvidenceFile(
                claim_id=CLAIM_ID,
                filename=f"extra_{i}.jpg",
                stored_path=f"/tmp/fake_{i}.jpg",
                mime_type="image/jpeg",
                kind="image",
                size_bytes=100,
                scanned=False,
            )
        )
    db_session.commit()

    resp = client_contributor.post(
        f"/api/claims/{CLAIM_ID}/vision-scan-all",
        data={"model_slug": "anthropic/claude-opus-4"},
    )
    assert resp.status_code == 200
    assert "Too many" in resp.text
