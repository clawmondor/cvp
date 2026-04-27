"""Room CRUD endpoints."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import update

from cvp.db import SessionLocal
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models import Item, Room
from cvp.services.audit import get_client_ip, write_audit_log

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


def _room_li(room: Room) -> str:
    return templates.get_template("_room_li.html").render(room=room)


@router.post("/api/matters/{matter_id}/rooms", response_class=HTMLResponse)
def create_room(
    request: Request,
    matter_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Room name required")
    db = SessionLocal()
    try:
        max_order = db.query(Room).filter(Room.matter_id == matter_id).count()
        room = Room(matter_id=matter_id, name=name, sort_order=max_order)
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
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.patch("/api/rooms/{room_id}", response_class=HTMLResponse)
def rename_room(
    request: Request,
    room_id: str,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
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
        matter_id = room.matter_id
        html = _room_li(room)
    finally:
        db.close()
    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="room.update",
        resource_type="room",
        resource_id=room_id,
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse(html)


@router.delete("/api/rooms/{room_id}", response_class=HTMLResponse)
def delete_room(
    request: Request,
    room_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_matter_role("manager")),
) -> HTMLResponse:
    db = SessionLocal()
    try:
        room = db.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        matter_id = room.matter_id
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
        matter_id=matter_id,
        ip_address=get_client_ip(request),
    )
    return HTMLResponse("", status_code=200)
