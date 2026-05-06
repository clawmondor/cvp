# tests/test_admin_vision_models.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401 — register table
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.main import app
from cvp.models import Base
from cvp.models_vision import VisionModel


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Seed the default model
    session.add(
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
    session.commit()
    yield session
    session.close()


@pytest.fixture
def client_admin(db_session):
    async def mock_admin():
        return CurrentUser(
            id="sa",
            email="sa@test.com",
            system_role="system_admin",
            group_id="ig",
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[require_system_admin] = mock_admin
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_admin_vision_models_index_lists_seeded_default(client_admin):
    resp = client_admin.get("/admin/vision-models")
    assert resp.status_code == 200
    body = resp.text
    assert "anthropic/claude-opus-4" in body
    assert "Claude Opus 4" in body
    assert "checked" in body  # default radio is checked


def test_admin_vision_models_index_requires_admin(monkeypatch):
    # Disable dev auto-login so the auth guard is actually tested.
    from cvp import config

    monkeypatch.setattr(config.settings, "auto_login_user_id", "")
    with TestClient(app) as c:
        resp = c.get("/admin/vision-models", follow_redirects=False)
    assert resp.status_code in (302, 303, 401, 403)
