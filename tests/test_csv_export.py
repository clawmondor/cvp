"""Unit tests for the Xactimate CSV exporter."""

import csv
import io
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cvp.models import Base, Category, EvidenceFile, Item, Matter, Room, VisionRun
from cvp.services.csv_export import CSV_HEADERS, _dollars, generate_csv


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def matter_with_items(db_session, tmp_path, monkeypatch):
    """Seed one matter, one room, one category, and a mix of items."""
    monkeypatch.setattr("cvp.config.settings.export_dir", str(tmp_path / "exports"))
    monkeypatch.setattr(
        "cvp.services.csv_export.SessionLocal", lambda: db_session
    )

    cat = Category(id=21, name="Electronics, TVs and displays", useful_life_years=7, acv_floor_pct=0.20)
    db_session.add(cat)

    matter = Matter(id=str(uuid.uuid4()), policyholder_name="Test Person")
    db_session.add(matter)

    room = Room(id=str(uuid.uuid4()), matter_id=matter.id, name="Living Room", sort_order=0)
    db_session.add(room)

    # Confirmed item
    item_a = Item(
        id=str(uuid.uuid4()),
        matter_id=matter.id,
        room_id=room.id,
        category_id=21,
        line_number=1,
        description="65-inch Samsung TV",
        brand="Samsung",
        quantity=1,
        age_years=3.0,
        condition="average",
        rcv_unit_cents=120_000,
        rcv_total_cents=120_000,
        acv_total_cents=84_000,
        confirmed=True,
        excluded=False,
        source_retailer="Best Buy",
        source_url="https://bestbuy.com/item/123",
        match_type="exact",
    )
    # Unconfirmed — must be excluded from CSV
    item_b = Item(
        id=str(uuid.uuid4()),
        matter_id=matter.id,
        category_id=21,
        line_number=2,
        description="Unknown TV",
        quantity=1,
        age_years=0.0,
        condition="average",
        rcv_unit_cents=0,
        rcv_total_cents=0,
        acv_total_cents=0,
        confirmed=False,
        excluded=False,
    )
    # Excluded — must be excluded from CSV
    item_c = Item(
        id=str(uuid.uuid4()),
        matter_id=matter.id,
        category_id=21,
        line_number=3,
        description="Broken TV",
        quantity=1,
        age_years=10.0,
        condition="below_average",
        rcv_unit_cents=50_000,
        rcv_total_cents=50_000,
        acv_total_cents=10_000,
        confirmed=True,
        excluded=True,
    )
    db_session.add_all([item_a, item_b, item_c])
    db_session.commit()
    return matter, [item_a]


def _read_csv(path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        lines = f.readlines()
    # Skip comment line
    data_lines = [l for l in lines if not l.startswith("#")]
    reader = csv.DictReader(io.StringIO("".join(data_lines)))
    return reader.fieldnames or [], list(reader)


def test_csv_headers(matter_with_items, tmp_path):
    matter, _ = matter_with_items
    path = generate_csv(matter.id)
    headers, _ = _read_csv(path)
    assert headers == CSV_HEADERS


def test_csv_row_count_confirmed_only(matter_with_items, tmp_path):
    matter, confirmed = matter_with_items
    path = generate_csv(matter.id)
    _, rows = _read_csv(path)
    assert len(rows) == len(confirmed)


def test_csv_currency_formatting(matter_with_items, tmp_path):
    matter, _ = matter_with_items
    path = generate_csv(matter.id)
    _, rows = _read_csv(path)
    row = rows[0]
    assert row["UnitPrice"] == "1200.00"
    assert row["Total"] == "1200.00"
    assert row["ACV"] == "840.00"
    assert row["Depreciation"] == "360.00"


def test_csv_room_and_category(matter_with_items, tmp_path):
    matter, _ = matter_with_items
    path = generate_csv(matter.id)
    _, rows = _read_csv(path)
    row = rows[0]
    assert row["Room"] == "Living Room"
    assert row["Category"] == "Electronics, TVs and displays"


def test_csv_notes_concat(matter_with_items, tmp_path):
    matter, _ = matter_with_items
    path = generate_csv(matter.id)
    _, rows = _read_csv(path)
    row = rows[0]
    assert "Best Buy" in row["Notes"]
    assert "bestbuy.com" in row["Notes"]
    assert "exact" in row["Notes"]


def test_dollars_helper():
    assert _dollars(0) == "0.00"
    assert _dollars(100) == "1.00"
    assert _dollars(123456) == "1234.56"
