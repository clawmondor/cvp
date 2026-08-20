"""JSON API for external AI agents (X-API-Key auth)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from cvp.agent_auth import AgentPrincipal, require_agent_key
from cvp.db import get_db
from cvp.models import Category, Item
from cvp.services import runtime_config
from cvp.services.recommendation_feed import items_needing_recommendations

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _serialize_item(db: Session, item: Item) -> dict:
    cat = db.get(Category, item.category_id)
    return {
        "item_id": item.id,
        "description": item.description,
        "brand": item.brand,
        "model": item.model,
        "category": cat.name if cat else None,
        "quantity": item.quantity,
        "vision_confidence": item.vision_confidence,
        "matter_id": item.matter_id,
        "crops": [
            {"item_crop_id": c.id, "image_url": f"/api/agent/crops/{c.crop_path}"}
            for c in item.crops
            if c.crop_path
        ],
    }


@router.get("/items")
def list_items(
    principal: AgentPrincipal = Depends(require_agent_key),
    db: Session = Depends(get_db),
    min_confidence: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    threshold = min_confidence or runtime_config.get_str(db, "ai_recommendation_min_confidence")
    items = items_needing_recommendations(db, threshold, limit=limit, offset=offset)
    # Eager-load crops to avoid N+1 in serialization.
    ids = [i.id for i in items]
    if ids:
        items = (
            db.query(Item)
            .options(selectinload(Item.crops))
            .filter(Item.id.in_(ids))
            .order_by(Item.created_at, Item.id)
            .all()
        )
    return {"items": [_serialize_item(db, i) for i in items]}


@router.get("/items/{item_id}")
def get_item(
    item_id: str,
    principal: AgentPrincipal = Depends(require_agent_key),
    db: Session = Depends(get_db),
) -> dict:
    item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _serialize_item(db, item)
