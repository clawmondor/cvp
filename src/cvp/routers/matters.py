import uuid
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from cvp.config import settings
from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_active_user, require_matter_role
from cvp.models import Category, Item, ItemGroup, Matter, VisionJob, VisionJobImage
from cvp.models_auth import User as UserORM
from cvp.models_vision import VisionModel
from cvp.services.audit import get_client_ip, should_debounce_view, write_audit_log

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["qplus"] = quote_plus
report_templates = Jinja2Templates(directory=BASE_DIR / "templates/report")

router = APIRouter()

LOSS_TYPES = ["total_loss", "partial_loss", "smoke", "water", "theft", "other"]
LOSS_EVENTS = ["Palisades Fire", "Eaton Fire", "Other"]


@router.get("/matters/new", response_class=HTMLResponse)
def new_matter_form(
    request: Request, user: CurrentUser = Depends(require_active_user)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="matter_new.html",
        context={
            "loss_types": LOSS_TYPES,
            "loss_events": LOSS_EVENTS,
            "user": user,
        },
    )


@router.post("/matters")
def create_matter(
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_active_user),
    firm_name: str = Form(default=""),
    attorney_name: str = Form(default=""),
    attorney_email: str = Form(default=""),
    policyholder_name: str = Form(default=""),
    loss_location: str = Form(default=""),
    loss_type: str = Form(default="total_loss"),
    loss_event: str = Form(default=""),
    loss_date: str = Form(default=""),
    carrier: str = Form(default=""),
    policy_number: str = Form(default=""),
    claim_number: str = Form(default=""),
    coverage_c_limit_dollars: str = Form(default="0"),
    firm_file_number: str = Form(default=""),
    target_delivery_date: str = Form(default=""),
) -> RedirectResponse:
    db = SessionLocal()
    try:
        matter = Matter(
            id=str(uuid.uuid4()),
            firm_name=firm_name,
            attorney_name=attorney_name,
            attorney_email=attorney_email,
            policyholder_name=policyholder_name,
            loss_location=loss_location,
            loss_type=loss_type,
            loss_event=loss_event,
            loss_date=date.fromisoformat(loss_date) if loss_date else None,
            carrier=carrier,
            policy_number=policy_number,
            claim_number=claim_number,
            coverage_c_limit=int(float(coverage_c_limit_dollars or 0) * 100),
            firm_file_number=firm_file_number,
            target_delivery_date=(
                date.fromisoformat(target_delivery_date) if target_delivery_date else None
            ),
        )
        matter.owner_group_id = user.group_id
        matter.created_by_id = user.id
        db.add(matter)
        db.commit()
        db.refresh(matter)
        matter_id = matter.id
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="matter.create",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=f"/matters/{matter_id}", status_code=303)


