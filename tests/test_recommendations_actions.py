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
from cvp.routers.recommendations import EDITOR
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
def ctx(db_session):
    db_session.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2))
    m = Matter(firm_name="F")
    db_session.add(m)
    db_session.flush()
    it = Item(matter_id=m.id, category_id=1, description="chair", quantity=2, age_years=1.0)
    db_session.add(it)
    full, prefix, key_hash = generate_key()
    key = AgentKey(name="Bot", key_prefix=prefix, key_hash=key_hash)
    db_session.add(key)
    db_session.flush()
    rec = AiRecommendation(
        item_id=it.id,
        agent_key_id=key.id,
        proposed_retail_unit_cents=10000,
        proposed_shipping_cents=500,
        source_url="https://s/x",
        source_retailer="Store",
        match_type="exact",
        status="pending",
    )
    other = AiRecommendation(
        item_id=it.id,
        agent_key_id=key.id,
        status="pending",
        source_url="https://s/y",
        source_retailer="Other",
    )
    db_session.add_all([rec, other])
    db_session.commit()

    async def mock_role():
        return CurrentUser(
            id="u1", email="e", system_role="internal_admin", group_id=None, group_kind=None
        )

    def override_get_db():
        yield db_session

    app.dependency_overrides[EDITOR] = mock_role
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), it.id, rec.id, other.id, db_session
    app.dependency_overrides.clear()


def test_accept_writes_through_and_supersedes_others(ctx):
    client, item_id, rec_id, other_id, db = ctx
    resp = client.post(f"/api/items/{item_id}/recommendations/{rec_id}/accept")
    assert resp.status_code == 200
    db.expire_all()
    item = db.get(Item, item_id)
    assert item.retail_unit_cents == 10000
    assert item.shipping_cents == 500
    assert item.source_url == "https://s/x"
    assert item.source_retailer == "Store"
    assert item.source_captured_at is not None
    # rcv = 10000 * 2 + 500
    assert item.rcv_total_cents == 20500
    assert item.acv_total_cents > 0
    assert db.get(AiRecommendation, rec_id).status == "accepted"
    assert db.get(AiRecommendation, other_id).status == "superseded"


def test_dismiss_marks_rejected(ctx):
    client, item_id, rec_id, other_id, db = ctx
    resp = client.post(f"/api/items/{item_id}/recommendations/{other_id}/dismiss")
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(AiRecommendation, other_id).status == "rejected"
