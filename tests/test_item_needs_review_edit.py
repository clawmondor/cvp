"""Editing an item persists the needs_review checkbox."""

import inspect

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
from cvp.models_auth import User
from cvp.services import access_cache

MATTER_ID = "m-nre"
USER_ID = "u-nre"


@pytest.fixture(autouse=True)
def _clear_access_cache():
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
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.add(User(id=USER_ID, email="u@t.com", display_name="U", system_role="internal_user"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session, monkeypatch):
    import cvp.routers.items as items_router

    async def mock_manager():
        return CurrentUser(
            id=USER_ID,
            email="u@t.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.update_item).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_manager
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_item(db):
    it = Item(matter_id=MATTER_ID, category_id=1, description="thing", confirmed=True)
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _form(**overrides):
    data = {
        "description": "thing",
        "category_id": "1",
        "room_id": "",
        "quantity": "1",
        "age_years": "0",
        "condition": "average",
        "retail_unit_dollars": "0",
        "shipping_dollars": "0",
        "brand": "",
        "model_num": "",
        "notes": "",
        "source_retailer": "",
        "source_url": "",
        "match_type": "exact",
        "acv_override_dollars": "",
        "acv_override_reason": "",
        "confirmed": "true",
        "item_group_id": "",
        "new_item_group_name": "",
    }
    data.update(overrides)
    return data


def test_edit_sets_needs_review(client, db_session):
    it = _make_item(db_session)
    # update_item is a PATCH route (see routers/items.py); the brief's test used
    # client.post, which 405s against this route. Using client.patch to match
    # the actual route method and the existing pattern in
    # tests/test_items_group_assignment.py.
    resp = client.patch(f"/api/items/{it.id}", data=_form(needs_review="true"))
    assert resp.status_code == 200
    # db.close() in update_item runs on the same monkeypatched shared session,
    # which detaches `it` via expunge_all(); db_session.refresh(it) would raise
    # InvalidRequestError. Re-query instead to verify persisted DB state.
    updated = db_session.query(Item).filter(Item.id == it.id).first()
    assert updated.needs_review is True


def test_edit_clears_needs_review_when_unchecked(client, db_session):
    it = _make_item(db_session)
    it.needs_review = True
    db_session.commit()
    # An unchecked checkbox submits no field at all.
    resp = client.patch(f"/api/items/{it.id}", data=_form())
    assert resp.status_code == 200
    # See comment above: re-query rather than refresh(it) after the detaching
    # db.close() in update_item.
    updated = db_session.query(Item).filter(Item.id == it.id).first()
    assert updated.needs_review is False
