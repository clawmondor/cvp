"""Tests confirming Item.item_group_id and EvidenceFile.pinned_item_group_id exist."""

import pytest

from claimos.db import SessionLocal
from claimos.models import Category, Claim, EvidenceFile, Item, ItemGroup


@pytest.fixture
def claim_id() -> str:
    db = SessionLocal()
    try:
        m = Claim(firm_name="Test", nickname="Test Claim")
        db.add(m)
        # Make sure at least one category exists for Item creation.
        if db.query(Category).count() == 0:
            db.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_item_can_reference_item_group(claim_id: str) -> None:
    db = SessionLocal()
    try:
        g = ItemGroup(claim_id=claim_id, name="12", name_normalized="12")
        db.add(g)
        db.commit()
        db.refresh(g)
        cat = db.query(Category).first()
        item = Item(claim_id=claim_id, category_id=cat.id, item_group_id=g.id)
        db.add(item)
        db.commit()
        db.refresh(item)
        assert item.item_group_id == g.id
    finally:
        db.close()


def test_item_group_id_nullable(claim_id: str) -> None:
    db = SessionLocal()
    try:
        cat = db.query(Category).first()
        item = Item(claim_id=claim_id, category_id=cat.id)
        db.add(item)
        db.commit()
        db.refresh(item)
        assert item.item_group_id is None
    finally:
        db.close()


def test_evidence_file_pinned_item_group_id(claim_id: str) -> None:
    db = SessionLocal()
    try:
        g = ItemGroup(claim_id=claim_id, name="A", name_normalized="a")
        db.add(g)
        db.commit()
        ef = EvidenceFile(
            claim_id=claim_id,
            filename="x.jpg",
            stored_path="x.jpg",
            pinned_item_group_id=g.id,
        )
        db.add(ef)
        db.commit()
        db.refresh(ef)
        assert ef.pinned_item_group_id == g.id
    finally:
        db.close()
