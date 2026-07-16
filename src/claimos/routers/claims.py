import uuid
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from claimos.config import settings
from claimos.db import SessionLocal
from claimos.dependencies import (
    CurrentUser,
    _check_claim_access,
    require_active_user,
    require_claim_role,
)
from claimos.models import (
    Category,
    Claim,
    EvidenceFile,
    Item,
    ItemGroup,
    VisionJob,
    VisionJobImage,
)
from claimos.models_auth import User as UserORM
from claimos.models_vision import VisionModel
from claimos.routers.items import compute_items_totals
from claimos.services import runtime_config
from claimos.services.audit import get_client_ip, should_debounce_view, write_audit_log
from claimos.services.pagination import paginate_by_cursor
from claimos.templating import templates

BASE_DIR = Path(__file__).parent.parent
report_templates = Jinja2Templates(directory=BASE_DIR / "templates/report")

router = APIRouter()

LOSS_TYPES = ["total_loss", "partial_loss", "smoke", "water", "theft", "other"]
LOSS_EVENTS = ["Palisades Fire", "Eaton Fire", "Other"]


@router.get("/claims/new", response_class=HTMLResponse)
def new_claim_form(
    request: Request, user: CurrentUser = Depends(require_active_user)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="claim_new.html",
        context={
            "loss_types": LOSS_TYPES,
            "loss_events": LOSS_EVENTS,
            "user": user,
        },
    )


