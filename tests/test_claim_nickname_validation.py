"""Unit tests for validate_nickname: required, length cap, case-insensitive
per-group uniqueness, and self-exclusion on edit."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from claimos.models import Base, Claim
from claimos.routers.claims import validate_nickname


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Claim(id="c1", owner_group_id="g1", nickname="Smith File"))
    s.commit()
    yield s
    s.close()


def test_strips_and_returns_clean_value(db):
    cleaned, err = validate_nickname(db, "  Jones File  ", "g1")
    assert cleaned == "Jones File"
    assert err is None


def test_empty_is_rejected(db):
    cleaned, err = validate_nickname(db, "   ", "g1")
    assert err == "Nickname is required."


def test_too_long_is_rejected(db):
    cleaned, err = validate_nickname(db, "x" * 101, "g1")
    assert err == "Nickname must be 100 characters or fewer."


def test_exactly_100_chars_accepted(db):
    cleaned, err = validate_nickname(db, "x" * 100, "g1")
    assert err is None
    assert cleaned == "x" * 100


def test_case_insensitive_duplicate_in_same_group_rejected(db):
    cleaned, err = validate_nickname(db, "smith file", "g1")
    assert err == "That nickname is already used in your group."


def test_same_nickname_other_group_allowed(db):
    cleaned, err = validate_nickname(db, "Smith File", "g2")
    assert err is None


def test_self_excluded_on_edit(db):
    # Re-saving c1 with its own (case-varied) nickname must pass.
    cleaned, err = validate_nickname(db, "SMITH FILE", "g1", exclude_claim_id="c1")
    assert err is None
