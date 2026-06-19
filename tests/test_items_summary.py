"""Tests for the items-totals helper and the items-summary endpoint."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, Item, Matter
from cvp.routers.items import compute_items_totals

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
