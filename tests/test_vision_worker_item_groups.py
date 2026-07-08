"""Tests for the vision worker's item-group resolution helper.

Tests exercise the pure helper directly. The full scan loop is integration-
tested via the existing vision_worker tests; this file focuses on the
group-resolution rule.
"""

import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_access  # noqa: F401
import claimos.models_auth  # noqa: F401
from claimos.models import Base, Category, EvidenceFile, ItemGroup, Matter
from claimos.services.vision import _resolve_effective_item_group_id


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded(db_session):
    db_session.add(Category(id=1, name="Misc", useful_life_years=10, acv_floor_pct=0.2))
    db_session.add(Matter(id="m1", firm_name="T"))
    db_session.commit()
    return db_session


def _make_ef(seeded, *, pinned_group_name: str | None = None) -> EvidenceFile:
    """Insert an EvidenceFile; optionally seed and pin a group."""
    ef = EvidenceFile(matter_id="m1", filename="x.jpg", stored_path="x.jpg", kind="image")
    seeded.add(ef)
    if pinned_group_name is not None:
        g = ItemGroup(
            matter_id="m1",
            name=pinned_group_name,
            name_normalized=pinned_group_name.strip().lower(),
        )
        seeded.add(g)
        seeded.commit()
        seeded.refresh(g)
        ef.pinned_item_group_id = g.id
    seeded.commit()
    seeded.refresh(ef)
    return ef


def test_no_pin_no_placard_yields_none(seeded):
    ef = _make_ef(seeded)
    assert _resolve_effective_item_group_id(seeded, ef, placard_text="") is None
    assert _resolve_effective_item_group_id(seeded, ef, placard_text="   ") is None


def test_placard_creates_group_when_no_pin(seeded):
    ef = _make_ef(seeded)
    gid = _resolve_effective_item_group_id(seeded, ef, placard_text="12")
    seeded.commit()
    assert gid is not None
    groups = seeded.query(ItemGroup).filter(ItemGroup.matter_id == "m1").all()
    assert len(groups) == 1
    assert groups[0].id == gid
    assert groups[0].name == "12"


def test_placard_reuses_existing_group_case_insensitive(seeded):
    seeded.add(ItemGroup(matter_id="m1", name="Box A", name_normalized="box a"))
    seeded.commit()
    ef = _make_ef(seeded)
    gid = _resolve_effective_item_group_id(seeded, ef, placard_text="box a")
    seeded.commit()
    groups = seeded.query(ItemGroup).filter(ItemGroup.matter_id == "m1").all()
    assert len(groups) == 1
    assert seeded.get(ItemGroup, gid).name == "Box A"


def test_pinned_wins_over_placard(seeded):
    ef = _make_ef(seeded, pinned_group_name="A")
    gid = _resolve_effective_item_group_id(seeded, ef, placard_text="99")
    assert gid == ef.pinned_item_group_id
    # No new group was created for "99".
    groups = seeded.query(ItemGroup).filter(ItemGroup.matter_id == "m1").all()
    assert len(groups) == 1
    assert groups[0].name == "A"


def test_pin_with_no_placard_returns_pin(seeded):
    ef = _make_ef(seeded, pinned_group_name="A")
    gid = _resolve_effective_item_group_id(seeded, ef, placard_text="")
    assert gid == ef.pinned_item_group_id


def _capture_vision_logs(emit_fn):
    """Install a direct INFO handler on claimos.services.vision and return cleanup.

    Necessary because alembic's fileConfig (run from migrations/env.py during
    other tests in the suite) defaults disable_existing_loggers=True, which sets
    logger.disabled=True on previously-created loggers — and caplog can't
    override that flag.
    """
    vision_logger = logging.getLogger("claimos.services.vision")

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            emit_fn(record)

    handler = _Capture(logging.INFO)
    old_level = vision_logger.level
    old_disabled = vision_logger.disabled
    vision_logger.disabled = False
    vision_logger.setLevel(logging.INFO)
    vision_logger.addHandler(handler)

    def cleanup() -> None:
        vision_logger.removeHandler(handler)
        vision_logger.setLevel(old_level)
        vision_logger.disabled = old_disabled

    return cleanup


def test_pin_with_conflicting_placard_logs_at_info(seeded):
    ef = _make_ef(seeded, pinned_group_name="A")
    records: list[logging.LogRecord] = []
    cleanup = _capture_vision_logs(records.append)
    try:
        _resolve_effective_item_group_id(seeded, ef, placard_text="99")
    finally:
        cleanup()
    assert any("placard mismatch" in r.getMessage() and "99" in r.getMessage() for r in records)


def test_pin_with_matching_placard_no_log(seeded):
    """Placard text matches the pinned group's normalized name — no INFO log."""
    ef = _make_ef(seeded, pinned_group_name="Box A")
    records: list[logging.LogRecord] = []
    cleanup = _capture_vision_logs(records.append)
    try:
        _resolve_effective_item_group_id(seeded, ef, placard_text="box a")
    finally:
        cleanup()
    assert not any("placard mismatch" in r.getMessage() for r in records)
