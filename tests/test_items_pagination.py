"""Tests for the paginated GET /api/matters/{matter_id}/items-rows endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, Item, Matter
from cvp.services import access_cache

VIEWER_ID = "v1"
MATTER_ID = "m-items"


@pytest.fixture(autouse=True)
def clear_caches():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    from cvp.models_auth import User

    s.add(User(id=VIEWER_ID, email="v@test.com", display_name="V", system_role="internal_user"))
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
    import inspect

    import cvp.routers.items as items_router

    async def mock_viewer():
        return CurrentUser(
            id=VIEWER_ID,
            email="v@test.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.get_items_rows).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_items(db, count: int) -> list[Item]:
    rows = []
    for i in range(count):
        it = Item(
            matter_id=MATTER_ID,
            category_id=1,
            line_number=i + 1,
            description=f"item {i + 1}",
            quantity=1,
            age_years=0.0,
            condition="average",
            rcv_unit_cents=100,
            rcv_total_cents=100,
            acv_total_cents=80,
            confirmed=True,
        )
        db.add(it)
        rows.append(it)
    db.commit()
    return rows


def test_first_page_returns_50_rows_and_sentinel(client, db_session):
    _seed_items(db_session, 60)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows")
    assert resp.status_code == 200
    body = resp.text
    assert body.count('<tr id="item-row-') == 50
    assert 'hx-trigger="revealed"' in body


def test_second_page_returns_remainder_and_no_sentinel(client, db_session):
    _seed_items(db_session, 60)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows?cursor=50")
    assert resp.status_code == 200
    body = resp.text
    assert body.count('<tr id="item-row-') == 10
    assert 'hx-trigger="revealed"' not in body


def test_empty_matter_returns_no_rows_no_sentinel(client):
    resp = client.get(f"/api/matters/{MATTER_ID}/items-rows")
    assert resp.status_code == 200
    assert '<tr id="item-row-' not in resp.text
    assert 'hx-trigger="revealed"' not in resp.text
