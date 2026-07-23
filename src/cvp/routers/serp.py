"""SERP search endpoints: crop file serving, panel, google_lens search, and apply result."""

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
from cvp.models import Category, Item, ItemCrop, ItemGroup, Room, SerpSearch
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.serp import build_crop_url, call_serp
from cvp.services.serp_display import extract_results

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

        latest_by_crop: dict[str, SerpSearch | None] = {}
        display_by_crop: dict[str, list[dict]] = {}

        for crop in item.crops:
            latest = (
                db.query(SerpSearch)
                .filter(SerpSearch.item_crop_id == crop.id)
                .order_by(SerpSearch.ran_at.desc())
                .first()
            )
            latest_by_crop[crop.id] = latest
            if latest and latest.response_json:
                response_dict = json.loads(latest.response_json)
                display_by_crop[crop.id] = extract_results(latest.service, response_dict)
            else:
                display_by_crop[crop.id] = []

        html = templates.get_template("_serp_panel.html").render(
            item=item,
            public_base_url=settings.public_base_url,
            latest_by_crop=latest_by_crop,
            display_by_crop=display_by_crop,
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
    """Run a Google Lens search for a specific item crop and persist the result."""
    db = SessionLocal()
    try:
        crop = db.get(ItemCrop, crop_id)
        if crop is None:
            raise HTTPException(status_code=404, detail="Crop not found")
        if crop.item_id != item_id:
            raise HTTPException(status_code=403, detail="Crop does not belong to this item")

        image_url_val = image_url.strip() or None
        request_url, params_dict, response_dict, status_code = call_serp(
            "google_lens", crop, image_url_val
        )

        search = SerpSearch(
            item_crop_id=crop.id,
            service="google_lens",
            image_url=image_url_val or build_crop_url(crop) or "",
            request_url=request_url,
            request_params=json.dumps(params_dict),
            response_json=json.dumps(response_dict),
            status_code=status_code,
        )
        db.add(search)
        db.commit()
        db.refresh(search)

        display_results = extract_results("google_lens", response_dict)

        item = db.get(Item, item_id)
        matter_id = item.matter_id if item else None

        html = templates.get_template("_serp_result.html").render(
            s=search,
            display_results=display_results,
            item_id=item_id,
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


@router.post("/api/items/{item_id}/serp-apply", response_class=HTMLResponse)
def serp_apply(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    source_url: str = Form(""),
    source_retailer: str = Form(""),
    rcv_unit_cents: str = Form(""),
) -> HTMLResponse:
    """Apply a SERP search result to an item, updating its pricing and source fields."""
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")

        item.source_url = source_url.strip()
        item.source_retailer = source_retailer.strip()
        item.source_captured_at = datetime.now(tz=timezone.utc)
        item.match_type = "exact"

        if rcv_unit_cents.strip():
            item.rcv_unit_cents = int(rcv_unit_cents.strip())

        item.rcv_total_cents = item.rcv_unit_cents * item.quantity

        cat = db.get(Category, item.category_id)
        item.acv_total_cents = compute_acv(
            retail_unit_cents=item.rcv_unit_cents,
            quantity=item.quantity,
            age_years=item.age_years,
            useful_life_years=cat.useful_life_years if cat else None,
            acv_floor_pct=cat.acv_floor_pct if cat else 0.2,
            condition=item.condition,
            acv_override_cents=item.acv_override_cents,
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
