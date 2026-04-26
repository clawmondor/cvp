"""External Admin (Org) panel router."""

import datetime
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from cvp.auth import generate_invite_code, hash_token
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_active_user
from cvp.models import Matter
from cvp.models_access import MatterAccess
from cvp.models_auth import Group, User

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/org")

_CTX = {"panel_color": "emerald", "panel_title": "Organization Administration"}


def _ctx(user: CurrentUser, **kwargs) -> dict[str, object]:
    return {**_CTX, "user": user, **kwargs}


async def _require_org_admin_or_above(
    user: CurrentUser = Depends(require_active_user),
) -> CurrentUser:
    """Require system_admin, internal_admin, or external_admin."""
    if user.system_role not in ("system_admin", "internal_admin", "external_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def _resolve_group_id(user: CurrentUser, group_id: str | None, db: Session) -> str | None:
    """Resolve which external group to operate on.

    Returns the group_id to use, or None if a group selector should be shown.
    - external_admin: always their own group_id (ignore query param)
    - internal_admin/system_admin: use ?group_id if provided, else None (show selector)
    """
    if user.system_role == "external_admin":
        return user.group_id
    return group_id  # None triggers selector page


@router.get("/", response_class=HTMLResponse)
def org_dashboard(
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    if resolved is None:
        groups = db.query(Group).filter(Group.kind == "external").order_by(Group.name).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/org/group_selector.html",
            context=_ctx(user, groups=groups),
        )
    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    user_count = db.query(User).filter(User.group_id == resolved).count()
    matter_count = db.query(Matter).filter(Matter.owner_group_id == resolved).count()
    return templates.TemplateResponse(
        request=request,
        name="admin/org/dashboard.html",
        context=_ctx(
            user,
            group=group,
            user_count=user_count,
            matter_count=matter_count,
            breadcrumbs=[{"label": group.name, "url": f"/admin/org/?group_id={resolved}"}],
        ),
    )


@router.get("/users", response_class=HTMLResponse)
def org_users(
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    if resolved is None:
        raise HTTPException(status_code=400, detail="group_id required")
    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    users = db.query(User).filter(User.group_id == resolved).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/org/users.html",
        context=_ctx(
            user,
            group=group,
            users=users,
            breadcrumbs=[
                {"label": group.name, "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Users", "url": f"/admin/org/users?group_id={resolved}"},
            ],
        ),
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
def org_user_detail(
    user_id: str,
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Tenant isolation: external_admin can only see own group
    if resolved and target.group_id != resolved:
        raise HTTPException(status_code=404, detail="User not found")
    group = db.get(Group, target.group_id) if target.group_id else None
    return templates.TemplateResponse(
        request=request,
        name="admin/org/user_detail.html",
        context=_ctx(
            user,
            target=target,
            group=group,
            breadcrumbs=[
                {"label": group.name if group else "Org", "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Users", "url": f"/admin/org/users?group_id={resolved}"},
                {"label": target.email, "url": f"/admin/org/users/{user_id}?group_id={resolved}"},
            ],
        ),
    )


@router.post("/users/invite", response_class=HTMLResponse)
def org_invite_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    group_id_form: str = Form(..., alias="group_id"),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id_form, db)
    if resolved is None:
        raise HTTPException(status_code=400, detail="group_id required")

    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    raw_code = generate_invite_code()
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        system_role="external_user",
        group_id=resolved,
        invite_code=hash_token(raw_code),
        invite_expires_at=datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=7),
    )
    db.add(new_user)
    db.commit()

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    users = db.query(User).filter(User.group_id == resolved).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/org/users.html",
        context=_ctx(
            user,
            group=group,
            users=users,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": group.name, "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Users", "url": f"/admin/org/users?group_id={resolved}"},
            ],
        ),
    )


