"""Unit tests for cvp.services.export_templates."""

from uuid import uuid4

import pytest

from cvp.db import SessionLocal
from cvp.services import export_templates as svc


def test_validate_rejects_empty_name():
    with pytest.raises(ValueError):
        svc.validate("", "line_number", [svc.ColumnSpec("description", None, None)])


def test_validate_rejects_no_columns():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [])


def test_validate_rejects_unknown_field_key():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [svc.ColumnSpec("nope", None, None)])


def test_validate_rejects_bad_sort_field():
    with pytest.raises(ValueError):
        svc.validate("T", "bogus", [svc.ColumnSpec("description", None, None)])


def test_validate_rejects_column_with_both_field_and_static():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [svc.ColumnSpec("description", None, "x")])


def test_validate_rejects_static_without_header():
    with pytest.raises(ValueError):
        svc.validate("T", "line_number", [svc.ColumnSpec(None, "", "x")])


def test_validate_accepts_valid_mix():
    svc.validate(
        "Carrier packet",
        "room",
        [
            svc.ColumnSpec("line_number", None, None),
            svc.ColumnSpec("description", "Item", None),
            svc.ColumnSpec(None, "Firm", "Roe LLP"),
        ],
    )


def test_xactimate_defaults_are_valid_and_ordered():
    cols = svc.xactimate_default_columns()
    assert [c.field_key for c in cols][:3] == ["line_number", "description", "quantity"]
    svc.validate("Xactimate", "line_number", cols)  # must not raise


def test_create_update_delete_roundtrip():
    group_id = "grp-" + uuid4().hex
    db = SessionLocal()
    try:
        t = svc.create_template(
            db,
            group_id=group_id,
            created_by_id="u1",
            name="Packet",
            description="",
            include_needs_review=False,
            include_excluded=False,
            sort_field="line_number",
            columns=[
                svc.ColumnSpec("description", None, None),
                svc.ColumnSpec(None, "Firm", "Roe"),
            ],
        )
        assert t.id
        assert [c.position for c in t.columns] == [0, 1]

        got = svc.get_template(db, t.id, group_id)
        assert got is not None
        assert svc.get_template(db, t.id, "other-group") is None  # cross-group isolation

        svc.update_template(
            db,
            t,
            name="Packet v2",
            description="d",
            include_needs_review=True,
            include_excluded=True,
            sort_field="room",
            columns=[svc.ColumnSpec("room", None, None)],
        )
        got = svc.get_template(db, t.id, group_id)
        assert got.name == "Packet v2"
        assert got.include_needs_review is True
        assert [c.field_key for c in got.columns] == ["room"]  # old columns replaced

        svc.delete_template(db, got)
        assert svc.get_template(db, t.id, group_id) is None
    finally:
        db.close()
