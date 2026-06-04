"""User-facing feedback router (floating widget + author thread access)."""

from datetime import datetime, timezone  # noqa: F401
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException  # noqa: F401
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: F401
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session  # noqa: F401

from cvp.db import get_db  # noqa: F401
from cvp.dependencies import (
    CurrentUser,  # noqa: F401
    _check_feedback_access,  # noqa: F401
    require_active_user,  # noqa: F401
)
from cvp.models_auth import User  # noqa: F401
from cvp.models_feedback import ALLOWED_STATUSES, Feedback, FeedbackComment  # noqa: F401
from cvp.text_validation import assert_plain_text  # noqa: F401

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
