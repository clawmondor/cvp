"""Comment CRUD endpoints with visibility scoping."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, _check_matter_access, require_active_user, require_matter_role
from cvp.models import Item
from cvp.models_auth import User
from cvp.models_comments import Comment

router = APIRouter()

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

EDIT_WINDOW_MINUTES = 15


def _get_comment_and_check_access(
    comment_id: str,
    minimum_role: str,
    user: CurrentUser,
    db: Session,
) -> Comment:
    """Load a comment and verify the caller has at least minimum_role on its matter."""
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    item = db.get(Item, comment.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if not _check_matter_access(db, user, item.matter_id, minimum_role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return comment


@router.get("/api/items/{item_id}/comments", response_class=HTMLResponse)
def list_comments(
    item_id: str,
    user: CurrentUser = Depends(require_matter_role("viewer")),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """List comments for an item, filtered by visibility."""
    query = db.query(Comment).filter(Comment.item_id == item_id)

    # External users only see shared comments
    if user.group_kind == "external":
        query = query.filter(Comment.visibility == "shared")

    comments = query.order_by(Comment.created_at.asc()).all()

    user_ids = {c.user_id for c in comments}
    users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
        if user_ids
        else {}
    )

    html = templates.get_template("_comments.html").render(
        comments=comments,
        users=users,
        item_id=item_id,
        current_user=user,
        edit_window_minutes=EDIT_WINDOW_MINUTES,
        now=datetime.now(tz=timezone.utc),
    )
    return HTMLResponse(html)


@router.post("/api/items/{item_id}/comments", response_class=HTMLResponse)
def create_comment(
    item_id: str,
    body: str = Form(...),
    visibility: str = Form("shared"),
    user: CurrentUser = Depends(require_matter_role("viewer")),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Create a comment on an item."""
    if visibility not in ("internal", "shared"):
        raise HTTPException(status_code=400, detail="Invalid visibility")

    # External users can only create shared comments
    if user.group_kind == "external" and visibility == "internal":
        visibility = "shared"

    comment = Comment(
        item_id=item_id,
        user_id=user.id,
        body=body.strip(),
        visibility=visibility,
    )
    db.add(comment)
    db.commit()

    return list_comments(item_id, user=user, db=db)


@router.patch("/api/comments/{comment_id}", response_class=JSONResponse)
async def edit_comment(
    comment_id: str,
    body: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Edit own comment within the edit window."""
    comment = await _get_comment_and_check_access(comment_id, "viewer", user, db)

    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Can only edit your own comments")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=EDIT_WINDOW_MINUTES)
    if comment.created_at.replace(tzinfo=timezone.utc) < cutoff:
        raise HTTPException(status_code=403, detail="Edit window has expired")

    comment.body = body.strip()
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/api/comments/{comment_id}", response_class=JSONResponse)
async def delete_comment(
    comment_id: str,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Delete own comment (within window) or any comment (if system_admin)."""
    comment = await _get_comment_and_check_access(comment_id, "viewer", user, db)

    if user.system_role == "system_admin":
        db.delete(comment)
        db.commit()
        return JSONResponse({"ok": True})

    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=EDIT_WINDOW_MINUTES)
    if comment.created_at.replace(tzinfo=timezone.utc) < cutoff:
        raise HTTPException(status_code=403, detail="Delete window has expired")

    db.delete(comment)
    db.commit()
    return JSONResponse({"ok": True})
