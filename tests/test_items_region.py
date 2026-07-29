"""Tests for GET /api/matters/{matter_id}/items-region (filter bar + region)."""

import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
import cvp.routers.items as items_router
from cvp.db import get_db
from cvp.dependencies import CurrentUser
from cvp.main import app
from cvp.models import Base, Category, Item, Matter, Room
from cvp.services import access_cache

VIEWER_ID = "v1"
MATTER_ID = "m-region"


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
    s = sessionmaker(bind=engine)()
    from cvp.models_auth import User

    s.add(User(id=VIEWER_ID, email="v@test.com", display_name="V", system_role="internal_user"))
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="Appliances", useful_life_years=10, acv_floor_pct=0.2))
    s.add(Room(id="r-kit", matter_id=MATTER_ID, name="Kitchen", sort_order=0))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
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

    dep = inspect.signature(items_router.get_items_region).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed(db, n):
    for i in range(n):
        db.add(
            Item(
                matter_id=MATTER_ID,
                category_id=1,
                room_id="r-kit" if i % 2 == 0 else None,
                line_number=i + 1,
                description=f"item {i + 1}",
                quantity=1,
                condition="average",
                retail_unit_cents=100,
                rcv_total_cents=100,
                acv_total_cents=80,
                confirmed=True,
            )
        )
    db.commit()


def test_region_renders_controls_and_region_id(client, db_session):
    _seed(db_session, 3)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="items-region"' in body
    assert 'id="items-controls"' in body
    assert 'id="items-tbody"' in body
    assert 'data-sort="line"' in body


def test_region_shows_filtered_count(client, db_session):
    _seed(db_session, 4)  # 2 in Kitchen, 2 unassigned
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region?room_id=r-kit")
    body = resp.text
    assert body.count('<tr id="item-row-') == 2
    assert "Showing 2 of 4" in body
    # The room select preselects the active room.
    assert 'value="r-kit" selected' in body


def test_region_first_page_capped_and_sentinel_present(client, db_session):
    _seed(db_session, 60)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region")
    body = resp.text
    assert body.count('<tr id="item-row-') == 50
    assert "offset=50" in body


def test_region_empty_filter_message(client, db_session):
    _seed(db_session, 2)
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region?q=nomatch")
    body = resp.text
    assert "No items match the current filters." in body


def test_region_empty_sort_only_shows_add_message(client, db_session):
    resp = client.get(f"/api/matters/{MATTER_ID}/items-region?sort=rcv_total&dir=desc")
    body = resp.text
    assert "No items yet" in body
    assert "No items match the current filters." not in body
