"""Unit tests for claimos.services.item_groups.find_or_create."""

import pytest
from sqlalchemy import func, select

from claimos.db import SessionLocal
from claimos.models import ItemGroup, Matter
from claimos.services.item_groups import find_or_create


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
        ("Garage shelf 2", "garage shelf 2"),
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
        count = db.execute(
            select(func.count(ItemGroup.id)).where(
                ItemGroup.name_normalized == "12",
                ItemGroup.matter_id.in_([matter_id, other.id]),
            )
        ).scalar_one()
        assert count == 2
    finally:
        db.close()


def test_savepoint_isolates_race_recovery(matter_id: str) -> None:
    """When IntegrityError fires (race), the caller's outer work must survive."""
    db = SessionLocal()
    try:
        # Pre-create the group from a different "session" so our find_or_create
        # call definitely loses the race when it tries to insert.
        other = SessionLocal()
        try:
            other.add(ItemGroup(matter_id=matter_id, name="raced", name_normalized="raced"))
            other.commit()
        finally:
            other.close()

        # Outer work the caller is in the middle of.
        m_extra = Matter(firm_name="Caller's Pending Work")
        db.add(m_extra)
        db.flush()  # caller has pending state in this session
        pending_id = m_extra.id

        # Trigger the find_or_create against an in-memory copy of ItemGroup that
        # is not yet aware of the row our `other` session inserted. The
        # select-then-insert lookup will miss, the insert will violate the unique
        # index, and the SAVEPOINT recovery branch will re-query.
        g = find_or_create(db, matter_id, "RACED")
        db.commit()

        # The recovered group exists and is the one the other session inserted.
        assert g.name == "raced"

        # And — critically — the caller's pending Matter is still committed,
        # because the SAVEPOINT only rolled back the failed sub-insert.
        assert db.get(Matter, pending_id) is not None
    finally:
        db.close()
