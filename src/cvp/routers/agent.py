"""JSON API for external AI agents (X-API-Key auth)."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, selectinload

from cvp.agent_auth import AgentPrincipal, require_agent_key
from cvp.config import settings
from cvp.db import get_db
from cvp.models import Category, Item
from cvp.models_agent import AiRecommendation
from cvp.services import runtime_config
from cvp.services.audit import write_audit_log
from cvp.services.recommendation_feed import (
    MAX_PENDING_PER_ITEM,
    items_needing_recommendations,
    pending_count,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


class RecommendationIn(BaseModel):
    proposed_retail_unit_cents: int = Field(ge=0)
    proposed_shipping_cents: int = Field(default=0, ge=0)
    source_url: str
    source_retailer: str
    match_type: str = "exact"
    product_title: str = ""
    rationale: str = ""
    item_crop_id: str | None = None
    #: Set when the submission came from a CVP-launched agent run. Optional so the
    #: external-agent path (which has no run) is unaffected; it is what makes the
    #: A/B join in the design spec (5.3) return rows.
    agent_run_id: str | None = None

    @field_validator("source_url", "source_retailer")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


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
    matter_id: str | None = Query(None),
    item_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    threshold = min_confidence or runtime_config.get_str(db, "ai_recommendation_min_confidence")
    items = items_needing_recommendations(
        db,
        threshold,
        limit=limit,
        offset=offset,
        matter_id=matter_id,
        item_id=item_id,
    )
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


@router.get("/crops/{crop_path:path}")
def serve_crop(
    crop_path: str,
    principal: AgentPrincipal = Depends(require_agent_key),
    db: Session = Depends(get_db),
) -> FileResponse:
    crop_dir = Path(settings.crop_dir).resolve()
    requested = (crop_dir / crop_path).resolve()
    if not str(requested).startswith(str(crop_dir)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not requested.exists():
        raise HTTPException(status_code=404, detail="Crop not found")
    return FileResponse(str(requested))


@router.post("/items/{item_id}/recommendations", status_code=201)
def submit_recommendation(
    item_id: str,
    body: RecommendationIn,
    background_tasks: BackgroundTasks,
    principal: AgentPrincipal = Depends(require_agent_key),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if pending_count(db, item_id) >= MAX_PENDING_PER_ITEM:
        raise HTTPException(
            status_code=409, detail="Item already has the maximum pending recommendations"
        )

    rec = AiRecommendation(
        item_id=item_id,
        item_crop_id=body.item_crop_id,
        agent_key_id=principal.agent_key_id,
        agent_run_id=body.agent_run_id,
        proposed_retail_unit_cents=body.proposed_retail_unit_cents,
        proposed_shipping_cents=body.proposed_shipping_cents,
        source_url=body.source_url,
        source_retailer=body.source_retailer,
        match_type=body.match_type,
        product_title=body.product_title,
        rationale=body.rationale,
        status="pending",
        source_captured_at=datetime.now(tz=timezone.utc),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    background_tasks.add_task(
        write_audit_log,
        user_id=None,
        action="agent.recommendation.create",
        resource_type="ai_recommendation",
        resource_id=rec.id,
        matter_id=item.matter_id,
        detail={"agent_key_id": principal.agent_key_id, "agent_name": principal.name},
    )
    return {"id": rec.id, "status": rec.status, "item_id": rec.item_id}
