"""Tests for POST /api/matters/{matter_id}/evidence (single-file endpoint)."""

import io

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
from cvp.services import runtime_config

CONTRIB_ID = "contrib-1"
MATTER_ID = "matter-up"


@pytest.fixture(autouse=True)
def clear_cache():
    runtime_config._cache.clear()
    yield
    runtime_config._cache.clear()


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    from cvp.models_auth import User

    s.add(User(id=CONTRIB_ID, email="c@test.com", display_name="C", system_role="internal_user"))
    s.add(Matter(id=MATTER_ID, policyholder_name="Owner", loss_type="total_loss"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client_contrib(db_session, monkeypatch, tmp_path):
    import inspect

    import cvp.routers.evidence as ev_router

    async def mock_contrib():
        return CurrentUser(
            id=CONTRIB_ID,
            email="c@test.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(ev_router.upload_evidence).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_contrib
    app.dependency_overrides[get_db] = override_get_db

    monkeypatch.setattr(
        "cvp.routers.evidence.settings",
        type("S", (), {"upload_dir": str(tmp_path), "crop_dir": str(tmp_path)})(),
    )
    monkeypatch.setattr("cvp.routers.evidence.SessionLocal", lambda: db_session)

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _jpeg_bytes(side: int = 10) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (side, side), "white").save(buf, "JPEG")
    return buf.getvalue()


def test_upload_single_image_succeeds_and_returns_tile_fragment(client_contrib, db_session):
    payload = _jpeg_bytes()
    resp = client_contrib.post(
        f"/api/matters/{MATTER_ID}/evidence",
        files={"file": ("a.jpg", payload, "image/jpeg")},
    )
    assert resp.status_code == 200
    # Response is a single-tile HTML fragment, not the whole grid
    assert "data-file-card" in resp.text
    assert 'id="evidence-grid"' not in resp.text

    rows = db_session.query(EvidenceFile).filter_by(matter_id=MATTER_ID).all()
    assert len(rows) == 1
    assert rows[0].filename == "a.jpg"
    assert rows[0].kind == "image"
    assert rows[0].size_bytes == len(payload)


def test_upload_rejects_file_exceeding_runtime_cap(client_contrib, db_session):
    # Set cap to 1 MB via DB override
    runtime_config.set_value(db_session, "evidence_upload_max_file_mb", 1, updated_by_user_id=None)
    big = b"\x00" * (2 * 1024 * 1024)  # 2 MB
    resp = client_contrib.post(
        f"/api/matters/{MATTER_ID}/evidence",
        files={"file": ("big.bin", big, "application/octet-stream")},
    )
    assert resp.status_code == 413
    assert db_session.query(EvidenceFile).filter_by(matter_id=MATTER_ID).count() == 0


def test_upload_requires_exactly_one_file_field(client_contrib):
    resp = client_contrib.post(f"/api/matters/{MATTER_ID}/evidence", data={})
    assert resp.status_code == 422  # FastAPI validation error
