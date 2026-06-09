"""Unit tests for cvp.services.item_groups.find_or_create."""

import pytest

from cvp.db import SessionLocal
from cvp.models import ItemGroup, Matter
from cvp.services.item_groups import find_or_create


@pytest.fixture
def matter_id() -> str:
    db = SessionLocal()
    try:
        m = Matter(firm_name="Test")
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_creates_when_missing(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g = find_or_create(db, matter_id, "12")
        db.commit()
        assert g.id
        assert g.name == "12"
        assert g.name_normalized == "12"
    finally:
        db.close()


def test_reuses_exact_match(matter_id: str) -> None:
    db = SessionLocal()
    try:
        g1 = find_or_create(db, matter_id, "Box A")
        db.commit()
        g2 = find_or_create(db, matter_id, "Box A")
        db.commit()
        assert g1.id == g2.id
    finally:
        db.close()


@pytest.mark.parametrize(
    "first,second",
    [
        ("12", " 12 "),
        ("12", "12 "),
        ("Box A", "box a"),
        ("Box A", "BOX A"),
        ("  Garage shelf 2  ", "garage shelf 2"),
    ],
)
def test_dedupes_case_and_whitespace(matter_id: str, first: str, second: str) -> None:
    db = SessionLocal()
    try:
        g1 = find_or_create(db, matter_id, first)
        db.commit()
        g2 = find_or_create(db, matter_id, second)
        db.commit()
        assert g1.id == g2.id
    finally:
        db.close()


def test_rejects_empty_name(matter_id: str) -> None:
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            find_or_create(db, matter_id, "")
        with pytest.raises(ValueError):
            find_or_create(db, matter_id, "   ")
    finally:
        db.close()


def test_scoped_per_matter(matter_id: str) -> None:
    db = SessionLocal()
    try:
        other = Matter(firm_name="Other")
        db.add(other)
        db.commit()
        db.refresh(other)
        g1 = find_or_create(db, matter_id, "12")
        g2 = find_or_create(db, other.id, "12")
        db.commit()
        assert g1.id != g2.id
        # Confirm exactly one group per matter (scoped to these two matters).
        count = (
            db.query(ItemGroup)
            .filter(
                ItemGroup.name_normalized == "12",
                ItemGroup.matter_id.in_([matter_id, other.id]),
            )
            .count()
        )
        assert count == 2
    finally:
        db.close()
