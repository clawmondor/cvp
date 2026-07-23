"""Sanity tests for the ItemGroup ORM model."""

import pytest
from sqlalchemy.exc import IntegrityError

from claimos.db import SessionLocal
from claimos.models import Claim, ItemGroup


@pytest.fixture
def claim_id() -> str:
    db = SessionLocal()
    try:
        m = Claim(firm_name="Test Firm", nickname="Test Claim")
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_item_group_can_be_created(claim_id: str) -> None:
    db = SessionLocal()
    try:
        g = ItemGroup(claim_id=claim_id, name="12", name_normalized="12")
        db.add(g)
        db.commit()
        db.refresh(g)
        assert g.id
        assert g.claim_id == claim_id
        assert g.name == "12"
        assert g.name_normalized == "12"
        assert g.created_at is not None
    finally:
        db.close()


def test_item_group_unique_constraint(claim_id: str) -> None:
    db = SessionLocal()
    try:
        first = ItemGroup(claim_id=claim_id, name="Box A", name_normalized="box a")
        db.add(first)
        db.commit()
        db.refresh(first)
        assert first.id

        db.add(ItemGroup(claim_id=claim_id, name="box a", name_normalized="box a"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
