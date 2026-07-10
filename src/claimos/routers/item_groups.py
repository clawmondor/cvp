"""ItemGroup CRUD endpoints (the Task 6 evidence-pin endpoint will be appended here later)."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, update

from claimos.db import SessionLocal
from claimos.dependencies import CurrentUser, require_claim_role
from claimos.models import EvidenceFile, Item, ItemGroup
from claimos.services.audit import get_client_ip, write_audit_log
from claimos.services.item_groups import find_or_create
from claimos.templating import templates

router = APIRouter()


def _render_li(group: ItemGroup, claim_id: str, item_count: int) -> str:
    return templates.get_template("_item_group_li.html").render(
        group=group, claim_id=claim_id, item_count=item_count
    )


def _item_count(db, group_id: str) -> int:
    return db.query(func.count(Item.id)).filter(Item.item_group_id == group_id).scalar() or 0


@router.post("/api/claims/{claim_id}/item-groups", response_class=HTMLResponse)
def create_item_group(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_claim_role("manager")),
) -> HTMLResponse:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Group name required")
    db = SessionLocal()
    try:
        group = find_or_create(db, claim_id, name)
        db.commit()
        db.refresh(group)
        gid = group.id
        html = _render_li(group, claim_id, _item_count(db, gid))
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item_group.create",
        resource_type="item_group",
        resource_id=gid,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.patch("/api/claims/{claim_id}/item-groups/{group_id}", response_class=HTMLResponse)
def rename_item_group(
    request: Request,
    claim_id: str,
    group_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_claim_role("manager")),
) -> HTMLResponse:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Group name required")
    db = SessionLocal()
    try:
        group = db.get(ItemGroup, group_id)
        if group is None or group.claim_id != claim_id:
            raise HTTPException(status_code=404, detail="Group not found")
        group.name = name.strip()
        group.name_normalized = name.strip().lower()
        db.commit()
        db.refresh(group)
        html = _render_li(group, claim_id, _item_count(db, group_id))
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item_group.update",
        resource_type="item_group",
        resource_id=group_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.delete("/api/claims/{claim_id}/item-groups/{group_id}", response_class=HTMLResponse)
def delete_item_group(
    request: Request,
    claim_id: str,
    group_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        group = db.get(ItemGroup, group_id)
        if group is None or group.claim_id != claim_id:
            raise HTTPException(status_code=404, detail="Group not found")
        # SQLite's ON DELETE SET NULL only fires when PRAGMA foreign_keys=ON.
        # Be explicit so behaviour is identical in SQLite and Postgres.
        db.execute(update(Item).where(Item.item_group_id == group_id).values(item_group_id=None))
        db.execute(
            update(EvidenceFile)
            .where(EvidenceFile.pinned_item_group_id == group_id)
            .values(pinned_item_group_id=None)
        )
        db.delete(group)
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="item_group.delete",
        resource_type="item_group",
        resource_id=group_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)


@router.patch(
    "/api/claims/{claim_id}/evidence/{file_id}/item-group",
    response_class=HTMLResponse,
)
def pin_evidence_to_group(
    request: Request,
    claim_id: str,
    file_id: str,
    background_tasks: BackgroundTasks,
    item_group_id: str = Form(""),
    new_item_group_name: str = Form(""),
    user: CurrentUser = Depends(require_claim_role("editor")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        ef = db.get(EvidenceFile, file_id)
        if ef is None or ef.claim_id != claim_id:
            raise HTTPException(status_code=404, detail="Evidence file not found")

        if new_item_group_name.strip():
            group = find_or_create(db, claim_id, new_item_group_name)
            ef.pinned_item_group_id = group.id
        elif item_group_id:
            group = db.get(ItemGroup, item_group_id)
            if group is None or group.claim_id != claim_id:
                raise HTTPException(status_code=400, detail="Group not in claim")
            ef.pinned_item_group_id = group.id
        else:
            ef.pinned_item_group_id = None

        db.commit()
        db.refresh(ef)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="evidence.pin_item_group",
        resource_type="evidence_file",
        resource_id=file_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
