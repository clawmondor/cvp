"""Room CRUD endpoints."""

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import update

from cvp.db import SessionLocal
from cvp.models import Item, Room

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter()


def _room_li(room: Room) -> str:
    return templates.get_template("_room_li.html").render(room=room)


@router.post("/api/matters/{matter_id}/rooms", response_class=HTMLResponse)
def create_room(matter_id: str, name: str = Form(...)) -> HTMLResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Room name required")
    db = SessionLocal()
    try:
        max_order = (
            db.query(Room)
            .filter(Room.matter_id == matter_id)
            .count()
        )
        room = Room(matter_id=matter_id, name=name, sort_order=max_order)
        db.add(room)
        db.commit()
        db.refresh(room)
        html = _room_li(room)
    finally:
        db.close()
    return HTMLResponse(html)


@router.patch("/api/rooms/{room_id}", response_class=HTMLResponse)
def rename_room(room_id: str, name: str = Form(...)) -> HTMLResponse:
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
        html = _room_li(room)
    finally:
        db.close()
    return HTMLResponse(html)


@router.delete("/api/rooms/{room_id}", response_class=HTMLResponse)
def delete_room(room_id: str) -> HTMLResponse:
    db = SessionLocal()
    try:
        room = db.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        # Unassign items from this room
        db.execute(update(Item).where(Item.room_id == room_id).values(room_id=None))
        db.delete(room)
        db.commit()
    finally:
        db.close()
    return HTMLResponse("", status_code=200)
