"""System-admin page to create, list, and revoke external agent API keys."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models_agent import AgentKey
from cvp.models_auth import User
from cvp.services.agent_keys import generate_key

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/system/agent-keys")

_BREADCRUMBS = [
    {"label": "System Admin", "url": "/admin/system/"},
    {"label": "Agent Keys", "url": "/admin/system/agent-keys"},
]


def _list(db: Session) -> list[AgentKey]:
    return db.query(AgentKey).order_by(AgentKey.created_at.desc()).all()


def _creator_emails(db: Session, keys: list[AgentKey]) -> dict[str, str]:
    creator_ids = {k.created_by_id for k in keys if k.created_by_id}
    if not creator_ids:
        return {}
    users = db.query(User).filter(User.id.in_(creator_ids)).all()
    return {u.id: u.email for u in users}


@router.get("", response_class=HTMLResponse)
def index(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    keys = _list(db)
    return templates.TemplateResponse(
        request,
        "admin/system/agent_keys.html",
        {
            "user": user,
            "keys": keys,
            "creator_emails": _creator_emails(db, keys),
            "new_key": None,
            "panel_title": "System Admin",
            "breadcrumbs": _BREADCRUMBS,
        },
    )


@router.post("", response_class=HTMLResponse)
def create(
    request: Request,
    name: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    full_key, prefix, key_hash = generate_key()
    key = AgentKey(
        name=name.strip() or "Unnamed",
        key_prefix=prefix,
        key_hash=key_hash,
        created_by_id=user.id,
    )
    db.add(key)
    db.commit()
    keys = _list(db)
    return templates.TemplateResponse(
        request,
        "admin/system/agent_keys.html",
        {
            "user": user,
            "keys": keys,
            "creator_emails": _creator_emails(db, keys),
            "new_key": full_key,  # shown once, never persisted
            "panel_title": "System Admin",
            "breadcrumbs": _BREADCRUMBS,
        },
    )


@router.post("/{key_id}/revoke")
def revoke(
    key_id: str,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    key = db.get(AgentKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(url="/admin/system/agent-keys", status_code=303)