@router.post("/users/{user_id}/deactivate", response_class=HTMLResponse)
def org_deactivate_user(
    user_id: str,
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if resolved and target.group_id != resolved:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    db.commit()
    return org_user_detail(user_id, request, group_id, user, db)


@router.post("/users/{user_id}/activate", response_class=HTMLResponse)
def org_activate_user(
    user_id: str,
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if resolved and target.group_id != resolved:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    return org_user_detail(user_id, request, group_id, user, db)


@router.get("/matters", response_class=HTMLResponse)
def org_matters(
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    if resolved is None:
        raise HTTPException(status_code=400, detail="group_id required")
    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    matters = (
        db.query(Matter)
        .filter(Matter.owner_group_id == resolved)
        .order_by(Matter.status, Matter.target_delivery_date)
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/org/matters.html",
        context=_ctx(
            user,
            group=group,
            matters=matters,
            breadcrumbs=[
                {"label": group.name, "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Matters", "url": f"/admin/org/matters?group_id={resolved}"},
            ],
        ),
    )


@router.get("/matters/{matter_id}/access", response_class=HTMLResponse)
def org_matter_access(
    matter_id: str,
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    matter = db.get(Matter, matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found")
    # Tenant isolation
    if resolved and matter.owner_group_id != resolved:
        raise HTTPException(status_code=403, detail="Access denied")

    rows = db.execute(
        select(MatterAccess, User)
        .join(User, MatterAccess.user_id == User.id)
        .where(MatterAccess.matter_id == matter_id)
    ).all()
    grants = [{"user": u, "role": g.role} for g, u in rows]

    # For external_admin, only show users in their group
    if resolved:
        group_users = db.query(User).filter(User.group_id == resolved).order_by(User.email).all()
    else:
        group_users = db.query(User).order_by(User.email).all()

    group = db.get(Group, resolved) if resolved else None
    return templates.TemplateResponse(
        request=request,
        name="admin/org/matter_access.html",
        context=_ctx(
            user,
            matter=matter,
            grants=grants,
            group_users=group_users,
            group=group,
            breadcrumbs=[
                {"label": group.name if group else "Org", "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Matters", "url": f"/admin/org/matters?group_id={resolved}"},
                {"label": matter_id, "url": f"/admin/org/matters/{matter_id}/access?group_id={resolved}"},
            ],
        ),
    )


@router.post("/matters/{matter_id}/access", response_class=HTMLResponse)
def org_grant_matter_access(
    matter_id: str,
    request: Request,
    user_id: str = Form(...),
    role: str = Form(...),
    group_id: str | None = Form(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    valid_roles = {"viewer", "editor", "contributor", "manager"}
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail="Invalid role")

    resolved = _resolve_group_id(user, group_id, db)
    matter = db.get(Matter, matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found")
    if resolved and matter.owner_group_id != resolved:
        raise HTTPException(status_code=403, detail="Access denied")

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = (
        db.query(MatterAccess)
        .filter(MatterAccess.user_id == user_id, MatterAccess.matter_id == matter_id)
        .first()
    )
    if existing:
        existing.role = role
        existing.granted_by_id = user.id
    else:
        db.add(MatterAccess(
            user_id=user_id,
            matter_id=matter_id,
            role=role,
            granted_by_id=user.id,
        ))
    db.commit()
    return org_matter_access(matter_id, request, group_id, user, db)


@router.get("/profile", response_class=HTMLResponse)
def org_profile(
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id, db)
    if resolved is None:
        raise HTTPException(status_code=400, detail="group_id required")
    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return templates.TemplateResponse(
        request=request,
        name="admin/org/profile.html",
        context=_ctx(
            user,
            group=group,
            breadcrumbs=[
                {"label": group.name, "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Profile", "url": f"/admin/org/profile?group_id={resolved}"},
            ],
        ),
    )


@router.post("/profile", response_class=HTMLResponse)
def org_update_profile(
    request: Request,
    name: str = Form(...),
    group_id_form: str = Form(..., alias="group_id"),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id_form, db)
    if resolved is None:
        raise HTTPException(status_code=400, detail="group_id required")
    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    group.name = name
    db.commit()
    return templates.TemplateResponse(
        request=request,
        name="admin/org/profile.html",
        context=_ctx(
            user,
            group=group,
            saved=True,
            breadcrumbs=[
                {"label": group.name, "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Profile", "url": f"/admin/org/profile?group_id={resolved}"},
            ],
        ),
    )