@router.post("/claims")
def create_claim(
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
        claim = Claim(
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
        claim.owner_group_id = user.group_id
        claim.created_by_id = user.id
        db.add(claim)
        db.commit()
        db.refresh(claim)
        claim_id = claim.id
    finally:
        db.close()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="claim.create",
        resource_type="claim",
        resource_id=claim_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=f"/claims/{claim_id}", status_code=303)


@router.get("/claims/{claim_id}", response_class=HTMLResponse)
def claim_detail(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("viewer")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        claim = (
            db.query(Claim).options(selectinload(Claim.rooms)).filter(Claim.id == claim_id).first()
        )
        if claim is None:
            return HTMLResponse("Claim not found", status_code=404)

        # First page of evidence (newest-first), with cursor for infinite scroll.
        evidence_files, evidence_next_cursor = paginate_by_cursor(
            db.query(EvidenceFile).filter(EvidenceFile.claim_id == claim_id),
            cursor_col=EvidenceFile.created_at,
            cursor_value=None,
            limit=24,
            order="desc",
        )
        evidence_next_cursor = evidence_next_cursor.isoformat() if evidence_next_cursor else None

        # Full-set items totals (aggregate query, not row-by-row).
        _totals = compute_items_totals(claim_id, db)
        total_rcv_cents = _totals["items_rcv_total_cents"]
        total_acv_cents = _totals["items_acv_total_cents"]
        unconfirmed_count = _totals["unconfirmed_count"]
        missing_price_count = _totals["missing_price_count"]
        items_total_count = _totals["items_total_count"]
        items_confirmed_count = _totals["items_confirmed_count"]

        # First page of items rows (line_number ASC), with cursor.
        items, items_next_cursor = paginate_by_cursor(
            db.query(Item).options(selectinload(Item.crops)).filter(Item.claim_id == claim_id),
            cursor_col=Item.line_number,
            cursor_value=None,
            limit=50,
            order="asc",
        )
        rooms = sorted(claim.rooms, key=lambda r: r.sort_order)
        item_groups_rows = (
            db.query(ItemGroup, func.count(Item.id))
            .outerjoin(Item, Item.item_group_id == ItemGroup.id)
            .filter(ItemGroup.claim_id == claim_id)
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
        debounce = should_debounce_view(db, user.id, "claim.view", claim_id)

        # Scan error badges — latest error per unscanned image
        scan_errors: dict[str, str] = {}
        error_rows = (
            db.query(VisionJobImage.evidence_file_id, VisionJobImage.error_message)
            .join(VisionJob, VisionJobImage.job_id == VisionJob.id)
            .filter(
                VisionJob.claim_id == claim_id,
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
                VisionJob.claim_id == claim_id,
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

        evidence_upload_concurrency = runtime_config.get_int(db, "evidence_upload_concurrency")
        evidence_upload_max_file_mb = runtime_config.get_int(db, "evidence_upload_max_file_mb")
        evidence_upload_max_batch_count = runtime_config.get_int(
            db, "evidence_upload_max_batch_count"
        )
        can_approve = _check_claim_access(db, user, claim_id, "approver", "items")
    finally:
        db.close()

    if not debounce:
        background_tasks.add_task(
            write_audit_log,
            user_id=user.id,
            action="claim.view",
            resource_type="claim",
            resource_id=claim_id,
            claim_id=claim_id,
            ip_address=get_client_ip(request),
        )

    return templates.TemplateResponse(
        request=request,
        name="claim_detail.html",
        context={
            "claim": claim,
            "items": items,
            "items_next_cursor": items_next_cursor,
            "items_total_count": items_total_count,
            "items_confirmed_count": items_confirmed_count,
            "items_rcv_total_cents": total_rcv_cents,
            "items_acv_total_cents": total_acv_cents,
            "evidence_files": evidence_files,
            "evidence_next_cursor": evidence_next_cursor,
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
            "evidence_upload_concurrency": evidence_upload_concurrency,
            "evidence_upload_max_file_mb": evidence_upload_max_file_mb,
            "evidence_upload_max_batch_count": evidence_upload_max_batch_count,
            "can_approve": can_approve,
        },
    )


@router.post("/claims/{claim_id}/update")
def update_claim(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager")),
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
        claim = db.get(Claim, claim_id)
        if claim is None:
            return HTMLResponse("Claim not found", status_code=404)
        claim.firm_name = firm_name
        claim.attorney_name = attorney_name
        claim.attorney_email = attorney_email
        claim.policyholder_name = policyholder_name
        claim.loss_location = loss_location
        claim.loss_type = loss_type
        claim.loss_event = loss_event
        claim.loss_date = date.fromisoformat(loss_date) if loss_date else None
        claim.carrier = carrier
        claim.policy_number = policy_number
        claim.claim_number = claim_number
        claim.coverage_c_limit = int(float(coverage_c_limit_dollars or 0) * 100)
        claim.firm_file_number = firm_file_number
        claim.target_delivery_date = (
            date.fromisoformat(target_delivery_date) if target_delivery_date else None
        )
        claim.internal_notes = internal_notes
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="claim.update",
        resource_type="claim",
        resource_id=claim_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=f"/claims/{claim_id}#overview", status_code=303)


@router.post("/api/claims/{claim_id}/status")
def update_claim_status(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager")),
    status: str = Form(...),
) -> RedirectResponse:
    valid = {"draft", "in_review", "delivered", "archived"}
    if status not in valid:
        return HTMLResponse("Invalid status", status_code=400)
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        if claim is None:
            return HTMLResponse("Claim not found", status_code=404)
        claim.status = status
        if status == "delivered":
            claim.delivered_date = date.today()
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="claim.update",
        resource_type="claim",
        resource_id=claim_id,
        claim_id=claim_id,
        detail={"status": status},
        ip_address=get_client_ip(request),
    )
    return RedirectResponse(url=f"/claims/{claim_id}#overview", status_code=303)


@router.get("/claims/{claim_id}/preview", response_class=HTMLResponse)
def claim_preview(
    request: Request, claim_id: str, user: CurrentUser = Depends(require_claim_role("viewer"))
) -> HTMLResponse:
    db = SessionLocal()
    try:
        claim = (
            db.query(Claim)
            .options(
                selectinload(Claim.items),
                selectinload(Claim.evidence_files),
                selectinload(Claim.rooms),
            )
            .filter(Claim.id == claim_id)
            .first()
        )
        if claim is None:
            return HTMLResponse("Claim not found", status_code=404)

        confirmed_items = sorted(
            [i for i in claim.items if i.confirmed and not i.excluded],
            key=lambda i: i.line_number,
        )
        total_rcv_cents = sum(i.rcv_total_cents for i in confirmed_items)
        total_acv_cents = sum(i.acv_total_cents for i in confirmed_items)

        # Room lookup map
        room_map = {r.id: r.name for r in claim.rooms}

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
        for room in sorted(claim.rooms, key=lambda r: r.sort_order):
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
            "claim": claim,
            "confirmed_items": confirmed_items,
            "total_items": len(confirmed_items),
            "total_rcv_cents": total_rcv_cents,
            "total_acv_cents": total_acv_cents,
            "evidence_files": claim.evidence_files,
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
