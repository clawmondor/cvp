import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AgentRun, AiRecommendation
from cvp.services.agent_keys import generate_key


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_agent_run_defaults_to_queued(db):
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
        started_by_id=None,
    )
    db.add(run)
    db.commit()

    assert run.status == "queued"
    assert run.browser_run_used is False
    assert run.cost_micro_usd is None


def test_terminal_set_contents():
    assert AgentRun.TERMINAL == frozenset({"succeeded", "failed"})


def test_recommendation_agent_run_id_is_nullable(db):
    """External-agent submissions have no run; that path must keep working."""
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

    rec = AiRecommendation(
        item_id=item.id,
        agent_key_id=key.id,
        proposed_retail_unit_cents=1000,
        source_url="https://shop.example/x",
        source_retailer="Shop",
    )
    db.add(rec)
    db.commit()
    assert rec.agent_run_id is None