@router.get("/matters/{matter_id}", response_class=HTMLResponse)
def matter_detail(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("viewer")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        matter = (
            db.query(Matter)
            .options(
                selectinload(Matter.items).selectinload(Item.crops),
                selectinload(Matter.evidence_files),
                selectinload(Matter.rooms),
            )
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        items = sorted(matter.items, key=lambda i: i.line_number)
        confirmed = [i for i in items if i.confirmed and not i.excluded]
        total_rcv_cents = sum(i.rcv_total_cents for i in confirmed)
        total_acv_cents = sum(i.acv_total_cents for i in confirmed)
        unconfirmed_count = sum(1 for i in items if not i.confirmed)
        missing_price_count = sum(1 for i in confirmed if i.rcv_unit_cents == 0)
        evidence_files = sorted(matter.evidence_files, key=lambda f: f.created_at, reverse=True)
        rooms = sorted(matter.rooms, key=lambda r: r.sort_order)
        item_groups_rows = (
            db.query(ItemGroup, func.count(Item.id))
            .outerjoin(Item, Item.item_group_id == ItemGroup.id)
            .filter(ItemGroup.matter_id == matter_id)
            .group_by(ItemGroup.id)
            .order_by(ItemGroup.created_at)
            .all()
        )
        item_groups = [(g, c) for g, c in item_groups_rows]
        item_groups_flat = [g for g, _ in item_groups_rows]
        categories = db.query(Category).order_by(Category.id).all()
        vision_models = (
            db.query(VisionModel)
            .filter_by(is_enabled=True)
            .order_by(VisionModel.recommended.desc(), VisionModel.display_name.asc())
            .all()
        )
        db_user = db.query(UserORM).filter_by(id=user.id).first()
        last_slug = db_user.last_vision_model_slug if db_user else None
        default_vision_slug = None
        if last_slug and any(vm.slug == last_slug for vm in vision_models):
            default_vision_slug = last_slug
        if default_vision_slug is None:
            default_vision_slug = next((vm.slug for vm in vision_models if vm.is_default), None)
        debounce = should_debounce_view(db, user.id, "matter.view", matter_id)

        # Scan error badges — latest error per unscanned image
        scan_errors: dict[str, str] = {}
        error_rows = (
            db.query(VisionJobImage.evidence_file_id, VisionJobImage.error_message)
            .join(VisionJob, VisionJobImage.job_id == VisionJob.id)
            .filter(
                VisionJob.matter_id == matter_id,
                VisionJobImage.status == "error",
            )
            .order_by(VisionJobImage.created_at.asc())
            .all()
        )
        for row in error_rows:
            if row.error_message:
                scan_errors[row.evidence_file_id] = row.error_message

        # Banner for latest completed job with errors
        latest_scan_job: dict | None = None
        latest_job = (
            db.query(VisionJob)
            .filter(
                VisionJob.matter_id == matter_id,
                VisionJob.status.in_(["done", "error"]),
            )
            .order_by(VisionJob.created_at.desc())
            .first()
        )
        if latest_job:
            job_images = db.query(VisionJobImage).filter_by(job_id=latest_job.id).all()
            error_count = sum(1 for i in job_images if i.status == "error")
            if error_count > 0:
                latest_scan_job = {
                    "job_id": latest_job.id,
                    "total": len(job_images),
                    "success_count": sum(1 for i in job_images if i.status == "done"),
                    "error_count": error_count,
                }
    finally:
        db.close()

    if not debounce:
        background_tasks.add_task(
            write_audit_log,
            user_id=user.id,
            action="matter.view",
            resource_type="matter",
            resource_id=matter_id,
            matter_id=matter_id,
            ip_address=get_client_ip(request),
        )

    return templates.TemplateResponse(
        request=request,
        name="matter_detail.html",
        context={
            "matter": matter,
            "items": items,
            "evidence_files": evidence_files,
            "rooms": rooms,
            "item_groups": item_groups,
            "item_groups_flat": item_groups_flat,
            "categories": categories,
            "total_rcv_cents": total_rcv_cents,
            "total_acv_cents": total_acv_cents,
            "unconfirmed_count": unconfirmed_count,
            "missing_price_count": missing_price_count,
            "loss_types": LOSS_TYPES,
            "loss_events": LOSS_EVENTS,
            "user": user,
            "vision_models": vision_models,
            "default_vision_slug": default_vision_slug,
            "scan_errors": scan_errors,
            "latest_scan_job": latest_scan_job,
        },
    )


@router.post("/matters/{matter_id}/update")
def update_matter(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
    firm_name: str = Form(default=""),
    attorney_name: str = Form(default=""),
    attorney_email: str = Form(default=""),
    policyholder_name: str = Form(default=""),
    loss_location: str = Form(default=""),
    loss_type: str = Form(default="total_loss"),
    loss_event: str = Form(default=""),
    loss_date: str = Form(default=""),
    carrier: str = Form(default=""),
    policy_number: str = Form(default=""),
    claim_number: str = Form(default=""),
    coverage_c_limit_dollars: str = Form(default="0"),
    firm_file_number: str = Form(default=""),
    target_delivery_date: str = Form(default=""),
    internal_notes: str = Form(default=""),
) -> RedirectResponse:
    db = SessionLocal()
    try:
        matter = db.get(Matter, matter_id)
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        matter.firm_name = firm_name
        matter.attorney_name = attorney_name
        matter.attorney_email = attorney_email
        matter.policyholder_name = policyholder_name
        matter.loss_location = loss_location
        matter.loss_type = loss_type
        matter.loss_event = loss_event
        matter.loss_date = date.fromisoformat(loss_date) if loss_date else None
        matter.carrier = carrier
        matter.policy_number = policy_number
        matter.claim_number = claim_number
        matter.coverage_c_limit = int(float(coverage_c_limit_dollars or 0) * 100)
        matter.firm_file_number = firm_file_number
        matter.target_delivery_date = (
            date.fromisoformat(target_delivery_date) if target_delivery_date else None
        )
        matter.internal_notes = internal_notes
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="matter.update",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=f"/matters/{matter_id}#overview", status_code=303)


@router.post("/api/matters/{matter_id}/status")
def update_matter_status(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
    status: str = Form(...),
) -> RedirectResponse:
    valid = {"draft", "in_review", "delivered", "archived"}
    if status not in valid:
        return HTMLResponse("Invalid status", status_code=400)
    db = SessionLocal()
    try:
        matter = db.get(Matter, matter_id)
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)
        matter.status = status
        if status == "delivered":
            matter.delivered_date = date.today()
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="matter.update",
        resource_type="matter",
        resource_id=matter_id,
        matter_id=matter_id,
        detail={"status": status},
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=f"/matters/{matter_id}#overview", status_code=303)


