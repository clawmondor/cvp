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


import cvp.routers.admin.vision_models as vm_router  # noqa: E402


@pytest.fixture(autouse=True)
def reset_catalog_cache():
    """Reset the module-level catalog cache before each test to prevent stale data."""
    vm_router._catalog_cache = None
    yield
    vm_router._catalog_cache = None


def test_admin_vision_models_add_modal_shows_catalog(client_admin, monkeypatch):
    fake_catalog = [
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "architecture": {"input_modalities": ["text", "image"]},
            "pricing": {"image": "0.005"},
            "context_length": 128000,
            "description": "OpenAI multimodal",
        }
    ]
    monkeypatch.setattr(
        "cvp.routers.admin.vision_models.openrouter.fetch_models",
        lambda: fake_catalog,
    )
    resp = client_admin.get("/admin/vision-models/add")
    assert resp.status_code == 200
    assert "openai/gpt-4o" in resp.text
    assert "GPT-4o" in resp.text


def test_admin_vision_models_add_inserts_row(client_admin, db_session, monkeypatch):
    fake_catalog = [
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "architecture": {"input_modalities": ["text", "image"]},
            "pricing": {"image": "0.005"},
            "context_length": 128000,
            "description": "OpenAI multimodal",
        }
    ]
    monkeypatch.setattr(
        "cvp.routers.admin.vision_models.openrouter.fetch_models",
        lambda: fake_catalog,
    )
    resp = client_admin.post(
        "/admin/vision-models",
        data={"slug": "openai/gpt-4o", "adapter": "none"},
    )
    assert resp.status_code in (200, 303)
    row = db_session.query(VisionModel).filter_by(slug="openai/gpt-4o").one()
    assert row.adapter == "none"
    assert row.supports_bbox is False
    assert row.display_name == "GPT-4o"


def test_admin_vision_models_add_rejects_duplicate(client_admin, monkeypatch):
    monkeypatch.setattr(
        "cvp.routers.admin.vision_models.openrouter.fetch_models",
        lambda: [],
    )
    resp = client_admin.post(
        "/admin/vision-models",
        data={"slug": "anthropic/claude-opus-4", "adapter": "pixel_passthrough"},
    )
    assert resp.status_code in (400, 409)


def test_set_default_flips_previous(client_admin, db_session):
    # Add a second model
    second = VisionModel(
        slug="x/second", display_name="Second", adapter="none",
        supports_bbox=False, is_default=False, is_enabled=True,
    )
    db_session.add(second)
    db_session.commit()
    second_id = second.id

    resp = client_admin.post(f"/admin/vision-models/{second_id}/set-default")
    assert resp.status_code in (200, 303)

    db_session.expire_all()
    defaults = db_session.query(VisionModel).filter_by(is_default=True).all()
    assert len(defaults) == 1
    assert defaults[0].id == second_id


def test_disable_default_is_rejected(client_admin, db_session):
    default = db_session.query(VisionModel).filter_by(is_default=True).one()
    resp = client_admin.post(f"/admin/vision-models/{default.id}/disable")
    assert resp.status_code == 400


def test_disable_non_default_works(client_admin, db_session):
    non_default = VisionModel(
        slug="x/ndisable", display_name="ND", adapter="none",
        supports_bbox=False, is_default=False, is_enabled=True,
    )
    db_session.add(non_default)
    db_session.commit()
    nd_id = non_default.id

    resp = client_admin.post(f"/admin/vision-models/{nd_id}/disable")
    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.query(VisionModel).filter_by(id=nd_id).one().is_enabled is False
