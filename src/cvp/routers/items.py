"""Item CRUD endpoints with ACV auto-computation."""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.depreciation import compute_acv
from cvp.models import Category, Item, ItemGroup, Room, SerpSearch
from cvp.services.item_groups import find_or_create
from cvp.services.audit import get_client_ip, write_audit_log
from cvp.services.serp_display import extract_results

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"
templates.env.filters["qplus"] = quote_plus
templates.env.filters["pretty_json"] = lambda v: json.dumps(json.loads(v), indent=2) if v else ""

router = APIRouter()

CONDITIONS = ["excellent", "above_average", "average", "below_average"]


def _get_context(matter_id: str, db):
    categories = db.query(Category).order_by(Category.id).all()
    rooms = db.query(Room).filter(Room.matter_id == matter_id).order_by(Room.sort_order).all()
    item_groups = (
        db.query(ItemGroup)
        .filter(ItemGroup.matter_id == matter_id)
        .order_by(ItemGroup.created_at)
        .all()
    )
    return categories, rooms, item_groups


def _compute_and_set_totals(item: Item, cat: Category) -> None:
    item.rcv_total_cents = item.rcv_unit_cents * item.quantity
    item.acv_total_cents = compute_acv(
        rcv_unit_cents=item.rcv_unit_cents,
        quantity=item.quantity,
        age_years=item.age_years,
        useful_life_years=cat.useful_life_years,
        acv_floor_pct=cat.acv_floor_pct,
        condition=item.condition,
        acv_override_cents=item.acv_override_cents,
    )


def _item_row_html(item: Item, categories: list, rooms: list, item_groups: list) -> str:
    return templates.get_template("_item_row.html").render(
        item=item, categories=categories, rooms=rooms, item_groups=item_groups
    )


def _item_row_edit_html(
    item: Item,
    categories: list,
    rooms: list,
    item_groups: list,
    latest_by_crop: dict | None = None,
    display_by_crop: dict | None = None,
) -> str:
    return templates.get_template("_item_row_edit.html").render(
        item=item,
        categories=categories,
        rooms=rooms,
        item_groups=item_groups,
        conditions=CONDITIONS,
        public_base_url=settings.public_base_url,
        latest_by_crop=latest_by_crop or {},
        display_by_crop=display_by_crop or {},
    )


def _items_tbody_html(matter_id: str, db) -> str:
    items = (
        db.query(Item)
        .filter(Item.matter_id == matter_id)
        .options(selectinload(Item.crops))
        .order_by(Item.line_number)
        .all()
    )
    categories, rooms, item_groups = _get_context(matter_id, db)
    return templates.get_template("_items_tbody.html").render(
        items=items,
        categories=categories,
        rooms=rooms,
        item_groups=item_groups,
        conditions=CONDITIONS,
    )


def _parse_cents(dollars_str: str) -> int:
    try:
        return round(float(dollars_str or 0) * 100)
    except ValueError:
        return 0


@router.post("/api/matters/{matter_id}/items", response_class=HTMLResponse)
def create_item(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("contributor")),
    description: str = Form(""),
    category_id: int = Form(...),
    room_id: str = Form(""),
    quantity: int = Form(1),
    age_years: float = Form(0.0),
    condition: str = Form("average"),
    rcv_unit_dollars: str = Form("0"),
    brand: str = Form(""),
    model_num: str = Form(""),
    notes: str = Form(""),
    item_group_id: str = Form(""),
    new_item_group_name: str = Form(""),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        cat = db.get(Category, category_id)
        if cat is None:
            raise HTTPException(status_code=400, detail="Invalid category")

        max_line = (
            db.query(func.max(Item.line_number)).filter(Item.matter_id == matter_id).scalar() or 0
        )
        item = Item(
            matter_id=matter_id,
            category_id=category_id,
            room_id=room_id or None,
            line_number=max_line + 1,
            description=description.strip(),
            brand=brand.strip() or None,
            model=model_num.strip() or None,
            quantity=max(1, quantity),
            age_years=max(0.0, age_years),
            condition=condition,
            rcv_unit_cents=_parse_cents(rcv_unit_dollars),
            notes=notes.strip(),
            confirmed=True,  # manually entered items start confirmed; Vision drafts use False
        )
        if new_item_group_name.strip():
            ig = find_or_create(db, matter_id, new_item_group_name)
            item.item_group_id = ig.id
        elif item_group_id:
            ig = db.get(ItemGroup, item_group_id)
            if ig is None or ig.matter_id != matter_id:
                raise HTTPException(status_code=400, detail="Group not in matter")
            item.item_group_id = ig.id
        _compute_and_set_totals(item, cat)
        db.add(item)
        db.commit()
        item_id = item.id
        html = _items_tbody_html(matter_id, db)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.create",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.get("/api/items/{item_id}/edit", response_class=HTMLResponse)
