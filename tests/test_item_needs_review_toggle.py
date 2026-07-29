"""POST /api/items/{id}/toggle-needs-review flips the flag and re-renders the row."""

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

MATTER_ID = "m-nrt"
USER_ID = "u-nrt"


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

    dep = inspect.signature(items_router.toggle_needs_review).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_manager
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_item(db, needs_review=False):
    it = Item(
        matter_id=MATTER_ID,
        category_id=1,
        description="thing",
        confirmed=True,
        needs_review=needs_review,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def test_toggle_needs_review_on(client, db_session):
    it = _make_item(db_session, needs_review=False)
    resp = client.post(f"/api/items/{it.id}/toggle-needs-review")
    assert resp.status_code == 200
    assert f'id="item-row-{it.id}"' in resp.text
    # The endpoint's `finally: db.close()` expunges `it` from the shared
    # db_session (SessionLocal is monkeypatched to return this exact object),
    # so `db_session.refresh(it)` would raise InvalidRequestError here.
    # Re-query instead to observe the persisted state.
    refreshed = db_session.query(Item).filter(Item.id == it.id).first()
    assert refreshed.needs_review is True
    assert refreshed.confirmed is True  # unchanged


def test_toggle_needs_review_off(client, db_session):
    it = _make_item(db_session, needs_review=True)
    resp = client.post(f"/api/items/{it.id}/toggle-needs-review")
    assert resp.status_code == 200
    refreshed = db_session.query(Item).filter(Item.id == it.id).first()
    assert refreshed.needs_review is False


def test_row_shows_amber_review_pill_when_flagged(client, db_session):
    it = _make_item(db_session, needs_review=True)
    resp = client.post(f"/api/items/{it.id}/toggle-needs-review")
    # After toggling a flagged item it becomes unflagged -> no amber pill/label.
    # (A bare "flag" in resp.text substring check is trivially true even when
    # flagged, since the unflagged button's title is "Click to flag for
    # review" — assert the flagged markers are absent instead.)
    assert "⚑ review" not in resp.text
    assert "bg-amber-100" not in resp.text
    # Flip back on and confirm the amber label renders
    resp2 = client.post(f"/api/items/{it.id}/toggle-needs-review")
    assert "⚑ review" in resp2.text
    assert "bg-amber-100" in resp2.text
