"""Admin feedback router: list, filter/sort, change status, soft-delete, submit-as."""

from datetime import datetime, timezone  # noqa: F401
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request  # noqa: F401
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: F401
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models_auth import Group, User
from cvp.models_feedback import ALLOWED_STATUSES, Feedback  # noqa: F401
from cvp.routers.feedback import (
    FEEDBACK_BODY_MAX,  # noqa: F401
    _clean_page_url,  # noqa: F401
    _load_feedback_or_404,  # noqa: F401
    _render_thread,  # noqa: F401
    count_admin_unread,
)
from cvp.text_validation import assert_plain_text  # noqa: F401

router = APIRouter(prefix="/admin/system/feedback")

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ALLOWED_SORTS = {"created_at", "status", "group", "author"}


@router.get("", response_class=HTMLResponse)
def list_feedback(
    request: Request,
    status: list[str] = Query(default_factory=list),
    group_id: str | None = Query(default=None),
    author_q: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc"),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    q = db.query(Feedback)
    if not include_deleted:
        q = q.filter(Feedback.deleted_at.is_(None))
    valid_statuses = [s for s in status if s in ALLOWED_STATUSES]
    if valid_statuses:
        q = q.filter(Feedback.status.in_(valid_statuses))
    if group_id:
        q = q.filter(Feedback.author_group_id == group_id)
    if author_q:
        like = f"%{author_q.lower()}%"
        author_ids = [
            u.id
            for u in db.query(User)
            .filter((User.email.ilike(like)) | (User.display_name.ilike(like)))
            .all()
        ]
        if not author_ids:
            q = q.filter(Feedback.author_user_id == "__none__")
        else:
            q = q.filter(Feedback.author_user_id.in_(author_ids))

    sort_key = sort if sort in ALLOWED_SORTS else "created_at"
    column = {
        "created_at": Feedback.created_at,
        "status": Feedback.status,
        "group": Feedback.author_group_id,
        "author": Feedback.author_user_id,
    }[sort_key]
    q = q.order_by(column.desc() if order != "asc" else column.asc())

    rows = q.all()
    user_ids = {r.author_user_id for r in rows}
    users_by_id = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    )
    group_ids = {r.author_group_id for r in rows}
    groups_by_id = (
        {g.id: g for g in db.query(Group).filter(Group.id.in_(group_ids)).all()}
        if group_ids
        else {}
    )
    all_groups = db.query(Group).order_by(Group.name.asc()).all()

    html = templates.get_template("admin/system/feedback.html").render(
        request=request,
        user=user,
        panel_title="System",
        breadcrumbs=[{"label": "Feedback", "url": "/admin/system/feedback"}],
        rows=rows,
        users=users_by_id,
        groups=groups_by_id,
        all_groups=all_groups,
        selected_statuses=valid_statuses,
        selected_group_id=group_id,
        author_q=author_q or "",
        include_deleted=include_deleted,
        sort=sort_key,
        order=order,
        allowed_statuses=ALLOWED_STATUSES,
        unread_count=count_admin_unread(db),
    )
    return HTMLResponse(html)
