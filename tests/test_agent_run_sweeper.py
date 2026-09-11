from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AgentRun
from cvp.services.agent_keys import generate_key
from cvp.services.agent_run_sweeper import sweep_stale_runs


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _make_run(db, *, status: str, age_minutes: int) -> AgentRun:
    m = Matter(firm_name="F")
    db.add(m)
    cat = Category(name="Furniture", useful_life_years=10, acv_floor_pct=0.2)
    db.add(cat)
    db.flush()
    item = Item(matter_id=m.id, category_id=cat.id, description="chair", quantity=1)
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
        status=status,
        created_at=datetime.now(tz=timezone.utc) - timedelta(minutes=age_minutes),
    )
    db.add(run)
    db.commit()
    return run


def test_old_running_run_is_failed(db):
    run = _make_run(db, status="running", age_minutes=60)
    assert sweep_stale_runs(db, older_than_minutes=15) == 1
    db.refresh(run)
    assert run.status == "failed"
    assert "timed out" in run.error
    assert run.finished_at is not None


def test_recent_run_is_left_alone(db):
    run = _make_run(db, status="running", age_minutes=2)
    assert sweep_stale_runs(db, older_than_minutes=15) == 0
    db.refresh(run)
    assert run.status == "running"


def test_terminal_run_is_left_alone(db):
    run = _make_run(db, status="succeeded", age_minutes=60)
    assert sweep_stale_runs(db, older_than_minutes=15) == 0
    db.refresh(run)
    assert run.status == "succeeded"
