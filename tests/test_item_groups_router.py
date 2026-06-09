"""HTTP tests for the item-groups CRUD router."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.dependencies as deps
import cvp.models_access  # noqa: F401 — register matter_access table
import cvp.models_auth  # noqa: F401 — register auth tables
from cvp.auth import hash_password
from cvp.models import Base, Category, EvidenceFile, Item, ItemGroup, Matter
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
    ig = Group(id="ig", name="Internal", kind="internal")
    db_session.add(ig)
    admin = User(
        id="ia",
        email="ia@test.com",
        display_name="Admin",
        password_hash=hash_password("x"),
        system_role="internal_admin",
        group_id="ig",
    )
    db_session.add(admin)
    db_session.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
    matter = Matter(id="m1", owner_group_id="ig", created_by_id="ia")
    db_session.add(matter)
    db_session.commit()
    return db_session


def _client_with_role(seeded_db, monkeypatch, role: str = "manager"):
    """Build a TestClient where the current user holds ``role`` on matter ``m1``.

    role: 'manager' (default) | 'editor' | 'contributor' | 'viewer'
    """
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

    # Permission gate: succeed iff the requested role is at or below `role`.
    # ROLE_HIERARCHY ordering: viewer < contributor < editor < manager.
    levels = {"viewer": 0, "contributor": 1, "editor": 2, "manager": 3}

    def fake_check(db, user, matter_id, required):
        return levels[role] >= levels[required]

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_active_user] = mock_user
    monkeypatch.setattr(deps, "_check_matter_access", fake_check)

    # Route the router's direct SessionLocal() calls to the in-memory DB.
    monkeypatch.setattr("cvp.routers.item_groups.SessionLocal", lambda: seeded_db)

    client = TestClient(app)
    return client, "m1"


def test_create_group(seeded_db, monkeypatch):
    client, matter_id = _client_with_role(seeded_db, monkeypatch)
    r = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "12"})
    assert r.status_code == 200
    groups = seeded_db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
    assert len(groups) == 1
    assert groups[0].name == "12"
    assert groups[0].name_normalized == "12"
    from cvp.main import app

    app.dependency_overrides.clear()


def test_create_duplicate_returns_existing(seeded_db, monkeypatch):
    client, matter_id = _client_with_role(seeded_db, monkeypatch)
    r1 = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "Box A"})
    assert r1.status_code == 200
    r2 = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "box a"})
    assert r2.status_code == 200
    groups = seeded_db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).all()
    assert len(groups) == 1
    from cvp.main import app

    app.dependency_overrides.clear()


def test_create_rejects_empty_name(seeded_db, monkeypatch):
    client, matter_id = _client_with_role(seeded_db, monkeypatch)
    r = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "   "})
    assert r.status_code == 400
    from cvp.main import app

    app.dependency_overrides.clear()


def test_rename_group(seeded_db, monkeypatch):
    client, matter_id = _client_with_role(seeded_db, monkeypatch)
    client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "old"})
    gid = seeded_db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).first().id
    r = client.patch(f"/api/matters/{matter_id}/item-groups/{gid}", data={"name": "new"})
    assert r.status_code == 200
    seeded_db.expire_all()
    g = seeded_db.get(ItemGroup, gid)
    assert g.name == "new"
    assert g.name_normalized == "new"
    from cvp.main import app

    app.dependency_overrides.clear()


def test_delete_group_nulls_item_group_id(seeded_db, monkeypatch):
    client, matter_id = _client_with_role(seeded_db, monkeypatch)
    client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "tmp"})
    g = seeded_db.query(ItemGroup).filter(ItemGroup.matter_id == matter_id).first()
    item = Item(matter_id=matter_id, category_id=1, item_group_id=g.id)
    seeded_db.add(item)
    seeded_db.commit()
    item_id = item.id
    gid = g.id
    r = client.delete(f"/api/matters/{matter_id}/item-groups/{gid}")
    assert r.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.get(ItemGroup, gid) is None
    assert seeded_db.get(Item, item_id).item_group_id is None
    from cvp.main import app

    app.dependency_overrides.clear()


def test_create_requires_role(seeded_db, monkeypatch):
    """A viewer cannot create groups."""
    client, matter_id = _client_with_role(seeded_db, monkeypatch, role="viewer")
    r = client.post(f"/api/matters/{matter_id}/item-groups", data={"name": "12"})
    assert r.status_code == 403
    from cvp.main import app

    app.dependency_overrides.clear()
