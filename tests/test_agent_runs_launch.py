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
from cvp.routers import agent_runs as agent_runs_router
from cvp.services.agent_keys import generate_key


@pytest.fixture
def ctx(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    m = Matter(firm_name="F")
    db.add(m)
    cat = Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2)
    db.add(cat)
    db.flush()
    item = Item(matter_id=m.id, category_id=cat.id, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.commit()

    launched: list[str] = []
    monkeypatch.setattr(
        agent_runs_router.agent_launch, "launch_run", lambda rid: launched.append(rid)
    )
    monkeypatch.setattr(
        agent_runs_router.settings, "cloudflare_agent_key_id", key.id, raising=False
    )

    class _User:
        id = "u1"

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[agent_runs_router.EDITOR] = lambda: _User()
    yield TestClient(app), db, item.id, key.id, launched
    app.dependency_overrides.clear()
    db.close()


def test_launch_creates_queued_run(ctx):
    client, db, item_id, key_id, launched = ctx
    r = client.post(f"/api/items/{item_id}/agent-runs")
    assert r.status_code == 200

    run = db.query(AgentRun).one()
    assert run.status == "queued"
    assert run.item_id == item_id
    assert run.agent_key_id == key_id
    assert run.agent_impl == "custom-python"
    assert run.model_slug == "anthropic/claude-haiku-4.5"
    assert launched == [run.id]


def test_launch_rejects_disallowed_model(ctx):
    client, db, item_id, _key_id, launched = ctx
    r = client.post(f"/api/items/{item_id}/agent-runs", params={"model_slug": "evil/expensive"})
    assert r.status_code == 400
    assert db.query(AgentRun).count() == 0
    assert launched == []


def test_launch_rejects_when_run_already_in_flight(ctx):
    client, db, item_id, key_id, launched = ctx
    db.add(
        AgentRun(
            item_id=item_id,
            matter_id=db.query(Item).first().matter_id,
            agent_impl="custom-python",
            model_slug="anthropic/claude-haiku-4.5",
            agent_key_id=key_id,
            status="running",
        )
    )
    db.commit()

    r = client.post(f"/api/items/{item_id}/agent-runs")
    assert r.status_code == 409
    assert launched == []


def test_launch_rejects_at_pending_cap(ctx):
    client, db, item_id, key_id, launched = ctx
    for _ in range(5):
        db.add(
            AiRecommendation(
                item_id=item_id,
                agent_key_id=key_id,
                proposed_retail_unit_cents=100,
                source_url="https://x.example/a",
                source_retailer="X",
                status="pending",
            )
        )
    db.commit()

    r = client.post(f"/api/items/{item_id}/agent-runs")
    assert r.status_code == 409
    assert db.query(AgentRun).count() == 0
    assert launched == []


def test_launch_404s_for_unknown_item(ctx):
    client, _db, _item_id, _key_id, _launched = ctx
    r = client.post("/api/items/does-not-exist/agent-runs")
    assert r.status_code == 404
