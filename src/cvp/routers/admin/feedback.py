"""Admin feedback router: list, filter/sort, detail, change status, submit on behalf."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models_auth import Group, User
from cvp.models_feedback import ALLOWED_STATUSES, Feedback
from cvp.routers.feedback import (
    FEEDBACK_BODY_MAX,
    _clean_page_url,
    _load_feedback_or_404,
    _render_thread,
    _resolve_author_group_id,
    count_admin_unread,
)
from cvp.text_validation import assert_plain_text

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


@router.get("/new", response_class=HTMLResponse)
def admin_new_form(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email.asc()).all()
    html = templates.get_template("admin/system/feedback_new.html").render(
        request=request,
        user=user,
        panel_title="System",
        breadcrumbs=[
            {"label": "Feedback", "url": "/admin/system/feedback"},
            {"label": "New", "url": "/admin/system/feedback/new"},
        ],
        users=users,
        feedback_body_max=FEEDBACK_BODY_MAX,
        unread_count=count_admin_unread(db),
    )
    return HTMLResponse(html)


@router.post("/new-as")
def admin_submit_as(
    body: str = Form(...),
    page_url: str = Form(...),
    author_user_id: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    author = db.get(User, author_user_id)
    if author is None or not author.is_active:
        raise HTTPException(status_code=400, detail="Author must be an active user.")
    author_group_id = _resolve_author_group_id(db, author)

    cleaned = body.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Feedback body is required.")
    if len(cleaned) > FEEDBACK_BODY_MAX:
        raise HTTPException(status_code=400, detail="Feedback body too long.")
    assert_plain_text(cleaned, field_name="Feedback")

    fb = Feedback(
        author_user_id=author.id,
        author_group_id=author_group_id,
        page_url=_clean_page_url(page_url),
        body=cleaned,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return RedirectResponse(url=f"/admin/system/feedback/{fb.id}", status_code=303)


@router.get("/{feedback_id}", response_class=HTMLResponse)
def admin_thread(
    feedback_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    fb.last_admin_read_at = datetime.now(tz=timezone.utc)
    db.commit()
    inner_html = _render_thread(db, user, fb, is_admin_view=True).body.decode("utf-8")
    html = templates.get_template("admin/system/feedback_detail.html").render(
        request=request,
        user=user,
        panel_title="System",
        breadcrumbs=[
            {"label": "Feedback", "url": "/admin/system/feedback"},
            {"label": fb.id[:8], "url": f"/admin/system/feedback/{fb.id}"},
        ],
        feedback=fb,
        thread_html=inner_html,
        unread_count=count_admin_unread(db),
    )
    return HTMLResponse(html)


@router.post("/{feedback_id}/status")
def change_status(
    feedback_id: str,
    status: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    fb = _load_feedback_or_404(feedback_id, db)
    now = datetime.now(tz=timezone.utc)
    fb.status = status
    fb.status_changed_at = now
    fb.status_changed_by_user_id = user.id
    fb.last_admin_read_at = now
    db.commit()
    return RedirectResponse(url=f"/admin/system/feedback/{fb.id}", status_code=303)
