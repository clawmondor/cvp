"""Specialist Accept/Dismiss actions for AI recommendations."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.depreciation import compute_acv
from cvp.models import Category, Item, ItemGroup, Room
from cvp.models_agent import AiRecommendation

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"

router = APIRouter()

# Single module-level dependency instance so tests can override it by identity.
EDITOR = require_matter_role("editor")


def _load_rec(db: Session, item_id: str, rec_id: str) -> AiRecommendation:
    rec = db.get(AiRecommendation, rec_id)
    if rec is None or rec.item_id != item_id:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return rec


@router.post("/api/items/{item_id}/recommendations/{rec_id}/accept", response_class=HTMLResponse)
def accept(
    request: Request,
    item_id: str,
    rec_id: str,
    user: CurrentUser = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    rec = _load_rec(db, item_id, rec_id)

    # Write-through (mirrors serp_apply field math).
    item.source_url = rec.source_url
    item.source_retailer = rec.source_retailer
    item.source_captured_at = datetime.now(tz=timezone.utc)
    item.match_type = rec.match_type
    item.retail_unit_cents = rec.proposed_retail_unit_cents
    item.shipping_cents = rec.proposed_shipping_cents
    item.rcv_total_cents = item.retail_unit_cents * item.quantity + item.shipping_cents

    cat = db.get(Category, item.category_id)
    item.acv_total_cents = compute_acv(
        retail_unit_cents=item.retail_unit_cents,
        quantity=item.quantity,
        age_years=item.age_years,
        useful_life_years=cat.useful_life_years if cat else None,
        acv_floor_pct=cat.acv_floor_pct if cat else 0.2,
        condition=item.condition,
        acv_override_cents=item.acv_override_cents,
        shipping_cents=item.shipping_cents,
    )

    now = datetime.now(tz=timezone.utc)
    rec.status = "accepted"
    rec.resolved_at = now
    rec.resolved_by_id = user.id
    for other in item.ai_recommendations:
        if other.id != rec.id and other.status == "pending":
            other.status = "superseded"
            other.resolved_at = now
            other.resolved_by_id = user.id

    db.commit()
    db.refresh(item)

    categories = db.query(Category).order_by(Category.id).all()
    rooms = db.query(Room).filter(Room.matter_id == item.matter_id).order_by(Room.sort_order).all()
    item_groups = (
        db.query(ItemGroup)
        .filter(ItemGroup.matter_id == item.matter_id)
        .order_by(ItemGroup.created_at)
        .all()
    )
    html = templates.get_template("_item_row.html").render(
        item=item, categories=categories, rooms=rooms, item_groups=item_groups
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/recommendations/{rec_id}/dismiss", response_class=HTMLResponse)
def dismiss(
    request: Request,
    item_id: str,
    rec_id: str,
    user: CurrentUser = Depends(EDITOR),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rec = _load_rec(db, item_id, rec_id)
    rec.status = "rejected"
    rec.resolved_at = datetime.now(tz=timezone.utc)
    rec.resolved_by_id = user.id
    db.commit()

    item = (
        db.query(Item)
        .options(selectinload(Item.ai_recommendations))
        .filter(Item.id == item_id)
        .first()
    )
    pending = [r for r in item.ai_recommendations if r.status == "pending"]
    html = templates.get_template("_ai_recommendations.html").render(
        item=item, recommendations=pending
    )
    return HTMLResponse(html)
