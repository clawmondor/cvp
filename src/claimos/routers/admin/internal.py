"""Internal Admin panel router."""

import datetime
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimos.auth import generate_invite_code, hash_token
from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_active_user
from claimos.models import Claim
from claimos.models_access import ClaimAccess
from claimos.models_auth import Group, User
from claimos.services.audit import get_client_ip, write_audit_log

BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin/internal")

_CTX = {"panel_color": "indigo", "panel_title": "Internal Administration"}


def _ctx(user: CurrentUser, **kwargs) -> dict[str, object]:
    return {**_CTX, "user": user, **kwargs}


async def _require_internal_or_above(
    user: CurrentUser = Depends(require_active_user),
) -> CurrentUser:
    """Require system_admin or internal_admin."""
    if user.system_role not in ("system_admin", "internal_admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


@router.get("/", response_class=HTMLResponse)
def internal_dashboard(
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    internal_user_count = db.query(User).filter(User.group_id == user.group_id).count()
    external_group_count = db.query(Group).filter(Group.kind == "external").count()
    claim_count = db.query(Claim).filter(Claim.owner_group_id == user.group_id).count()
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/dashboard.html",
        context=_ctx(
            user,
            internal_user_count=internal_user_count,
            external_group_count=external_group_count,
            claim_count=claim_count,
            breadcrumbs=[{"label": "Internal Admin", "url": "/admin/internal/"}],
        ),
    )


@router.get("/users", response_class=HTMLResponse)
def internal_users(
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    users = db.query(User).filter(User.group_id == user.group_id).order_by(User.email).all()
    internal_group = db.get(Group, user.group_id)
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/users.html",
        context=_ctx(
            user,
            users=users,
            internal_group=internal_group,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "Users", "url": "/admin/internal/users"},
            ],
        ),
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
def internal_user_detail(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="User not found")
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/user_detail.html",
        context=_ctx(
            user,
            target=target,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "Users", "url": "/admin/internal/users"},
                {"label": target.email, "url": f"/admin/internal/users/{user_id}"},
            ],
        ),
    )


@router.post("/users/{user_id}/activate", response_class=HTMLResponse)
def internal_activate_user(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    return internal_user_detail(user_id, request, user, db)


@router.post("/users/{user_id}/deactivate", response_class=HTMLResponse)
def internal_deactivate_user(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    db.commit()
    return internal_user_detail(user_id, request, user, db)


@router.post("/users/{user_id}/regenerate-invite", response_class=HTMLResponse)
def internal_regenerate_invite(
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="User not found")
    if not target.is_active:
        raise HTTPException(status_code=400, detail="Cannot regenerate invite for an inactive user")

    raw_code = generate_invite_code()
    now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
    target.invite_code = hash_token(raw_code)
    target.invite_expires_at = now_utc + datetime.timedelta(days=7)
    target.password_changed_at = None
    db.commit()

    background_tasks.add_task(
        write_audit_log,
        user_id=user.id,
        action="admin.invite_regenerated",
        resource_type="user",
        resource_id=user_id,
        ip_address=get_client_ip(request),
    )

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/user_detail.html",
        context=_ctx(
            user,
            target=target,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "Users", "url": "/admin/internal/users"},
                {"label": target.email, "url": f"/admin/internal/users/{user_id}"},
            ],
        ),
    )


@router.post("/users/invite", response_class=HTMLResponse)
def internal_invite_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    raw_code = generate_invite_code()
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        system_role="internal_user",
        group_id=user.group_id,
        invite_code=hash_token(raw_code),
        invite_expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(days=7),
    )
    db.add(new_user)
    db.commit()

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    users = db.query(User).filter(User.group_id == user.group_id).order_by(User.email).all()
    internal_group = db.get(Group, user.group_id)
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/users.html",
        context=_ctx(
            user,
            users=users,
            internal_group=internal_group,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "Users", "url": "/admin/internal/users"},
            ],
        ),
    )


