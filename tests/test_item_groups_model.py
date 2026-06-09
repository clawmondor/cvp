"""Sanity tests for the ItemGroup ORM model."""

import pytest
from sqlalchemy.exc import IntegrityError

from cvp.db import SessionLocal
from cvp.models import ItemGroup, Matter


@pytest.fixture
def matter_id() -> str:
    db = SessionLocal()
    try:
        m = Matter(firm_name="Test Firm")
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_item_group_can_be_created(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g = ItemGroup(matter_id=matter_id, name="12", name_normalized="12")
        db.add(g)
        db.commit()
        db.refresh(g)
        assert g.id
        assert g.matter_id == matter_id
        assert g.name == "12"
        assert g.name_normalized == "12"
        assert g.created_at is not None
    finally:
        db.close()


def test_item_group_unique_constraint(matter_id: str) -> None:
    db = SessionLocal()
    try:
        first = ItemGroup(matter_id=matter_id, name="Box A", name_normalized="box a")
        db.add(first)
        db.commit()
        db.refresh(first)
        assert first.id

        db.add(ItemGroup(matter_id=matter_id, name="box a", name_normalized="box a"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
