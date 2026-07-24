"""The Claim model exposes a required nickname with a case-insensitive
per-group unique index."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from claimos.models import Base, Claim


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_nickname_column_exists_and_not_null(session):
    cols = {c["name"]: c for c in inspect(session.bind).get_columns("claims")}
    assert "nickname" in cols
    assert cols["nickname"]["nullable"] is False


def test_unique_index_is_case_insensitive_per_group(session):
    session.add(Claim(id="c1", owner_group_id="g1", nickname="Smith File"))
    session.commit()
    # Same group, different case -> collides at the DB level.
    session.add(Claim(id="c2", owner_group_id="g1", nickname="smith file"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_same_nickname_allowed_in_different_group(session):
    session.add(Claim(id="c1", owner_group_id="g1", nickname="Smith File"))
    session.add(Claim(id="c2", owner_group_id="g2", nickname="Smith File"))
    session.commit()  # must not raise
    assert session.query(Claim).count() == 2
