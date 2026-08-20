"""Tests for the external-agent reference client (skills/airecommendations).

The client's single I/O seam (`_send`) is wired to the FastAPI TestClient so
the real `/api/agent/*` endpoints are exercised — this catches drift between
the reference client and the actual API surface.
"""

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_agent  # noqa: F401
from cvp.config import settings
from cvp.db import get_db
from cvp.main import app
from cvp.models import Base, Category, Item, ItemCrop, Matter
from cvp.models_agent import AgentKey, AiRecommendation
from cvp.services.agent_keys import generate_key

# Load the reference client module by path (it lives under skills/, not the cvp package).
_CLIENT_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "airecommendations"
    / "scripts"
    / "agent_client.py"
)
_spec = importlib.util.spec_from_file_location("agent_client", _CLIENT_PATH)
agent_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_client)

AiRecommendationsClient = agent_client.AiRecommendationsClient
AgentApiError = agent_client.AgentApiError
dollars_to_cents = agent_client.dollars_to_cents


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
def api_key(db_session):
    full, prefix, key_hash = generate_key()
    db_session.add(AgentKey(name="Bot", key_prefix=prefix, key_hash=key_hash))
    db_session.commit()
    return full


@pytest.fixture
def seeded_item(db_session):
    db_session.add(Category(id=1, name="Furniture", useful_life_years=10, acv_floor_pct=0.2))
    m = Matter(firm_name="F")
    db_session.add(m)
    db_session.flush()
    it = Item(
        matter_id=m.id,
        category_id=1,
        description="oak chair",
        quantity=1,
        vision_confidence="high",
    )
    db_session.add(it)
    db_session.commit()
    return it


@pytest.fixture
def client(db_session, api_key):
    """A reference client whose _send seam is routed to the FastAPI TestClient."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)

    c = AiRecommendationsClient(base_url="", api_key=api_key)

    def fake_send(method, url, headers, data):
        resp = tc.request(method, url, headers=headers, content=data)
        return resp.status_code, resp.content

    c._send = fake_send
    yield c
    app.dependency_overrides.clear()


def test_dollars_to_cents():
    assert dollars_to_cents("12.34") == 1234
    assert dollars_to_cents(99) == 9900
    assert dollars_to_cents(0) == 0


def test_list_items_sends_key_and_returns_items(client, seeded_item):
    items = client.list_items()
    assert any(i["item_id"] == seeded_item.id for i in items)
    got = next(i for i in items if i["item_id"] == seeded_item.id)
    assert got["vision_confidence"] == "high"


def test_get_item_returns_detail(client, seeded_item):
    item = client.get_item(seeded_item.id)
    assert item["item_id"] == seeded_item.id
    assert item["description"] == "oak chair"


def test_get_item_unknown_raises_404(client):
    with pytest.raises(AgentApiError) as exc:
        client.get_item("does-not-exist")
    assert exc.value.status == 404


def test_submit_creates_pending_recommendation(client, seeded_item, db_session):
    result = client.submit_recommendation(
        seeded_item.id,
        retail_unit_cents=12300,
        shipping_cents=500,
        source_url="https://shop.example/oak-chair",
        source_retailer="Example",
        product_title="Oak Chair",
        rationale="matches the crop",
    )
    assert result["status"] == "pending"
    rec = db_session.query(AiRecommendation).one()
    assert rec.proposed_retail_unit_cents == 12300
    assert rec.proposed_shipping_cents == 500


def test_submit_missing_source_raises_422(client, seeded_item):
    with pytest.raises(AgentApiError) as exc:
        client.submit_recommendation(
            seeded_item.id,
            retail_unit_cents=12300,
            source_url="",
            source_retailer="Example",
        )
    assert exc.value.status == 422


def test_submit_over_cap_raises_409(client, seeded_item):
    for _ in range(5):
        client.submit_recommendation(
            seeded_item.id,
            retail_unit_cents=100,
            source_url="https://s/x",
            source_retailer="R",
        )
    with pytest.raises(AgentApiError) as exc:
        client.submit_recommendation(
            seeded_item.id,
            retail_unit_cents=100,
            source_url="https://s/x",
            source_retailer="R",
        )
    assert exc.value.status == 409


def test_fetch_crop_returns_bytes(client, seeded_item, db_session, tmp_path, monkeypatch):
    (tmp_path / "c.jpg").write_bytes(b"imgbytes")
    monkeypatch.setattr(settings, "crop_dir", str(tmp_path))
    crop = ItemCrop(item_id=seeded_item.id, evidence_file_id="ef1", crop_path="c.jpg")
    db_session.add(crop)
    db_session.commit()

    data = client.fetch_crop("/api/agent/crops/c.jpg")
    assert data == b"imgbytes"
