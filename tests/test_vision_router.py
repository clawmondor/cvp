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

import claimos.models_vision  # noqa: F401
import claimos.routers.vision as vision_router
from claimos.db import get_db
from claimos.dependencies import CurrentUser
from claimos.main import app
from claimos.models import Base, EvidenceFile, Matter, VisionJob, VisionJobImage
from claimos.models_auth import User
from claimos.models_vision import VisionModel

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
_region_scan_dep = _dep(vision_router.region_scan)
_poll_status_dep = _dep(vision_router.poll_scan_status)


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
            prompt_image_cost_cents=3,
        )
    )
    db.add(
        User(
            id=CONTRIBUTOR_ID,
            email=CONTRIBUTOR_EMAIL,
            display_name="C",
            system_role="internal_user",
        )
    )
    db.add(Matter(id=MATTER_ID, policyholder_name="Owner", loss_type="total_loss"))
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

    app.dependency_overrides[_start_scan_dep] = mock_contributor
    app.dependency_overrides[_start_scan_all_dep] = mock_contributor
    app.dependency_overrides[_poll_scan_dep] = mock_contributor
    app.dependency_overrides[_estimate_dep] = mock_contributor
    app.dependency_overrides[_region_scan_dep] = mock_contributor
    app.dependency_overrides[_poll_status_dep] = mock_contributor
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_start_scan_rejects_unknown_model(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("claimos.services.vision_worker.wake", lambda: None)
    resp = client_contributor.post(
        f"/api/matters/{MATTER_ID}/vision-scan",
        data={"evidence_file_ids": FILE_ID, "model_slug": "made/up"},
    )
    assert resp.status_code == 400


def test_start_scan_records_last_used_and_creates_job(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("claimos.services.vision_worker.wake", lambda: None)
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
    monkeypatch.setattr("claimos.services.vision.SessionLocal", lambda: db_session)
    resp = client_contributor.get(
        f"/api/matters/{MATTER_ID}/vision-scan-estimate?count=4&model_slug=anthropic/claude-opus-4"
    )
    assert resp.status_code == 200
    assert "0.12" in resp.text


def test_region_scan_creates_job_with_region(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("claimos.services.vision_worker.wake", lambda: None)

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
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
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
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    # User has no last_vision_model_slug set.
    resp = client_contributor.post(
        f"/api/evidence/{FILE_ID}/region-scan",
        json={"left": 10, "upper": 10, "right": 110, "lower": 110},
    )
    assert resp.status_code == 400


def test_poll_scan_status_returns_json(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    monkeypatch.setattr("claimos.services.vision.SessionLocal", lambda: db_session)
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


def test_poll_scan_status_rejects_foreign_matter(client_contributor, db_session, monkeypatch):
    monkeypatch.setattr("claimos.routers.vision.SessionLocal", lambda: db_session)
    # Job belongs to a different matter than the one in the request path.
    other = Matter(id="matter-other", policyholder_name="Other", loss_type="total_loss")
    db_session.add(other)
    db_session.flush()
    job = VisionJob(
        matter_id="matter-other", model_slug="anthropic/claude-opus-4", status="running"
    )
    db_session.add(job)
    db_session.commit()

    resp = client_contributor.get(f"/api/matters/{MATTER_ID}/vision-scan/{job.id}/status")
    assert resp.status_code == 404
