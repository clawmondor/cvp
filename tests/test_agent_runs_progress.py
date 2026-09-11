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

    mine_full, mine_prefix, mine_hash = generate_key()
    mine = AgentKey(name="cf", key_prefix=mine_prefix, key_hash=mine_hash)
    other_full, other_prefix, other_hash = generate_key()
    other = AgentKey(name="other", key_prefix=other_prefix, key_hash=other_hash)
    db.add_all([mine, other])
    db.flush()

    run = AgentRun(
        item_id=item.id,
        matter_id=m.id,
        agent_impl="custom-python",
        model_slug="anthropic/claude-haiku-4.5",
        agent_key_id=mine.id,
        status="running",
    )
    db.add(run)
    db.commit()

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app), db, run.id, mine_full, other_full
    app.dependency_overrides.clear()
    db.close()


def test_progress_updates_status_and_message(ctx):
    client, db, run_id, key, _other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "searching", "message": "Looking for retail matches…"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    db.expire_all()
    run = db.get(AgentRun, run_id)
    assert run.status == "searching"
    assert run.status_message == "Looking for retail matches…"
    assert run.finished_at is None


def test_terminal_success_records_telemetry(ctx):
    client, db, run_id, key, _other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={
            "status": "succeeded",
            "agent_impl": "custom-python",
            "image_tag": "a1b2c3d",
            "model_slug": "anthropic/claude-haiku-4.5",
            "cost_micro_usd": 9835,
            "latency_ms": 3521,
            "browser_run_used": False,
        },
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    db.expire_all()
    run = db.get(AgentRun, run_id)
    assert run.status == "succeeded"
    assert run.cost_micro_usd == 9835
    assert run.latency_ms == 3521
    assert run.image_tag == "a1b2c3d"
    assert run.finished_at is not None


def test_progress_rejects_missing_key(ctx):
    client, _db, run_id, _key, _other = ctx
    r = client.post(f"/api/agent/runs/{run_id}/progress", json={"status": "running"})
    assert r.status_code == 401


def test_progress_rejects_another_principals_run(ctx):
    client, _db, run_id, _key, other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "running"},
        headers={"X-API-Key": other},
    )
    assert r.status_code == 403


def test_progress_rejected_after_terminal(ctx):
    client, db, run_id, key, _other = ctx
    run = db.get(AgentRun, run_id)
    run.status = "succeeded"
    db.commit()

    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "running"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 409


def test_progress_rejects_unknown_status(ctx):
    client, _db, run_id, key, _other = ctx
    r = client.post(
        f"/api/agent/runs/{run_id}/progress",
        json={"status": "bogus"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 422
