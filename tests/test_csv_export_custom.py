"""Unit tests for custom-template CSV export (generate_custom_csv)."""

import csv
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cvp.models import (
    Base,
    Category,
    ExportTemplate,
    ExportTemplateColumn,
    Item,
    Matter,
    Room,
)
from cvp.services import csv_export


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared in-memory connection
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _seed(
    db,
    tmp_path,
    monkeypatch,
    *,
    include_excluded=False,
    include_needs_review=False,
    sort_field="line_number",
):
    monkeypatch.setattr(csv_export.settings, "export_dir", str(tmp_path))
    db.add(Category(id=1, name="Furniture", acv_floor_pct=0.2))
    matter = Matter(id="m1", policyholder_name="Jane Roe", firm_name="Roe LLP", owner_group_id="g1")
    room = Room(id="r1", matter_id="m1", name="Den")
    db.add_all([matter, room])
    db.add_all(
        [
            Item(
                id="i1",
                matter_id="m1",
                room_id="r1",
                category_id=1,
                line_number=1,
                description="Sofa",
                quantity=1,
                retail_unit_cents=100000,
                rcv_total_cents=100000,
                acv_total_cents=60000,
                confirmed=True,
                excluded=False,
                needs_review=False,
            ),
            Item(
                id="i2",
                matter_id="m1",
                room_id="r1",
                category_id=1,
                line_number=2,
                description="Lamp",
                quantity=1,
                retail_unit_cents=5000,
                rcv_total_cents=5000,
                acv_total_cents=3000,
                confirmed=True,
                excluded=True,
                needs_review=False,
            ),
            Item(
                id="i3",
                matter_id="m1",
                room_id="r1",
                category_id=1,
                line_number=3,
                description="Rug",
                quantity=1,
                retail_unit_cents=20000,
                rcv_total_cents=20000,
                acv_total_cents=12000,
                confirmed=True,
                excluded=False,
                needs_review=True,
            ),
        ]
    )
    t = ExportTemplate(
        id="t1",
        group_id="g1",
        name="Packet",
        sort_field=sort_field,
        include_excluded=include_excluded,
        include_needs_review=include_needs_review,
    )
    t.columns = [
        ExportTemplateColumn(position=0, field_key="line_number", header_label=None),
        ExportTemplateColumn(position=1, field_key="description", header_label="Item"),
        ExportTemplateColumn(position=2, field_key="acv_total", header_label=None),
        ExportTemplateColumn(
            position=3, field_key=None, header_label="Firm", static_value="Roe LLP"
        ),
    ]
    db.add(t)
    db.commit()


def _read(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0].startswith("# Confidential — Attorney Work Product")
    reader = csv.reader(lines[1:])
    return list(reader)


def test_custom_csv_columns_headers_and_default_filter(db_session, tmp_path, monkeypatch):
    _seed(db_session, tmp_path, monkeypatch)
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    path = csv_export.generate_custom_csv("m1", "t1")
    rows = _read(path)
    assert rows[0] == ["LineItem", "Item", "ACV", "Firm"]
    # default filter: confirmed & not excluded & not needs_review -> only Sofa (i1)
    assert rows[1] == ["1", "Sofa", "600.00", "Roe LLP"]
    assert len(rows) == 2


def test_custom_csv_filename_includes_time(db_session, tmp_path, monkeypatch):
    """Filename embeds date + HHMM so same-day re-exports don't clobber each other."""
    _seed(db_session, tmp_path, monkeypatch)
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    path = csv_export.generate_custom_csv("m1", "t1")
    # Expected suffix: contents_<slug>_YYYYMMDD_HHMMSS.csv
    stem = path.stem  # e.g. "contents_my-template_20260824_143059"
    date_part, time_part = stem.rsplit("_", 2)[-2:]
    assert re.fullmatch(r"\d{8}", date_part)
    assert re.fullmatch(r"\d{6}", time_part)


def test_include_toggles_add_rows(db_session, tmp_path, monkeypatch):
    _seed(db_session, tmp_path, monkeypatch, include_excluded=True, include_needs_review=True)
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    rows = _read(csv_export.generate_custom_csv("m1", "t1"))
    descriptions = [r[1] for r in rows[1:]]
    assert descriptions == ["Sofa", "Lamp", "Rug"]  # all three now included


def test_sort_by_description(db_session, tmp_path, monkeypatch):
    _seed(
        db_session,
        tmp_path,
        monkeypatch,
        include_excluded=True,
        include_needs_review=True,
        sort_field="description",
    )
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    rows = _read(csv_export.generate_custom_csv("m1", "t1"))
    assert [r[1] for r in rows[1:]] == ["Lamp", "Rug", "Sofa"]


def test_wrong_group_template_rejected(db_session, tmp_path, monkeypatch):
    _seed(db_session, tmp_path, monkeypatch)
    monkeypatch.setattr(csv_export, "SessionLocal", lambda: db_session)
    db_session.query(Matter).filter_by(id="m1").update({"owner_group_id": "other"})
    db_session.commit()
    try:
        csv_export.generate_custom_csv("m1", "t1")
        assert False, "expected ValueError"
    except ValueError:
        pass
