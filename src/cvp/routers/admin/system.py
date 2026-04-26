"""System Admin panel router."""

import datetime
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cvp.auth import generate_invite_code, hash_token
from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_system_admin
from cvp.models import Matter
from cvp.models_auth import Group, User

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/system")

_CTX = {"panel_color": "slate", "panel_title": "System Administration"}


def _ctx(user: CurrentUser, **kwargs) -> dict:
    return {**_CTX, "user": user, **kwargs}


@router.get("/", response_class=HTMLResponse)
def system_dashboard(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user_count = db.query(User).count()
    group_count = db.query(Group).count()
    matter_count = db.query(Matter).count()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/dashboard.html",
        context=_ctx(
            user,
            user_count=user_count,
            group_count=group_count,
            matter_count=matter_count,
            breadcrumbs=[{"label": "System Admin", "url": "/admin/system/"}],
        ),
    )


@router.get("/users", response_class=HTMLResponse)
def system_users(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    users = db.query(User).order_by(User.email).all()
    groups = db.query(Group).order_by(Group.name).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/users.html",
        context=_ctx(
            user,
            users=users,
            groups=groups,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Users", "url": "/admin/system/users"},
            ],
        ),
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
def system_user_detail(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    group = db.get(Group, target.group_id) if target.group_id else None
    return templates.TemplateResponse(
        request=request,
        name="admin/system/user_detail.html",
        context=_ctx(
            user,
            target=target,
            group=group,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Users", "url": "/admin/system/users"},
                {"label": target.email, "url": f"/admin/system/users/{user_id}"},
            ],
        ),
    )


@router.post("/users/invite", response_class=HTMLResponse)
def system_invite_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    system_role: str = Form(...),
    group_id: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    valid_roles = {
        "system_admin", "internal_admin", "internal_user",
        "specialist", "external_admin", "external_user",
    }
    if system_role not in valid_roles:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=400, detail="Group not found")

    raw_code = generate_invite_code()
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        system_role=system_role,
        group_id=group_id,
        invite_code=hash_token(raw_code),
        invite_expires_at=now_utc + datetime.timedelta(days=7),
    )
    db.add(new_user)
    db.commit()

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    groups = db.query(Group).order_by(Group.name).all()
    users = db.query(User).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/users.html",
        context=_ctx(user, users=users, groups=groups, invite_url=invite_url,
                     breadcrumbs=[
                         {"label": "System Admin", "url": "/admin/system/"},
                         {"label": "Users", "url": "/admin/system/users"},
                     ]),
    )


@router.post("/users/{user_id}/deactivate", response_class=HTMLResponse)
def system_deactivate_user(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    db.commit()
    return system_user_detail(user_id, request, user, db)


@router.post("/users/{user_id}/activate", response_class=HTMLResponse)
def system_activate_user(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    return system_user_detail(user_id, request, user, db)


@router.post("/users/{user_id}/reset-mfa", response_class=HTMLResponse)
def system_reset_mfa(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.mfa_enabled = False
    target.mfa_secret = None
    db.commit()
    return system_user_detail(user_id, request, user, db)


@router.get("/groups", response_class=HTMLResponse)
def system_groups(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    groups = db.query(Group).order_by(Group.name).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/groups.html",
        context=_ctx(
            user,
            groups=groups,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Groups", "url": "/admin/system/groups"},
            ],
        ),
    )


@router.post("/groups", response_class=HTMLResponse)
def system_create_group(
    request: Request,
    name: str = Form(...),
    kind: str = Form(...),
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if db.query(Group).filter(Group.name == name).first():
        raise HTTPException(status_code=400, detail="A group with this name already exists")
    group = Group(id=str(uuid.uuid4()), name=name, kind=kind)
    db.add(group)
    db.commit()
    return system_groups(request, user, db)


@router.get("/groups/{group_id}", response_class=HTMLResponse)
def system_group_detail(
    group_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    members = db.query(User).filter(User.group_id == group_id).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/group_detail.html",
        context=_ctx(
            user,
            group=group,
            members=members,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Groups", "url": "/admin/system/groups"},
                {"label": group.name, "url": f"/admin/system/groups/{group_id}"},
            ],
        ),
    )


@router.post("/groups/{group_id}/deactivate", response_class=HTMLResponse)
def system_deactivate_group(
    group_id: str,
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    group.is_active = False
    db.commit()
    return system_group_detail(group_id, request, user, db)


@router.get("/matters", response_class=HTMLResponse)
def system_matters(
    request: Request,
    user: CurrentUser = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    matters = db.query(Matter).order_by(Matter.status, Matter.target_delivery_date).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/system/matters.html",
        context=_ctx(
            user,
            matters=matters,
            breadcrumbs=[
                {"label": "System Admin", "url": "/admin/system/"},
                {"label": "Matters", "url": "/admin/system/matters"},
            ],
        ),
    )