@router.get("/claims", response_class=HTMLResponse)
def internal_claims(
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    claims = (
        db.query(Claim)
        .filter(Claim.owner_group_id == user.group_id)
        .order_by(Claim.status, Claim.target_delivery_date)
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/claims.html",
        context=_ctx(
            user,
            claims=claims,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "Claims", "url": "/admin/internal/claims"},
            ],
        ),
    )


@router.get("/claims/{claim_id}/access", response_class=HTMLResponse)
def internal_claim_access(
    claim_id: str,
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    rows = db.execute(
        select(ClaimAccess, User)
        .join(User, ClaimAccess.user_id == User.id)
        .where(ClaimAccess.claim_id == claim_id)
    ).all()
    grants = [{"user": u, "role": g.role} for g, u in rows]

    all_users = db.query(User).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/claim_access.html",
        context=_ctx(
            user,
            claim=claim,
            grants=grants,
            all_users=all_users,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "Claims", "url": "/admin/internal/claims"},
                {"label": claim_id, "url": f"/admin/internal/claims/{claim_id}/access"},
            ],
        ),
    )


@router.post("/claims/{claim_id}/access", response_class=HTMLResponse)
def internal_grant_claim_access(
    claim_id: str,
    request: Request,
    user_id: str = Form(...),
    role: str = Form(...),
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    valid_roles = {"viewer", "editor", "contributor", "manager"}
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail="Invalid role")

    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = (
        db.query(ClaimAccess)
        .filter(ClaimAccess.user_id == user_id, ClaimAccess.claim_id == claim_id)
        .first()
    )
    if existing:
        existing.role = role
        existing.granted_by_id = user.id
    else:
        db.add(
            ClaimAccess(
                user_id=user_id,
                claim_id=claim_id,
                role=role,
                granted_by_id=user.id,
            )
        )
    db.commit()
    return internal_claim_access(claim_id, request, user, db)


@router.get("/groups", response_class=HTMLResponse)
def internal_groups(
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    groups = db.query(Group).filter(Group.kind == "external").order_by(Group.name).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/groups.html",
        context=_ctx(
            user,
            groups=groups,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "External Groups", "url": "/admin/internal/groups"},
            ],
        ),
    )


@router.post("/groups", response_class=HTMLResponse)
def internal_create_group(
    request: Request,
    name: str = Form(...),
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if db.query(Group).filter(Group.name == name).first():
        raise HTTPException(status_code=400, detail="A group with this name already exists")
    group = Group(id=str(uuid.uuid4()), name=name, kind="external")
    db.add(group)
    db.commit()
    return internal_groups(request, user, db)


@router.get("/groups/{group_id}", response_class=HTMLResponse)
def internal_group_detail(
    group_id: str,
    request: Request,
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, group_id)
    if group is None or group.kind != "external":
        raise HTTPException(status_code=404, detail="Group not found")
    members = db.query(User).filter(User.group_id == group_id).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/group_detail.html",
        context=_ctx(
            user,
            group=group,
            members=members,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "External Groups", "url": "/admin/internal/groups"},
                {"label": group.name, "url": f"/admin/internal/groups/{group_id}"},
            ],
        ),
    )


@router.post("/groups/{group_id}/invite-admin", response_class=HTMLResponse)
def internal_invite_group_admin(
    group_id: str,
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    user: CurrentUser = Depends(_require_internal_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = db.get(Group, group_id)
    if group is None or group.kind != "external":
        raise HTTPException(status_code=404, detail="Group not found")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    raw_code = generate_invite_code()
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        system_role="external_admin",
        group_id=group_id,
        invite_code=hash_token(raw_code),
        invite_expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(days=7),
    )
    db.add(new_user)
    db.commit()

    invite_url = str(request.base_url).rstrip("/") + f"/register/{raw_code}"
    members = db.query(User).filter(User.group_id == group_id).order_by(User.email).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/internal/group_detail.html",
        context=_ctx(
            user,
            group=group,
            members=members,
            invite_url=invite_url,
            breadcrumbs=[
                {"label": "Internal Admin", "url": "/admin/internal/"},
                {"label": "External Groups", "url": "/admin/internal/groups"},
                {"label": group.name, "url": f"/admin/internal/groups/{group_id}"},
            ],
        ),
    )
