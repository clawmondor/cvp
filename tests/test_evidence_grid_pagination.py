"""Tests for the paginated GET /api/claims/{claim_id}/evidence-grid endpoint."""

import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_vision  # noqa: F401
from claimos.db import get_db
from claimos.dependencies import CurrentUser
from claimos.main import app
from claimos.models import Base, Claim, EvidenceFile
from claimos.services import access_cache

VIEWER_ID = "v1"
CLAIM_ID = "m-grid"


@pytest.fixture(autouse=True)
def clear_caches():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


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
    from claimos.models_auth import User

    s.add(User(id=VIEWER_ID, email="v@test.com", display_name="V", system_role="internal_user"))
    s.add(Claim(id=CLAIM_ID, policyholder_name="P", loss_type="total_loss"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    import inspect

    import claimos.routers.evidence as ev_router

    async def mock_viewer():
        return CurrentUser(
            id=VIEWER_ID,
            email="v@test.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(ev_router.get_evidence_grid).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("claimos.routers.evidence.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_images(db, count: int, tmp_path) -> list[EvidenceFile]:
    # Give each row a unique sub-second `created_at`. SQLite stores
    # `func.now()` at second precision, which under heavy seeding produces
    # ties that defeat cursor pagination. Setting timestamps explicitly here
    # avoids that test-only artifact; production Postgres has microsecond
    # precision and doesn't need the hint.
    rows = []
    base = datetime(2026, 1, 1, 12, 0, 0)
    for i in range(count):
        path = tmp_path / f"img_{i:03d}.jpg"
        PILImage.new("RGB", (10, 10), "white").save(path, "JPEG")
        ef = EvidenceFile(
            claim_id=CLAIM_ID,
            filename=path.name,
            stored_path=f"{CLAIM_ID}/{path.name}",
            mime_type="image/jpeg",
            size_bytes=os.path.getsize(path),
            kind="image",
            created_at=base + timedelta(seconds=i),
        )
        db.add(ef)
        db.commit()
        db.refresh(ef)
        rows.append(ef)
    return rows


def test_first_page_returns_24_tiles_and_sentinel(client, db_session, tmp_path):
    _seed_images(db_session, 30, tmp_path)
    resp = client.get(f"/api/claims/{CLAIM_ID}/evidence-grid")
    assert resp.status_code == 200
    body = resp.text
    assert body.count("data-file-card") == 24
    assert 'hx-trigger="revealed"' in body
    assert "cursor=" in body


def test_second_page_returns_remainder_and_no_sentinel(client, db_session, tmp_path):
    rows = _seed_images(db_session, 30, tmp_path)
    # Newest-first ordering by created_at desc; oldest of the first page is rows[6]
    # (rows[29], rows[28], ..., rows[6] = 24 newest). Cursor = rows[6].created_at.
    cursor = rows[6].created_at.isoformat()
    resp = client.get(f"/api/claims/{CLAIM_ID}/evidence-grid?cursor={cursor}")
    assert resp.status_code == 200
    body = resp.text
    assert body.count("data-file-card") == 6
    assert 'hx-trigger="revealed"' not in body


def test_empty_claim_returns_no_tiles_no_sentinel(client):
    resp = client.get(f"/api/claims/{CLAIM_ID}/evidence-grid")
    assert resp.status_code == 200
    assert "data-file-card" not in resp.text
    assert 'hx-trigger="revealed"' not in resp.text
