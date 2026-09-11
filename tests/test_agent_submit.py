import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.main import app
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AgentRun, AiRecommendation
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
    it = Item(matter_id=m.id, category_id=1, description="chair", quantity=1)
    db_session.add(it)
    full, prefix, key_hash = generate_key()
    db_session.add(AgentKey(name="Bot", key_prefix=prefix, key_hash=key_hash))
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), full, it.id, db_session
    app.dependency_overrides.clear()


def _body(**over):
    b = {
        "proposed_retail_unit_cents": 12300,
        "proposed_shipping_cents": 500,
        "source_url": "https://shop.example/x",
        "source_retailer": "Example",
        "match_type": "exact",
        "product_title": "Oak chair",
        "rationale": "matches crop",
    }
    b.update(over)
    return b


def test_submit_creates_pending_recommendation(ctx):
    client, key, item_id, db = ctx
    resp = client.post(
        f"/api/agent/items/{item_id}/recommendations",
        json=_body(),
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 201
    rec = db.query(AiRecommendation).one()
    assert rec.status == "pending"
    assert rec.proposed_retail_unit_cents == 12300
    assert rec.source_captured_at is not None


def test_submit_requires_source_fields(ctx):
    client, key, item_id, db = ctx
    resp = client.post(
        f"/api/agent/items/{item_id}/recommendations",
        json=_body(source_url=""),
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 422


def test_submit_rejects_negative_retail_cents(ctx):
    client, key, item_id, db = ctx
    resp = client.post(
        f"/api/agent/items/{item_id}/recommendations",
        json=_body(proposed_retail_unit_cents=-100),
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 422


def test_submit_rejects_sixth_pending_with_409(ctx):
    client, key, item_id, db = ctx
    for _ in range(5):
        assert (
            client.post(
                f"/api/agent/items/{item_id}/recommendations",
                json=_body(),
                headers={"X-API-Key": key},
            ).status_code
            == 201
        )
    resp = client.post(
        f"/api/agent/items/{item_id}/recommendations",
        json=_body(),
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 409


def test_submit_unknown_item_404(ctx):
    client, key, item_id, db = ctx
    resp = client.post(
        "/api/agent/items/does-not-exist/recommendations",
        json=_body(),
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 404


def _agent_run(db, item_id):
    """A run row to attribute a submission to (FK target for agent_run_id)."""
    item = db.get(Item, item_id)
    key = db.query(AgentKey).one()
    run = AgentRun(
        item_id=item_id,
        matter_id=item.matter_id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=key.id,
    )
    db.add(run)
    db.commit()
    return run.id


def test_submit_records_agent_run_id_when_supplied(ctx):
    """Without this the A/B join in the design spec (5.3) returns zero rows."""
    client, key, item_id, db = ctx
    run_id = _agent_run(db, item_id)

    resp = client.post(
        f"/api/agent/items/{item_id}/recommendations",
        json=_body(agent_run_id=run_id),
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 201
    rec = db.query(AiRecommendation).one()
    assert rec.agent_run_id == run_id


def test_submit_leaves_agent_run_id_none_for_external_agents(ctx):
    """The external-agent path has no run; it must stay untouched."""
    client, key, item_id, db = ctx
    resp = client.post(
        f"/api/agent/items/{item_id}/recommendations",
        json=_body(),
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 201
    assert db.query(AiRecommendation).one().agent_run_id is None
