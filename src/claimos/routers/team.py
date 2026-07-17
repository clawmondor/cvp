"""Firm-facing Team management surface for external admins (RBAC v2)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_active_user
from claimos.models_auth import Group, User
from claimos.templating import templates

router = APIRouter(prefix="/team")


async def require_external_admin(
    user: CurrentUser = Depends(require_active_user),
) -> CurrentUser:
    """Allow external_admin and system_admin; everyone else 403."""
    if user.system_role not in ("external_admin", "system_admin"):
        raise HTTPException(status_code=403, detail="Team access requires firm admin")
    return user


@router.get("/users", response_class=HTMLResponse)
def team_users(
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, user.group_id) if user.group_id else None
    members = db.query(User).filter(User.group_id == user.group_id).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="team/users.html",
        context={"user": user, "group": group, "members": members},
    )
