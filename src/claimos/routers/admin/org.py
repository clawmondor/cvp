"""External Admin (Org) panel router."""

import datetime
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimos.auth import generate_invite_code, hash_token
from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_active_user
from claimos.models import Claim
from claimos.models_access import ClaimAccess
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant
from claimos.roles import USER_ROLES
from claimos.services.grants import GrantValidationError, create_grant, list_grants, revoke_grant
from claimos.templating import templates

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


def _resolve_group_id(user: CurrentUser, group_id: str | None) -> str | None:
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
    resolved = _resolve_group_id(user, group_id)
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
    claim_count = db.query(Claim).filter(Claim.owner_group_id == resolved).count()
    return templates.TemplateResponse(
        request=request,
        name="admin/org/dashboard.html",
        context=_ctx(
            user,
            group=group,
            user_count=user_count,
            claim_count=claim_count,
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
    resolved = _resolve_group_id(user, group_id)
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
    resolved = _resolve_group_id(user, group_id)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Tenant isolation: external_admin can only see own group
    if resolved and target.group_id != resolved:
        raise HTTPException(status_code=404, detail="User not found")
    group = db.get(Group, target.group_id) if target.group_id else None
    group_label = group.name if group else "Org"
    group_url = f"/admin/org/?group_id={resolved}"
    users_url = f"/admin/org/users?group_id={resolved}"
    user_url = f"/admin/org/users/{user_id}?group_id={resolved}"
    grants = list_grants(db, target.id)
    group_claims = (
        db.query(Claim).filter(Claim.owner_group_id == target.group_id).order_by(Claim.id).all()
        if target.group_id
        else []
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/org/user_detail.html",
        context=_ctx(
            user,
            target=target,
            group=group,
            grants=grants,
            user_roles=USER_ROLES,
            group_claims=group_claims,
            breadcrumbs=[
                {"label": group_label, "url": group_url},
                {"label": "Users", "url": users_url},
                {"label": target.email, "url": user_url},
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
    resolved = _resolve_group_id(user, group_id_form)
    if resolved is None:
        raise HTTPException(status_code=400, detail="group_id required")

    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    raw_code = generate_invite_code()
    expires_at = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=7)
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
        system_role="external_user",
        group_id=resolved,
        invite_code=hash_token(raw_code),
        invite_expires_at=expires_at,
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
    resolved = _resolve_group_id(user, group_id)
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
    resolved = _resolve_group_id(user, group_id)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if resolved and target.group_id != resolved:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    return org_user_detail(user_id, request, group_id, user, db)


@router.post("/users/{user_id}/grants", response_class=HTMLResponse)
def org_assign_grant(
    user_id: str,
    request: Request,
    user_role: str = Form(...),
    scope: str = Form("group"),
    claim_ids: list[str] = Form(default=[]),
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.system_role == "external_admin" and target.group_id != user.group_id:
        raise HTTPException(status_code=403, detail="Cannot grant outside your group")
    try:
        create_grant(
            db,
            user_id=user_id,
            user_role=user_role,
            scope=scope,
            claim_ids=claim_ids,
            overrides={},  # override editor added with the Users-page slice
            granted_by_id=user.id,
        )
    except GrantValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return org_user_detail(user_id, request, group_id, user, db)


@router.post("/grants/{grant_id}/revoke", response_class=HTMLResponse)
def org_revoke_grant(
    grant_id: str,
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    if user.system_role == "external_admin" and grant.group_id != user.group_id:
        raise HTTPException(status_code=403, detail="Cannot revoke outside your group")
    user_id = grant.user_id
    revoke_grant(db, grant_id)
    return org_user_detail(user_id, request, group_id, user, db)


@router.get("/claims", response_class=HTMLResponse)
def org_claims(
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id)
    if resolved is None:
        raise HTTPException(status_code=400, detail="group_id required")
    group = db.get(Group, resolved)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    claims = (
        db.query(Claim)
        .filter(Claim.owner_group_id == resolved)
        .order_by(Claim.status, Claim.target_delivery_date)
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/org/claims.html",
        context=_ctx(
            user,
            group=group,
            claims=claims,
            breadcrumbs=[
                {"label": group.name, "url": f"/admin/org/?group_id={resolved}"},
                {"label": "Claims", "url": f"/admin/org/claims?group_id={resolved}"},
            ],
        ),
    )


@router.get("/claims/{claim_id}/access", response_class=HTMLResponse)
def org_claim_access(
    claim_id: str,
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    # Tenant isolation
    if resolved and claim.owner_group_id != resolved:
        raise HTTPException(status_code=403, detail="Access denied")

    rows = db.execute(
        select(ClaimAccess, User)
        .join(User, ClaimAccess.user_id == User.id)
        .where(ClaimAccess.claim_id == claim_id)
    ).all()
    grants = [{"user": u, "role": g.role} for g, u in rows]

    # For external_admin, only show users in their group
    if resolved:
        group_users = db.query(User).filter(User.group_id == resolved).order_by(User.email).all()
    else:
        group_users = db.query(User).order_by(User.email).all()

    group = db.get(Group, resolved) if resolved else None
    group_label = group.name if group else "Org"
    group_url = f"/admin/org/?group_id={resolved}"
    claims_url = f"/admin/org/claims?group_id={resolved}"
    claim_url = f"/admin/org/claims/{claim_id}/access?group_id={resolved}"
    return templates.TemplateResponse(
        request=request,
        name="admin/org/claim_access.html",
        context=_ctx(
            user,
            claim=claim,
            grants=grants,
            group_users=group_users,
            group=group,
            breadcrumbs=[
                {"label": group_label, "url": group_url},
                {"label": "Claims", "url": claims_url},
                {"label": claim_id, "url": claim_url},
            ],
        ),
    )


@router.post("/claims/{claim_id}/access", response_class=HTMLResponse)
def org_grant_claim_access(
    claim_id: str,
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

    resolved = _resolve_group_id(user, group_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    if resolved and claim.owner_group_id != resolved:
        raise HTTPException(status_code=403, detail="Access denied")

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
    return org_claim_access(claim_id, request, group_id, user, db)


@router.get("/profile", response_class=HTMLResponse)
def org_profile(
    request: Request,
    group_id: str | None = Query(None),
    user: CurrentUser = Depends(_require_org_admin_or_above),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resolved = _resolve_group_id(user, group_id)
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
    resolved = _resolve_group_id(user, group_id_form)
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
