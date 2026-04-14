import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cvp.models import Base, Category
from cvp.seed import CATEGORIES, seed_categories


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_seed_creates_42_categories(db: Session) -> None:
    inserted = seed_categories(db)
    assert inserted == 42
    assert db.query(Category).count() == 42


def test_seed_is_idempotent(db: Session) -> None:
    seed_categories(db)
    second_run = seed_categories(db)
    assert second_run == 0  # nothing new inserted
    assert db.query(Category).count() == 42


def test_all_category_ids_present(db: Session) -> None:
    seed_categories(db)
    ids = {c.id for c in db.query(Category).all()}
    assert ids == set(range(1, 43))


def test_non_depreciable_categories_have_null_useful_life(db: Session) -> None:
    seed_categories(db)
    # IDs 7, 36, 37, 38 are non-depreciable per the depreciation schedule
    for cat_id in [7, 36, 37, 38]:
        cat = db.get(Category, cat_id)
        assert cat is not None
        assert cat.useful_life_years is None, f"Category {cat_id} should have null useful_life_years"
        assert cat.acv_floor_pct == 1.00, f"Category {cat_id} should have acv_floor_pct=1.0"
