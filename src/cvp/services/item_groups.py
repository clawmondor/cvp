"""Service helpers for the ItemGroup entity (per-matter on-site placards)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cvp.models import ItemGroup


def _normalize(name: str) -> str:
    return name.strip().lower()


def find_or_create(session: Session, matter_id: str, name: str) -> ItemGroup:
    """Return the ItemGroup matching ``name`` for ``matter_id``, creating it if absent.

    Names are matched case-insensitively after whitespace trimming. The unique
    index on ``(matter_id, name_normalized)`` is the source of truth for
    dedupe; this function catches an IntegrityError race and re-queries.
    """
    normalized = _normalize(name)
    if not normalized:
        raise ValueError("group name cannot be empty")
    existing = session.execute(
        select(ItemGroup).where(
            ItemGroup.matter_id == matter_id,
            ItemGroup.name_normalized == normalized,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    group = ItemGroup(
        matter_id=matter_id,
        name=name.strip(),
        name_normalized=normalized,
    )
    try:
        with session.begin_nested():
            session.add(group)
    except IntegrityError:
        # Concurrent insert won the race; SAVEPOINT was rolled back so the
        # caller's outer transaction is intact.
        return session.execute(
            select(ItemGroup).where(
                ItemGroup.matter_id == matter_id,
                ItemGroup.name_normalized == normalized,
            )
        ).scalar_one()
    return group
