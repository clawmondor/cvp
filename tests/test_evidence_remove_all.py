"""Tests for POST /api/matters/{matter_id}/evidence/remove-all-images."""

import os

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

    db.add(
        User(id=MANAGER_ID, email="mgr@test.com", display_name="Mgr", system_role="internal_user")
    )
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
            id=MANAGER_ID,
            email="mgr@test.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
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
    filename = os.path.basename(path)
    ef = EvidenceFile(
        matter_id=matter_id,
        filename=filename,
        stored_path=filename,  # relative path — matches production convention
        mime_type="image/jpeg",
        kind="image",
        size_bytes=os.path.getsize(path),
    )
    db.add(ef)
    db.commit()
    return ef


def test_remove_all_images_deletes_images_leaves_pdfs(
    client_manager, db_session, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "cvp.routers.evidence.settings",
        type("S", (), {"upload_dir": str(tmp_path), "crop_dir": str(tmp_path)})(),
    )
    monkeypatch.setattr("cvp.routers.evidence.SessionLocal", lambda: db_session)

    img1 = str(tmp_path / "a.jpg")
    img2 = str(tmp_path / "b.jpg")
    _add_image(db_session, MATTER_ID, img1)
    _add_image(db_session, MATTER_ID, img2)

    # Add a PDF (should survive)
    pdf = EvidenceFile(
        matter_id=MATTER_ID,
        filename="doc.pdf",
        stored_path="doc.pdf",
        mime_type="application/pdf",
        kind="pdf",
        size_bytes=100,
    )
    db_session.add(pdf)
    db_session.commit()

    resp = client_manager.post(
        f"/api/matters/{MATTER_ID}/evidence/remove-all-images",
        data={"confirm_count": "2"},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    remaining = db_session.query(EvidenceFile).filter_by(matter_id=MATTER_ID).all()
    assert len(remaining) == 1
    assert remaining[0].kind == "pdf"


def test_remove_all_images_rejects_mismatched_count(
    client_manager, db_session, monkeypatch, tmp_path
):
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
