import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.models import Base, Category, Item, Matter
from cvp.models_agent import AgentKey, AiRecommendation
from cvp.services.agent_keys import generate_key
from cvp.services.recommendation_feed import items_needing_recommendations


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _seed(db):
    db.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2))
    m = Matter(firm_name="F")
    db.add(m)
    db.flush()
    return m


def _item(db, matter, confidence, source_url=""):
    it = Item(
        matter_id=matter.id,
        category_id=1,
        description="chair",
        quantity=1,
        vision_confidence=confidence,
        source_url=source_url,
    )
    db.add(it)
    db.flush()
    return it


def test_feed_filters_by_confidence_source_and_cap(db_session):
    m = _seed(db_session)
    high = _item(db_session, m, "high")
    _item(db_session, m, "low")  # below threshold -> excluded
    _item(db_session, m, "high", source_url="http://x")  # already priced -> excluded
    db_session.commit()

    result = items_needing_recommendations(db_session, "high", limit=50, offset=0)
    assert [i.id for i in result] == [high.id]


def test_feed_excludes_items_at_five_pending(db_session):
    m = _seed(db_session)
    full = _item(db_session, m, "high")
    key = AgentKey(name="b", key_prefix=generate_key()[1], key_hash="h")
    db_session.add(key)
    db_session.flush()
    for _ in range(5):
        db_session.add(AiRecommendation(item_id=full.id, agent_key_id=key.id, status="pending"))
    db_session.commit()
    result = items_needing_recommendations(db_session, "high", limit=50, offset=0)
    assert full.id not in [i.id for i in result]


def test_medium_threshold_includes_medium_and_high(db_session):
    m = _seed(db_session)
    _item(db_session, m, "medium")
    _item(db_session, m, "high")
    db_session.commit()
    result = items_needing_recommendations(db_session, "medium", limit=50, offset=0)
    assert len(result) == 2


def _client(db_session):
    from fastapi.testclient import TestClient

    from cvp.db import get_db
    from cvp.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app


def _make_key_row(db):
    full, prefix, key_hash = generate_key()
    key = AgentKey(name="Bot", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    db.commit()
    return full


def test_feed_endpoint_requires_key_and_returns_items(db_session):
    m = _seed(db_session)
    _item(db_session, m, "high")
    db_session.commit()
    full = _make_key_row(db_session)
    client, app = _client(db_session)
    try:
        assert client.get("/api/agent/items").status_code == 401
        resp = client.get("/api/agent/items", headers={"X-API-Key": full})
        assert resp.status_code == 200
        payload = resp.json()
        assert len(payload["items"]) == 1
        assert payload["items"][0]["vision_confidence"] == "high"
    finally:
        app.dependency_overrides.clear()