def item_edit_form(
    item_id: str, user: CurrentUser = Depends(require_matter_role("editor"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        categories, rooms, item_groups = _get_context(item.matter_id, db)

        latest_by_crop: dict = {}
        display_by_crop: dict = {}
        for crop in item.crops:
            latest = (
                db.query(SerpSearch)
                .filter(SerpSearch.item_crop_id == crop.id)
                .order_by(SerpSearch.ran_at.desc())
                .first()
            )
            latest_by_crop[crop.id] = latest
            if latest and latest.response_json:
                display_by_crop[crop.id] = extract_results(
                    latest.service, json.loads(latest.response_json)
                )
            else:
                display_by_crop[crop.id] = []

        html = _item_row_edit_html(
            item, categories, rooms, item_groups, latest_by_crop, display_by_crop
        )
    finally:
        db.close()
    return HTMLResponse(html)


@router.get("/api/items/{item_id}/view", response_class=HTMLResponse)
def item_view_row(
    item_id: str, user: CurrentUser = Depends(require_matter_role("viewer"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        categories, rooms, item_groups = _get_context(item.matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    return HTMLResponse(html)


@router.patch("/api/items/{item_id}", response_class=HTMLResponse)
def update_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("editor")),
    description: str = Form(""),
    category_id: int = Form(...),
    room_id: str = Form(""),
    quantity: int = Form(1),
    age_years: float = Form(0.0),
    condition: str = Form("average"),
    rcv_unit_dollars: str = Form("0"),
    brand: str = Form(""),
    model_num: str = Form(""),
    notes: str = Form(""),
    source_retailer: str = Form(""),
    source_url: str = Form(""),
    match_type: str = Form("exact"),
    acv_override_dollars: str = Form(""),
    acv_override_reason: str = Form(""),
    confirmed: bool = Form(False),
    item_group_id: str = Form(""),
    new_item_group_name: str = Form(""),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        cat = db.get(Category, category_id)
        if cat is None:
            raise HTTPException(status_code=400, detail="Invalid category")

        item.confirmed = confirmed
        item.description = description.strip()
        item.category_id = category_id
        item.room_id = room_id or None
        item.quantity = max(1, quantity)
        item.age_years = max(0.0, age_years)
        item.condition = condition
        item.rcv_unit_cents = _parse_cents(rcv_unit_dollars)
        item.brand = brand.strip() or None
        item.model = model_num.strip() or None
        item.notes = notes.strip()
        item.source_retailer = source_retailer.strip()
        item.source_url = source_url.strip()
        item.match_type = match_type

        if acv_override_dollars.strip() and acv_override_reason.strip():
            item.acv_override_cents = _parse_cents(acv_override_dollars)
            item.acv_override_reason = acv_override_reason.strip()
        else:
            item.acv_override_cents = None
            item.acv_override_reason = None

        if new_item_group_name.strip():
            ig = find_or_create(db, item.matter_id, new_item_group_name)
            item.item_group_id = ig.id
        elif item_group_id:
            ig = db.get(ItemGroup, item_group_id)
            if ig is None or ig.matter_id != item.matter_id:
                raise HTTPException(status_code=400, detail="Group not in matter")
            item.item_group_id = ig.id
        else:
            item.item_group_id = None

        _compute_and_set_totals(item, cat)
        db.commit()
        db.refresh(item)
        matter_id = item.matter_id
        categories, rooms, item_groups = _get_context(matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/toggle-confirm", response_class=HTMLResponse)
def toggle_confirm(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.confirmed = not item.confirmed
        if item.confirmed:
            item.confirmed_by_id = user.id
            item.confirmed_at = datetime.now(tz=timezone.utc)
        else:
            item.confirmed_by_id = None
            item.confirmed_at = None
        db.commit()
        db.refresh(item)
        matter_id = item.matter_id
        categories, rooms, item_groups = _get_context(matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/toggle-exclude", response_class=HTMLResponse)
def toggle_exclude(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.query(Item).options(selectinload(Item.crops)).filter(Item.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404)
        item.excluded = not item.excluded
        db.commit()
        db.refresh(item)
        matter_id = item.matter_id
        categories, rooms, item_groups = _get_context(matter_id, db)
        html = _item_row_html(item, categories, rooms, item_groups)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.update",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.delete("/api/items/{item_id}", response_class=HTMLResponse)
def delete_item(
    request: Request,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        item = db.get(Item, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        matter_id = item.matter_id
        db.delete(item)
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item.delete",
        resource_type="item",
        resource_id=item_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
