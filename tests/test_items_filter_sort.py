"""Unit tests for the items sort/filter query builder + querystring helpers."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, Item, Matter, Room
from cvp.routers.items import (
    ItemFilters,
    _build_items_query,
    _count_items,
    _sort_state,
    items_query_string,
)

MATTER_ID = "m-fs"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Matter(id=MATTER_ID, policyholder_name="P", loss_type="total_loss"))
    s.add(Category(id=1, name="Appliances", useful_life_years=10, acv_floor_pct=0.2))
    s.add(Category(id=2, name="Bedding", useful_life_years=5, acv_floor_pct=0.2))
    s.add(Room(id="r-kit", matter_id=MATTER_ID, name="Kitchen", sort_order=0))
    s.add(Room(id="r-bed", matter_id=MATTER_ID, name="Bedroom", sort_order=1))
    s.commit()
    yield s
    s.close()


def _add(db, **kw):
    defaults = dict(
        matter_id=MATTER_ID,
        category_id=1,
        quantity=1,
        age_years=0.0,
        condition="average",
        retail_unit_cents=0,
        rcv_total_cents=0,
        acv_total_cents=0,
        confirmed=True,
        excluded=False,
    )
    defaults.update(kw)
    it = Item(**defaults)
    db.add(it)
    db.commit()
    return it


def _descs(rows):
    return [r.description for r in rows]


def test_default_sort_is_line_number_asc(db):
    _add(db, line_number=2, description="b")
    _add(db, line_number=1, description="a")
    rows = _build_items_query(db, MATTER_ID, ItemFilters()).all()
    assert _descs(rows) == ["a", "b"]


def test_sort_rcv_total_desc(db):
    _add(db, line_number=1, description="cheap", rcv_total_cents=100)
    _add(db, line_number=2, description="pricey", rcv_total_cents=9999)
    f = ItemFilters(sort="rcv_total", dir="desc")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["pricey", "cheap"]


def test_sort_condition_ranks_excellent_first(db):
    _add(db, line_number=1, description="avg", condition="average")
    _add(db, line_number=2, description="exc", condition="excellent")
    _add(db, line_number=3, description="low", condition="below_average")
    f = ItemFilters(sort="condition", dir="asc")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["exc", "avg", "low"]


def test_sort_room_by_name(db):
    _add(db, line_number=1, description="k", room_id="r-kit")  # Kitchen
    _add(db, line_number=2, description="b", room_id="r-bed")  # Bedroom
    f = ItemFilters(sort="room", dir="asc")
    # Bedroom < Kitchen alphabetically
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["b", "k"]


def test_sort_status_asc_surfaces_active_unconfirmed_first(db):
    _add(db, line_number=1, description="conf", confirmed=True, excluded=False)
    _add(db, line_number=2, description="todo", confirmed=False, excluded=False)
    _add(db, line_number=3, description="excl", confirmed=True, excluded=True)
    f = ItemFilters(sort="status", dir="asc")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["todo", "conf", "excl"]


def test_filter_by_room(db):
    _add(db, line_number=1, description="k", room_id="r-kit")
    _add(db, line_number=2, description="b", room_id="r-bed")
    f = ItemFilters(room_id="r-kit")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["k"]


def test_filter_by_category(db):
    _add(db, line_number=1, description="app", category_id=1)
    _add(db, line_number=2, description="bed", category_id=2)
    f = ItemFilters(category_id="2")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["bed"]


def test_filter_status_missing_price(db):
    _add(db, line_number=1, description="priced", confirmed=True, retail_unit_cents=500)
    _add(db, line_number=2, description="noprice", confirmed=True, retail_unit_cents=0)
    _add(db, line_number=3, description="draft", confirmed=False, retail_unit_cents=0)
    f = ItemFilters(status="missing_price")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["noprice"]


def test_filter_text_matches_brand(db):
    _add(db, line_number=1, description="tv", brand="Samsung")
    _add(db, line_number=2, description="couch", brand="Ashley")
    f = ItemFilters(q="samsung")
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["tv"]


def test_count_items_respects_filters(db):
    _add(db, line_number=1, description="a", room_id="r-kit")
    _add(db, line_number=2, description="b", room_id="r-kit")
    _add(db, line_number=3, description="c", room_id="r-bed")
    assert _count_items(db, MATTER_ID, ItemFilters(room_id="r-kit")) == 2
    assert _count_items(db, MATTER_ID, ItemFilters()) == 3


def test_unknown_sort_falls_back_to_line(db):
    _add(db, line_number=2, description="b")
    _add(db, line_number=1, description="a")
    f = ItemFilters(sort="bogus", dir="weird")
    # Bad sort/dir default to line asc (fallback happens in _parse; builder
    # also treats unknown sort keys as line).
    assert _descs(_build_items_query(db, MATTER_ID, f).all()) == ["a", "b"]


def test_query_string_omits_defaults():
    assert items_query_string(ItemFilters()) == ""


def test_query_string_includes_active_filters_and_sort():
    f = ItemFilters(room_id="r-kit", status="unconfirmed", sort="rcv_total", dir="desc")
    qs = items_query_string(f)
    assert "room_id=r-kit" in qs
    assert "status=unconfirmed" in qs
    assert "sort=rcv_total" in qs
    assert "dir=desc" in qs


def test_sort_state_toggles_active_column():
    # Active column asc -> link flips to desc, indicator ▲
    qs, indicator = _sort_state(ItemFilters(sort="qty", dir="asc"), "qty")
    assert "sort=qty" in qs and "dir=desc" in qs
    assert indicator == "▲"
    # Inactive column -> link is asc, no indicator
    qs2, indicator2 = _sort_state(ItemFilters(sort="qty", dir="asc"), "age")
    assert "sort=age" in qs2 and "dir=asc" in qs2
    assert indicator2 == ""
