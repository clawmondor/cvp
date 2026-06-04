"""User-facing feedback router (floating widget + author thread access)."""

from datetime import datetime, timezone  # noqa: F401
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: F401
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import (
    CurrentUser,
    _check_feedback_access,
    require_active_user,
)
from cvp.models_auth import User
from cvp.models_feedback import ALLOWED_STATUSES, Feedback, FeedbackComment
from cvp.text_validation import assert_plain_text

router = APIRouter()

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

FEEDBACK_BODY_MAX = 5000
COMMENT_BODY_MAX = 2000
PAGE_URL_MAX = 2048


def _clean_page_url(raw: str) -> str:
    """Return a safe relative path, or '/' if the input is unsafe or malformed.

    Accepts only paths starting with a single '/'. Protocol-relative URLs
    ('//evil.com'), absolute URLs ('http://...'), bare schemes ('javascript:'),
    over-length input, and anything else fall back to '/'.
    """
    if not raw:
        return "/"
    if len(raw) > PAGE_URL_MAX:
        return "/"
    if not raw.startswith("/"):
        return "/"
    if raw.startswith("//"):
        return "/"
    return raw


@router.post("/feedback", response_class=HTMLResponse)
def submit_feedback(
    body: str = Form(...),
    page_url: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    cleaned_body = body.strip()
    if not cleaned_body:
        raise HTTPException(status_code=400, detail="Feedback body is required.")
    if len(cleaned_body) > FEEDBACK_BODY_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Feedback body must be {FEEDBACK_BODY_MAX} characters or fewer.",
        )
    assert_plain_text(cleaned_body, field_name="Feedback")

    if user.group_id is None:
        raise HTTPException(status_code=400, detail="Submitting user has no group.")

    fb = Feedback(
        author_user_id=user.id,
        author_group_id=user.group_id,
        page_url=_clean_page_url(page_url),
        body=cleaned_body,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)

    return _render_widget_panel(db, user)


@router.get("/feedback/widget", response_class=HTMLResponse)
def get_widget_panel(
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_widget_panel(db, user)


def _render_widget_panel(db: Session, user: CurrentUser) -> HTMLResponse:
    """Render the popover panel HTML: new-feedback form + author's threads."""
    threads = (
        db.query(Feedback)
        .filter(
            Feedback.author_user_id == user.id,
            Feedback.deleted_at.is_(None),
        )
        .order_by(Feedback.created_at.desc())
        .all()
    )
    html = templates.get_template("_feedback_widget_panel.html").render(
        threads=threads,
        feedback_body_max=FEEDBACK_BODY_MAX,
    )
    return HTMLResponse(html)


def _load_feedback_or_404(feedback_id: str, db: Session) -> Feedback:
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return fb


def _render_thread(
    db: Session, user: CurrentUser, fb: Feedback, *, is_admin_view: bool
) -> HTMLResponse:
    comments = (
        db.query(FeedbackComment)
        .filter(FeedbackComment.feedback_id == fb.id)
        .order_by(FeedbackComment.created_at.asc())
        .all()
    )
    user_ids = {fb.author_user_id} | {c.author_user_id for c in comments}
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    html = templates.get_template("_feedback_thread.html").render(
        feedback=fb,
        comments=comments,
        users=users_by_id,
        current_user=user,
        is_admin_view=is_admin_view,
        comment_body_max=COMMENT_BODY_MAX,
        allowed_statuses=ALLOWED_STATUSES,
    )
    return HTMLResponse(html)


@router.get("/feedback/{feedback_id}", response_class=HTMLResponse)
def get_thread(
    feedback_id: str,
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    if not _check_feedback_access(user, fb):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return _render_thread(db, user, fb, is_admin_view=False)


@router.post("/feedback/{feedback_id}/comments", response_class=HTMLResponse)
def post_comment(
    feedback_id: str,
    body: str = Form(...),
    user: CurrentUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    fb = _load_feedback_or_404(feedback_id, db)
    if not _check_feedback_access(user, fb):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    cleaned = body.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Comment body is required.")
    if len(cleaned) > COMMENT_BODY_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Comment must be {COMMENT_BODY_MAX} characters or fewer.",
        )
    assert_plain_text(cleaned, field_name="Comment")

    c = FeedbackComment(
        feedback_id=fb.id,
        author_user_id=user.id,
        body=cleaned,
    )
    db.add(c)
    db.commit()
    db.refresh(fb)
    return _render_thread(db, user, fb, is_admin_view=user.system_role == "system_admin")