@router.get("/matters/{matter_id}/preview", response_class=HTMLResponse)
def matter_preview(
    request: Request, matter_id: str, user: CurrentUser = Depends(require_matter_role("viewer"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        matter = (
            db.query(Matter)
            .options(
                selectinload(Matter.items),
                selectinload(Matter.evidence_files),
                selectinload(Matter.rooms),
            )
            .filter(Matter.id == matter_id)
            .first()
        )
        if matter is None:
            return HTMLResponse("Matter not found", status_code=404)

        confirmed_items = sorted(
            [i for i in matter.items if i.confirmed and not i.excluded],
            key=lambda i: i.line_number,
        )
        total_rcv_cents = sum(i.rcv_total_cents for i in confirmed_items)
        total_acv_cents = sum(i.acv_total_cents for i in confirmed_items)

        # Room lookup map
        room_map = {r.id: r.name for r in matter.rooms}

        # Category lookup
        all_categories = db.query(Category).order_by(Category.id).all()
        cat_map = {c.id: c.name for c in all_categories}
        cat_obj_map = {c.id: c for c in all_categories}

        # Categories used and item counts
        cat_counts: Counter = Counter(i.category_id for i in confirmed_items)
        categories_used = sorted(
            [(cat_obj_map[cid], count) for cid, count in cat_counts.items() if cid in cat_obj_map],
            key=lambda x: x[0].id,
        )

        # Summary by room
        room_rcv: dict = defaultdict(int)
        room_acv: dict = defaultdict(int)
        room_count: Counter = Counter()
        for item in confirmed_items:
            key = item.room_id or "__unassigned__"
            room_rcv[key] += item.rcv_total_cents
            room_acv[key] += item.acv_total_cents
            room_count[key] += 1

        by_room = []
        # Named rooms first (in sort_order), then unassigned
        for room in sorted(matter.rooms, key=lambda r: r.sort_order):
            if room.id in room_count:
                by_room.append(
                    dict(
                        room_name=room.name,
                        count=room_count[room.id],
                        rcv=room_rcv[room.id],
                        acv=room_acv[room.id],
                    )
                )
        if "__unassigned__" in room_count:
            by_room.append(
                dict(
                    room_name="Unassigned",
                    count=room_count["__unassigned__"],
                    rcv=room_rcv["__unassigned__"],
                    acv=room_acv["__unassigned__"],
                )
            )
    finally:
        db.close()

    return report_templates.TemplateResponse(
        request=request,
        name="preview.html",
        context={
            "matter": matter,
            "confirmed_items": confirmed_items,
            "total_items": len(confirmed_items),
            "total_rcv_cents": total_rcv_cents,
            "total_acv_cents": total_acv_cents,
            "evidence_files": matter.evidence_files,
            "room_map": room_map,
            "cat_map": cat_map,
            "categories_used": categories_used,
            "by_room": by_room,
            "report_date": datetime.now().strftime("%B %-d, %Y"),
            "company_name": settings.company_name,
            "company_address": settings.company_address,
            "company_email": settings.company_email,
            "company_phone": settings.company_phone,
            "user": user,
        },
    )
