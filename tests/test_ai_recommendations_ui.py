"""Tests for the AI Recommendations item-edit UI partial."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AiRecommendation
from cvp.routers.items import EDITOR_DEP
from cvp.services.agent_keys import generate_key


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture
def client(db_session):
    db_session.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2))
    m = Matter(firm_name="F")
    db_session.add(m)
    db_session.flush()
    it = Item(matter_id=m.id, category_id=1, description="chair", quantity=1)
    db_session.add(it)
    db_session.commit()

    async def mock_role():
        return CurrentUser(
            id="u1", email="e", system_role="internal_admin", group_id=None, group_kind=None
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[EDITOR_DEP] = mock_role
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), it.id, db_session
    app.dependency_overrides.clear()


def test_empty_state_text(client):
    c, item_id, db = client
    resp = c.get(f"/api/items/{item_id}/ai-recommendations")
    assert resp.status_code == 200
    assert "No Existing Recommendations." in resp.text


def test_pending_recommendation_renders(client):
    c, item_id, db = client
    full, prefix, key_hash = generate_key()
    key = AgentKey(name="Bot", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()
    db.add(
        AiRecommendation(
            item_id=item_id,
            agent_key_id=key.id,
            proposed_retail_unit_cents=9900,
            source_url="https://s/x",
            source_retailer="Store",
            product_title="Oak chair",
            status="pending",
        )
    )
    db.commit()
    resp = c.get(f"/api/items/{item_id}/ai-recommendations")
    assert "Oak chair" in resp.text
    assert "Store" in resp.text
    assert "$99.00" in resp.text
