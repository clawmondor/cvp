"""The needs_review column defaults to False and is independent of confirmed."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cvp.models_vision  # noqa: F401
from cvp.models import Base, Category, Item, Matter

MATTER_ID = "m-nr"


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
    s.add(Category(id=1, name="C", useful_life_years=5, acv_floor_pct=0.2))
    s.commit()
    yield s
    s.close()


def test_needs_review_defaults_false(db):
    it = Item(matter_id=MATTER_ID, category_id=1, description="x", confirmed=True)
    db.add(it)
    db.commit()
    db.refresh(it)
    assert it.needs_review is False


def test_needs_review_independent_of_confirmed(db):
    it = Item(
        matter_id=MATTER_ID,
        category_id=1,
        description="x",
        confirmed=True,
        needs_review=True,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    assert it.confirmed is True
    assert it.needs_review is True
