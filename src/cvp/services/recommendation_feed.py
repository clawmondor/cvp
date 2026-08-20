"""Query helpers for the agent discovery feed."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cvp.models import Item
from cvp.models_agent import AiRecommendation

CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
MAX_PENDING_PER_ITEM = 5


def _at_or_above(min_confidence: str) -> list[str]:
    threshold = CONFIDENCE_RANK.get(min_confidence, CONFIDENCE_RANK["high"])
    return [name for name, rank in CONFIDENCE_RANK.items() if rank >= threshold]


def pending_count(db: Session, item_id: str) -> int:
    return (
        db.query(func.count(AiRecommendation.id))
        .filter(
            AiRecommendation.item_id == item_id,
            AiRecommendation.status == "pending",
        )
        .scalar()
        or 0
    )


def items_needing_recommendations(
    db: Session, min_confidence: str, limit: int, offset: int
) -> list[Item]:
    """Items above the confidence threshold, unpriced, with < 5 pending recs."""
    allowed = _at_or_above(min_confidence)

    pending_sub = (
        select(
            AiRecommendation.item_id.label("item_id"),
            func.count(AiRecommendation.id).label("n"),
        )
        .where(AiRecommendation.status == "pending")
        .group_by(AiRecommendation.item_id)
        .subquery()
    )

    q = (
        db.query(Item)
        .outerjoin(pending_sub, pending_sub.c.item_id == Item.id)
        .filter(Item.vision_confidence.in_(allowed))
        .filter(Item.source_url == "")
        .filter(func.coalesce(pending_sub.c.n, 0) < MAX_PENDING_PER_ITEM)
        .order_by(Item.created_at, Item.id)
        .limit(limit)
        .offset(offset)
    )
    return q.all()
