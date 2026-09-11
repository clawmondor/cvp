import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.db import get_db
from cvp.main import app
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.routers import agent_runs as agent_runs_router
from cvp.services.agent_keys import generate_key


@pytest.fixture
def ctx():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2))
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    item = Item(matter_id=m.id, category_id=1, description="chair", quantity=1)
    db.add(item)
    _, prefix, key_hash = generate_key()
    key = AgentKey(name="cf", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.flush()
    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=key.id,
        status="searching",
        status_message="Looking for retail matches…",
    )
    db.add(run)
    db.commit()

    class _User:
        id = "u1"

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[agent_runs_router.EDITOR] = lambda: _User()
    yield TestClient(app), db, item.id, run.id
    app.dependency_overrides.clear()
    db.close()


def test_running_state_polls(ctx):
    client, _db, item_id, run_id = ctx
    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert 'hx-trigger="every 2s"' in html
    assert f"/api/items/{item_id}/agent-runs/{run_id}" in html
    assert "Looking for retail matches" in html


def test_terminal_state_stops_polling(ctx):
    client, db, item_id, run_id = ctx
    run = db.get(AgentRun, run_id)
    run.status = "succeeded"
    db.commit()

    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert "hx-trigger" not in html


def test_success_swaps_recommendations_out_of_band(ctx):
    client, db, item_id, run_id = ctx
    run = db.get(AgentRun, run_id)
    run.status = "succeeded"
    db.commit()

    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert 'hx-swap-oob="true"' in html
    assert f'id="ai-recs-{item_id}"' in html


def test_failed_state_shows_error(ctx):
    client, db, item_id, run_id = ctx
    run = db.get(AgentRun, run_id)
    run.status = "failed"
    run.error = "Worker returned 500"
    db.commit()

    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    assert "Worker returned 500" in html
    assert "hx-trigger" not in html


def test_no_inline_event_handlers(ctx):
    """CSP script-src has no unsafe-inline; inline handlers are hard-blocked."""
    client, _db, item_id, run_id = ctx
    html = client.get(f"/api/items/{item_id}/agent-runs/{run_id}").text
    for handler in ("onclick=", "onchange=", "onsubmit=", "onload="):
        assert handler not in html
