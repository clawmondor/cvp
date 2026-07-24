"""Tests for the cursor-based pagination helper."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from claimos.models import Base, Claim, EvidenceFile
from claimos.services.pagination import paginate_by_cursor


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Claim(id="m", policyholder_name="P", loss_type="total_loss", nickname="Test Claim"))
    s.commit()
    # 7 evidence rows; we'll paginate by id (stable, ascending insertion order)
    for i in range(7):
        s.add(
            EvidenceFile(
                claim_id="m",
                filename=f"f{i}.jpg",
                stored_path=f"m/f{i}.jpg",
                mime_type="image/jpeg",
                size_bytes=100,
                kind="image",
            )
        )
    s.commit()
    yield s
    s.close()


def test_first_page_returns_limit_rows_and_next_cursor(db):
    rows, next_cursor = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(claim_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=None,
        limit=3,
        order="asc",
    )
    assert len(rows) == 3
    assert next_cursor == rows[-1].id


def test_middle_page_skips_consumed_rows(db):
    rows, _ = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(claim_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=None,
        limit=3,
        order="asc",
    )
    last_id = rows[-1].id

    page2, next_cursor2 = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(claim_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=last_id,
        limit=3,
        order="asc",
    )
    assert len(page2) == 3
    assert all(r.id != last_id for r in page2)
    assert next_cursor2 == page2[-1].id


def test_last_page_returns_no_cursor(db):
    # Page 1 of 3, page 2 of 3, page 3 of 1
    cursor = None
    pages = []
    for _ in range(3):
        rows, cursor = paginate_by_cursor(
            db.query(EvidenceFile).filter_by(claim_id="m"),
            cursor_col=EvidenceFile.id,
            cursor_value=cursor,
            limit=3,
            order="asc",
        )
        pages.append((rows, cursor))
    assert [len(p[0]) for p in pages] == [3, 3, 1]
    assert pages[-1][1] is None  # last page → no next cursor


def test_descending_order_works(db):
    rows, _ = paginate_by_cursor(
        db.query(EvidenceFile).filter_by(claim_id="m"),
        cursor_col=EvidenceFile.id,
        cursor_value=None,
        limit=10,
        order="desc",
    )
    ids = [r.id for r in rows]
    assert ids == sorted(ids, reverse=True)
