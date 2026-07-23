"""Tests for the item edit form's Group field (existing + create-new)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.dependencies as deps
import cvp.models_access  # noqa: F401
import cvp.models_auth  # noqa: F401
from cvp.auth import hash_password
from cvp.models import Base, Category, Item, ItemGroup, Matter
from cvp.models_auth import Group, User


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded_db(db_session):
    db_session.add(Group(id="ig", name="Internal", kind="internal"))
    db_session.add(
        User(
            id="ia",
            email="ia@test.com",
            display_name="Admin",
            password_hash=hash_password("x"),
            system_role="internal_admin",
            group_id="ig",
        )
    )
    db_session.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
    db_session.add(Matter(id="m1", owner_group_id="ig", created_by_id="ia"))
    db_session.commit()
    return db_session


@pytest.fixture
def make_client(seeded_db, monkeypatch):
    from cvp.db import get_db
    from cvp.dependencies import CurrentUser, require_active_user
    from cvp.main import app

    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass

    async def mock_user():
        return CurrentUser(
            id="ia",
            email="ia@test.com",
            system_role="internal_admin",
            group_id="ig",
            group_kind="internal",
        )

    levels = {"viewer": 0, "contributor": 1, "editor": 2, "manager": 3}

    def _make(role: str = "editor"):
        def fake_check(db, user, matter_id, required):
            return levels[role] >= levels[required]

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[require_active_user] = mock_user
        monkeypatch.setattr(deps, "_check_matter_access", fake_check)
        monkeypatch.setattr("cvp.routers.items.SessionLocal", lambda: seeded_db)
        return TestClient(app), "m1"

    yield _make
    app.dependency_overrides.clear()


def _make_item(seeded_db) -> str:
    item = Item(matter_id="m1", category_id=1, description="thing")
    seeded_db.add(item)
    seeded_db.commit()
    return item.id


def _base_form() -> dict:
    return {
        "description": "thing",
        "category_id": "1",
        "room_id": "",
        "quantity": "1",
        "age_years": "0",
        "condition": "average",
        "retail_unit_dollars": "0",
        "brand": "",
        "model_num": "",
        "notes": "",
        "source_retailer": "",
        "source_url": "",
        "match_type": "exact",
        "acv_override_dollars": "",
        "acv_override_reason": "",
        "confirmed": "false",
    }


def test_assign_existing_group(seeded_db, make_client):
    client, matter_id = make_client()
    item_id = _make_item(seeded_db)
    g = ItemGroup(matter_id=matter_id, name="12", name_normalized="12")
    seeded_db.add(g)
    seeded_db.commit()
    gid = g.id

    form = _base_form()
    form["item_group_id"] = gid
    r = client.patch(f"/api/items/{item_id}", data=form)
    assert r.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.get(Item, item_id).item_group_id == gid


def test_assign_creates_new_group(seeded_db, make_client):
    client, matter_id = make_client()
    item_id = _make_item(seeded_db)

    form = _base_form()
    form["new_item_group_name"] = "Box B"
    r = client.patch(f"/api/items/{item_id}", data=form)
    assert r.status_code == 200
    seeded_db.expire_all()
    groups = seeded_db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
    assert len(groups) == 1 and groups[0].name == "Box B"
    assert seeded_db.get(Item, item_id).item_group_id == groups[0].id


def test_clear_group_with_empty(seeded_db, make_client):
    client, matter_id = make_client()
    item_id = _make_item(seeded_db)
    g = ItemGroup(matter_id=matter_id, name="12", name_normalized="12")
    seeded_db.add(g)
    seeded_db.commit()
    item = seeded_db.get(Item, item_id)
    item.item_group_id = g.id
    seeded_db.commit()

    form = _base_form()
    form["item_group_id"] = ""
    r = client.patch(f"/api/items/{item_id}", data=form)
    assert r.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.get(Item, item_id).item_group_id is None


def test_assign_400_when_group_in_wrong_matter(seeded_db, make_client):
    """A group from another matter must be rejected."""
    other = Matter(id="m2", owner_group_id="ig", created_by_id="ia")
    seeded_db.add(other)
    seeded_db.add(ItemGroup(matter_id="m2", name="x", name_normalized="x"))
    seeded_db.commit()
    other_gid = seeded_db.query(ItemGroup).filter(ItemGroup.matter_id == "m2").first().id

    client, matter_id = make_client()
    item_id = _make_item(seeded_db)

    form = _base_form()
    form["item_group_id"] = other_gid
    r = client.patch(f"/api/items/{item_id}", data=form)
    assert r.status_code == 400


def test_create_item_with_new_group(seeded_db, make_client):
    """POST /api/matters/{id}/items creates a new group when new_item_group_name is set."""
    client, matter_id = make_client(role="contributor")
    form = _base_form()
    form["new_item_group_name"] = "Garage shelf 2"
    r = client.post(f"/api/matters/{matter_id}/items", data=form)
    assert r.status_code == 200
    seeded_db.expire_all()
    groups = seeded_db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
    assert len(groups) == 1
    assert groups[0].name == "Garage shelf 2"
    items = seeded_db.query(Item).filter(Item.matter_id == matter_id).all()
    assert len(items) == 1
    assert items[0].item_group_id == groups[0].id
