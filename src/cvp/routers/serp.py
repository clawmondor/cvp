"""SERP search endpoints: crop file serving, panel, google_lens/firecrawl search, apply result."""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, optional_user, require_matter_role
from cvp.depreciation import compute_acv
from cvp.models import MATCH_TYPES, Category, Item, ItemGroup, Room
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.firecrawl import build_query, call_firecrawl
from cvp.services.serp import build_crop_url, call_serp
from cvp.services.serp_runner import panel_context, run_and_render

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["pretty_json"] = lambda v: json.dumps(json.loads(v), indent=2) if v else ""
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"
templates.env.filters["qplus"] = quote_plus

router = APIRouter()


@router.get("/crops/{crop_path:path}")
def serve_crop(crop_path: str, user: CurrentUser | None = Depends(optional_user)) -> FileResponse:
    """Serve a crop image file from the crop directory with path-traversal guard."""
    crop_dir = Path(settings.crop_dir).resolve()
    requested = (crop_dir / crop_path).resolve()
    if not str(requested).startswith(str(crop_dir)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not requested.exists():
        raise HTTPException(status_code=404, detail="Crop not found")
    return FileResponse(str(requested))


@router.get("/api/items/{item_id}/serp-panel", response_class=HTMLResponse)
def serp_panel(
    item_id: str, user: CurrentUser = Depends(require_matter_role("editor"))
) -> HTMLResponse:
    """Render the SERP panel for an item showing all crops and their latest search results."""
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")

        html = templates.get_template("_serp_panel.html").render(
            item=item,
            public_base_url=settings.public_base_url,
            default_query=build_query(item),
            **panel_context(db, item),
        )
    finally:
        db.close()
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/crops/{crop_id}/serp/google_lens", response_class=HTMLResponse)
def run_google_lens(
    request: Request,
    item_id: str,
    crop_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    image_url: str = Form(""),
) -> HTMLResponse:
    """Run a Google Lens reverse-image search for one crop and persist the result."""
    pasted = image_url.strip() or None
    return run_and_render(
        SessionLocal,
        templates,
        request,
        background_tasks,
        user,
        item_id,
        crop_id,
        service="google_lens",
        caller=lambda crop, _item: call_serp("google_lens", crop, pasted),
        image_url_fn=lambda crop: pasted or build_crop_url(crop) or "",
    )


@router.post("/api/items/{item_id}/crops/{crop_id}/serp/firecrawl", response_class=HTMLResponse)
def run_firecrawl(
    request: Request,
    item_id: str,
    crop_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    query: str = Form(""),
) -> HTMLResponse:
    """Run a Firecrawl web product search for one item and persist the result.

    An empty query falls back to the item's own fields, so the endpoint is
    usable without the pre-filled input.
    """
    typed = query.strip()
    return run_and_render(
        SessionLocal,
        templates,
        request,
        background_tasks,
        user,
        item_id,
        crop_id,
        service="firecrawl",
        caller=lambda _crop, item: call_firecrawl(typed or (build_query(item) if item else "")),
    )


@router.post("/api/items/{item_id}/serp-apply", response_class=HTMLResponse)
def serp_apply(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    source_url: str = Form(""),
    source_retailer: str = Form(""),
    rcv_unit_cents: str = Form(""),
    match_type: str = Form("nearest_comparable"),
) -> HTMLResponse:
    """Apply a SERP search result to an item, updating its pricing and source fields."""
    if match_type not in MATCH_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid match_type: {match_type}")

    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")

        item.source_url = source_url.strip()
        item.source_retailer = source_retailer.strip()
        item.source_captured_at = datetime.now(tz=timezone.utc)
        item.match_type = match_type

        if rcv_unit_cents.strip():
            item.retail_unit_cents = int(rcv_unit_cents.strip())

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

        db.commit()
        db.refresh(item)

        matter_id = item.matter_id
        categories = db.query(Category).order_by(Category.id).all()
        rooms = db.query(Room).filter(Room.matter_id == matter_id).order_by(Room.sort_order).all()
        item_groups = (
            db.query(ItemGroup)
            .filter(ItemGroup.matter_id == matter_id)
            .order_by(ItemGroup.created_at)
            .all()
        )

        html = templates.get_template("_item_row.html").render(
            item=item, categories=categories, rooms=rooms, item_groups=item_groups
        )
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="serp.run",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)
