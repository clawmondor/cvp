"""Room CRUD endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import update

from claimos.db import SessionLocal
from claimos.dependencies import CurrentUser, require_claim_role
from claimos.models import Item, Room
from claimos.services.audit import get_client_ip, write_audit_log
from claimos.templating import templates

router = APIRouter()


def _room_li(room: Room) -> str:
    return templates.get_template("_room_li.html").render(room=room)


@router.post("/api/claims/{claim_id}/rooms", response_class=HTMLResponse)
def create_room(
    request: Request,
    claim_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_claim_role("contributor", "rooms")),
) -> HTMLResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Room name required")
    db = SessionLocal()
    try:
        max_order = db.query(Room).filter(Room.claim_id == claim_id).count()
        room = Room(claim_id=claim_id, name=name, sort_order=max_order)
        db.add(room)
        db.commit()
        db.refresh(room)
        room_id = room.id
        html = _room_li(room)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="room.create",
        resource_type="room",
        resource_id=room_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.patch("/api/rooms/{room_id}", response_class=HTMLResponse)
def rename_room(
    request: Request,
    room_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_claim_role("contributor", "rooms")),
) -> HTMLResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Room name required")
    db = SessionLocal()
    try:
        room = db.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        room.name = name
        db.commit()
        db.refresh(room)
        claim_id = room.claim_id
        html = _room_li(room)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="room.update",
        resource_type="room",
        resource_id=room_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.delete("/api/rooms/{room_id}", response_class=HTMLResponse)
def delete_room(
    request: Request,
    room_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_claim_role("manager", "rooms")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        room = db.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        claim_id = room.claim_id
        # Unassign items from this room
        db.execute(update(Item).where(Item.room_id == room_id).values(room_id=None))
        db.delete(room)
        db.commit()
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="room.delete",
        resource_type="room",
        resource_id=room_id,
        claim_id=claim_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
