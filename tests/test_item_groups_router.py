"""HTTP tests for the item-groups CRUD router."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.dependencies as deps
import claimos.models_access  # noqa: F401 — register claim_access table
import claimos.models_auth  # noqa: F401 — register auth tables
from claimos.auth import hash_password
from claimos.models import Base, Category, Claim, EvidenceFile, Item, ItemGroup
from claimos.models_auth import Group, User


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
    claim = Claim(id="m1", owner_group_id="ig", created_by_id="ia")
    db_session.add(claim)
    db_session.commit()
    return db_session


@pytest.fixture
def make_client(seeded_db, monkeypatch):
    """Factory: returns ``(client, claim_id)`` for the given role on claim 'm1'."""
    from claimos.db import get_db
    from claimos.dependencies import CurrentUser, require_active_user
    from claimos.main import app

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

    def _make(role: str = "manager"):
        def fake_check(db, user, claim_id, required, object_type=None):
            return levels[role] >= levels[required]

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[require_active_user] = mock_user
        monkeypatch.setattr(deps, "_check_claim_access", fake_check)
        monkeypatch.setattr("claimos.routers.item_groups.SessionLocal", lambda: seeded_db)
        monkeypatch.setattr("claimos.routers.claims.SessionLocal", lambda: seeded_db)
        return TestClient(app), "m1"

    yield _make
    app.dependency_overrides.clear()


def test_create_group(seeded_db, make_client):
    client, claim_id = make_client()
    r = client.post(f"/api/claims/{claim_id}/item-groups", data={"name": "12"})
    assert r.status_code == 200
    groups = seeded_db.query(ItemGroup).filter(ItemGroup.claim_id == claim_id).all()
    assert len(groups) == 1
    assert groups[0].name == "12"
    assert groups[0].name_normalized == "12"


def test_create_duplicate_returns_existing(seeded_db, make_client):
    client, claim_id = make_client()
    r1 = client.post(f"/api/claims/{claim_id}/item-groups", data={"name": "Box A"})
    assert r1.status_code == 200
    r2 = client.post(f"/api/claims/{claim_id}/item-groups", data={"name": "box a"})
    assert r2.status_code == 200
    groups = seeded_db.query(ItemGroup).filter(ItemGroup.claim_id == claim_id).all()
    assert len(groups) == 1


def test_create_rejects_empty_name(seeded_db, make_client):
    client, claim_id = make_client()
    r = client.post(f"/api/claims/{claim_id}/item-groups", data={"name": "   "})
    assert r.status_code == 400


def test_rename_group(seeded_db, make_client):
    client, claim_id = make_client()
    client.post(f"/api/claims/{claim_id}/item-groups", data={"name": "old"})
    gid = seeded_db.query(ItemGroup).filter(ItemGroup.claim_id == claim_id).first().id
    r = client.patch(f"/api/claims/{claim_id}/item-groups/{gid}", data={"name": "new"})
    assert r.status_code == 200
    seeded_db.expire_all()
    g = seeded_db.get(ItemGroup, gid)
    assert g.name == "new"
    assert g.name_normalized == "new"


def test_delete_group_nulls_item_and_evidence_pin(seeded_db, make_client):
    client, claim_id = make_client()
    client.post(f"/api/claims/{claim_id}/item-groups", data={"name": "tmp"})
    g = seeded_db.query(ItemGroup).filter(ItemGroup.claim_id == claim_id).first()
    item = Item(claim_id=claim_id, category_id=1, item_group_id=g.id)
    ef = EvidenceFile(
        claim_id=claim_id,
        filename="x.jpg",
        stored_path="x.jpg",
        pinned_item_group_id=g.id,
    )
    seeded_db.add_all([item, ef])
    seeded_db.commit()
    item_id, ef_id, gid = item.id, ef.id, g.id

    r = client.delete(f"/api/claims/{claim_id}/item-groups/{gid}")
    assert r.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.get(ItemGroup, gid) is None
    assert seeded_db.get(Item, item_id).item_group_id is None
    assert seeded_db.get(EvidenceFile, ef_id).pinned_item_group_id is None


def test_create_requires_role(seeded_db, make_client):
    """A viewer cannot create groups."""
    client, claim_id = make_client(role="viewer")
    r = client.post(f"/api/claims/{claim_id}/item-groups", data={"name": "12"})
    assert r.status_code == 403


def test_rename_wrong_claim_returns_404(seeded_db, make_client):
    """PATCH and DELETE via the wrong claim_id return 404."""
    other = Claim(id="m2", owner_group_id="ig", created_by_id="ia")
    seeded_db.add(other)
    seeded_db.add(ItemGroup(claim_id="m2", name="other-12", name_normalized="other-12"))
    seeded_db.commit()
    gid = seeded_db.query(ItemGroup).filter(ItemGroup.claim_id == "m2").first().id

    client, claim_id = make_client()  # user has access to m1, not m2
    r = client.patch(f"/api/claims/{claim_id}/item-groups/{gid}", data={"name": "x"})
    assert r.status_code == 404

    r = client.delete(f"/api/claims/{claim_id}/item-groups/{gid}")
    assert r.status_code == 404


def test_pin_evidence_to_group(seeded_db, make_client):
    client, claim_id = make_client(role="editor")
    g = ItemGroup(claim_id=claim_id, name="12", name_normalized="12")
    seeded_db.add(g)
    seeded_db.commit()
    gid = g.id
    ef = EvidenceFile(claim_id=claim_id, filename="a.jpg", stored_path="a.jpg")
    seeded_db.add(ef)
    seeded_db.commit()
    ef_id = ef.id

    r = client.patch(
        f"/api/claims/{claim_id}/evidence/{ef_id}/item-group",
        data={"item_group_id": gid},
    )
    assert r.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.get(EvidenceFile, ef_id).pinned_item_group_id == gid


def test_pin_evidence_clear_with_empty_value(seeded_db, make_client):
    client, claim_id = make_client(role="editor")
    g = ItemGroup(claim_id=claim_id, name="12", name_normalized="12")
    seeded_db.add(g)
    seeded_db.commit()
    gid = g.id
    ef = EvidenceFile(
        claim_id=claim_id,
        filename="a.jpg",
        stored_path="a.jpg",
        pinned_item_group_id=gid,
    )
    seeded_db.add(ef)
    seeded_db.commit()
    ef_id = ef.id

    r = client.patch(
        f"/api/claims/{claim_id}/evidence/{ef_id}/item-group",
        data={"item_group_id": ""},
    )
    assert r.status_code == 200
    seeded_db.expire_all()
    assert seeded_db.get(EvidenceFile, ef_id).pinned_item_group_id is None


def test_pin_evidence_new_group_name_creates(seeded_db, make_client):
    client, claim_id = make_client(role="editor")
    ef = EvidenceFile(claim_id=claim_id, filename="a.jpg", stored_path="a.jpg")
    seeded_db.add(ef)
    seeded_db.commit()
    ef_id = ef.id

    r = client.patch(
        f"/api/claims/{claim_id}/evidence/{ef_id}/item-group",
        data={"new_item_group_name": "Box C"},
    )
    assert r.status_code == 200
    seeded_db.expire_all()
    groups = seeded_db.query(ItemGroup).filter(ItemGroup.claim_id == claim_id).all()
    assert len(groups) == 1 and groups[0].name == "Box C"
    assert seeded_db.get(EvidenceFile, ef_id).pinned_item_group_id == groups[0].id


def test_pin_evidence_wrong_claim_returns_404(seeded_db, make_client):
    """Pinning evidence from a different claim must 404."""
    other = Claim(id="m2", owner_group_id="ig", created_by_id="ia")
    seeded_db.add(other)
    ef = EvidenceFile(claim_id="m2", filename="other.jpg", stored_path="other.jpg")
    seeded_db.add(ef)
    seeded_db.commit()
    ef_id = ef.id

    client, claim_id = make_client(role="editor")  # access to m1, not m2
    r = client.patch(
        f"/api/claims/{claim_id}/evidence/{ef_id}/item-group",
        data={"new_item_group_name": "Box X"},
    )
    assert r.status_code == 404


def test_claim_detail_renames_rooms_tab(seeded_db, make_client):
    client, claim_id = make_client(role="viewer")
    r = client.get(f"/claims/{claim_id}")
    assert r.status_code == 200
    assert "Rooms &amp; Groups" in r.text


def test_claim_detail_groups_panel_empty_state(seeded_db, make_client):
    client, claim_id = make_client(role="viewer")
    r = client.get(f"/claims/{claim_id}")
    assert r.status_code == 200
    assert "No groups yet" in r.text


def test_claim_detail_groups_panel_shows_group(seeded_db, make_client):
    seeded_db.add(ItemGroup(claim_id="m1", name="12", name_normalized="12"))
    seeded_db.commit()
    client, claim_id = make_client(role="viewer")
    r = client.get(f"/claims/{claim_id}")
    assert r.status_code == 200
    assert "12" in r.text
    assert "0 items" in r.text


def test_evidence_grid_includes_group_dropdown(seeded_db, make_client):
    ef = EvidenceFile(claim_id="m1", filename="a.jpg", stored_path="a.jpg", kind="image")
    seeded_db.add(ef)
    seeded_db.commit()

    client, claim_id = make_client(role="viewer")
    r = client.get(f"/claims/{claim_id}")
    assert r.status_code == 200
    body = r.text
    assert f'data-evidence-group-select="{ef.id}"' in body
    assert "Auto-detect" in body
    assert "+ New group" in body


def test_evidence_grid_dropdown_shows_groups(seeded_db, make_client):
    seeded_db.add(ItemGroup(claim_id="m1", name="Box A", name_normalized="box a"))
    seeded_db.add(EvidenceFile(claim_id="m1", filename="a.jpg", stored_path="a.jpg", kind="image"))
    seeded_db.commit()

    client, claim_id = make_client(role="viewer")
    r = client.get(f"/claims/{claim_id}")
    assert r.status_code == 200
    assert "Box A" in r.text


def test_evidence_grid_dropdown_preselects_pinned_group(seeded_db, make_client):
    g = ItemGroup(claim_id="m1", name="12", name_normalized="12")
    seeded_db.add(g)
    seeded_db.flush()
    ef = EvidenceFile(
        claim_id="m1",
        filename="a.jpg",
        stored_path="a.jpg",
        kind="image",
        pinned_item_group_id=g.id,
    )
    seeded_db.add(ef)
    seeded_db.commit()

    client, claim_id = make_client(role="viewer")
    r = client.get(f"/claims/{claim_id}")
    assert r.status_code == 200
    # The pinned group's option should carry "selected" attribute.
    # Auto-detect should NOT be selected.
    body = r.text
    # Crude but effective: find the substring "<option value="{gid}" selected"
    assert f'value="{g.id}" selected' in body
