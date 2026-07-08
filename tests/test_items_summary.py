"""Tests for the items-totals helper and the items-summary endpoint."""

import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_vision  # noqa: F401
from claimos.db import get_db
from claimos.dependencies import CurrentUser
from claimos.main import app
from claimos.models import Base, Category, Item, Matter
from claimos.models_auth import User
from claimos.routers.items import compute_items_totals
from claimos.services import access_cache

MATTER_ID = "m-totals"


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
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.commit()
    yield s
    s.close()


def _add_item(db, *, line, confirmed, excluded, rcv_total, acv_total, rcv_unit):
    db.add(
        Item(
            matter_id=MATTER_ID,
            category_id=1,
            line_number=line,
            description=f"item {line}",
            quantity=1,
            age_years=0.0,
            condition="average",
            rcv_unit_cents=rcv_unit,
            rcv_total_cents=rcv_total,
            acv_total_cents=acv_total,
            confirmed=confirmed,
            excluded=excluded,
        )
    )


def test_totals_count_only_confirmed_not_excluded(db_session):
    # confirmed + not excluded -> counted
    _add_item(
        db_session,
        line=1,
        confirmed=True,
        excluded=False,
        rcv_total=10000,
        acv_total=8000,
        rcv_unit=10000,
    )
    # confirmed but excluded -> not counted in money totals
    _add_item(
        db_session,
        line=2,
        confirmed=True,
        excluded=True,
        rcv_total=5000,
        acv_total=4000,
        rcv_unit=5000,
    )
    # unconfirmed (draft from a scan) -> not counted in money totals
    _add_item(
        db_session,
        line=3,
        confirmed=False,
        excluded=False,
        rcv_total=9999,
        acv_total=9999,
        rcv_unit=0,
    )
    db_session.commit()

    totals = compute_items_totals(MATTER_ID, db_session)

    assert totals["items_total_count"] == 3
    assert totals["items_confirmed_count"] == 1
    assert totals["items_rcv_total_cents"] == 10000
    assert totals["items_acv_total_cents"] == 8000
    assert totals["unconfirmed_count"] == 1
    assert totals["missing_price_count"] == 0


def test_missing_price_counts_confirmed_zero_rcv(db_session):
    _add_item(
        db_session, line=1, confirmed=True, excluded=False, rcv_total=0, acv_total=0, rcv_unit=0
    )
    db_session.commit()
    totals = compute_items_totals(MATTER_ID, db_session)
    assert totals["missing_price_count"] == 1


# ---------------------------------------------------------------------------
# Endpoint tests — GET /api/matters/{matter_id}/items-summary
# ---------------------------------------------------------------------------

VIEWER_ID = "v-totals"


@pytest.fixture(autouse=True)
def _clear_access_cache():
    access_cache._cache.clear()
    yield
    access_cache._cache.clear()


@pytest.fixture
def client(db_session, monkeypatch):
    db_session.add(
        User(id=VIEWER_ID, email="v@t.com", display_name="V", system_role="internal_user")
    )
    db_session.commit()

    import claimos.routers.items as items_router

    async def mock_viewer():
        return CurrentUser(
            id=VIEWER_ID,
            email="v@t.com",
            system_role="internal_user",
            group_id=None,
            group_kind="internal",
        )

    def override_get_db():
        yield db_session

    dep = inspect.signature(items_router.get_items_summary).parameters["user"].default.dependency
    app.dependency_overrides[dep] = mock_viewer
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("claimos.routers.items.SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_items_summary_renders_totals(client, db_session):
    _add_item(
        db_session,
        line=1,
        confirmed=True,
        excluded=False,
        rcv_total=10000,
        acv_total=8000,
        rcv_unit=10000,
    )
    db_session.commit()
    resp = client.get(f"/api/matters/{MATTER_ID}/items-summary")
    assert resp.status_code == 200
    body = resp.text
    assert 'id="items-summary"' in body
    assert "$100.00" in body  # RCV total
    assert "$80.00" in body  # ACV total
    assert 'hx-trigger="item-created from:body"' in body


def test_items_summary_empty_matter_renders_no_totals_row(client):
    resp = client.get(f"/api/matters/{MATTER_ID}/items-summary")
    assert resp.status_code == 200
    assert 'id="items-summary"' in resp.text
    assert "RCV total" not in resp.text
