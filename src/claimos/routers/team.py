"""Firm-facing Team management surface for external admins (RBAC v2)."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from claimos.db import get_db
from claimos.dependencies import ROLE_HIERARCHY, CurrentUser, require_active_user
from claimos.models import Claim
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant
from claimos.roles import OBJECT_TYPES, USER_ROLES
from claimos.services.effective_permissions import group_effective_matrix
from claimos.services.grants import GrantValidationError, create_grant, list_grants, revoke_grant
from claimos.templating import templates

router = APIRouter(prefix="/team")


async def require_external_admin(
    user: CurrentUser = Depends(require_active_user),
) -> CurrentUser:
    """Allow external_admin and system_admin; everyone else 403."""
    if user.system_role not in ("external_admin", "system_admin"):
        raise HTTPException(status_code=403, detail="Team access requires firm admin")
    return user


def _load_own_member(db: Session, user: CurrentUser, user_id: str) -> User:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Member not found")
    return target


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


@router.get("/users/{user_id}", response_class=HTMLResponse)
def team_user_detail(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    target = db.get(User, user_id)
    if target is None or target.group_id != user.group_id:
        raise HTTPException(status_code=404, detail="Member not found")
    grants = list_grants(db, target.id)
    claim_grants = [g for g in grants if g.scope == "claims"]
    effective = group_effective_matrix(db, target.id, user.group_id)
    group_claims = (
        db.query(Claim).filter(Claim.owner_group_id == user.group_id).order_by(Claim.id).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="team/user_detail.html",
        context={
            "user": user,
            "target": target,
            "grants": grants,
            "claim_grants": claim_grants,
            "effective": effective,
            "object_types": OBJECT_TYPES,
            "user_roles": USER_ROLES,
            "role_levels": list(ROLE_HIERARCHY.keys()),
            "group_claims": group_claims,
        },
    )


@router.post("/users/{user_id}/deactivate")
def team_deactivate(
    user_id: str,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    target = _load_own_member(db, user, user_id)
    target.is_active = False
    db.commit()
    return RedirectResponse(url=f"/team/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/activate")
def team_activate(
    user_id: str,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    target = _load_own_member(db, user, user_id)
    target.is_active = True
    db.commit()
    return RedirectResponse(url=f"/team/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/grants")
def team_assign_grant(
    user_id: str,
    user_role: str = Form(...),
    scope: str = Form("group"),
    claim_ids: list[str] = Form(default=[]),
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    target = _load_own_member(db, user, user_id)
    # claim_ids must belong to the firm (defense in depth).
    if scope == "claims":
        owned = {
            c.id
            for c in db.query(Claim).filter(
                Claim.owner_group_id == user.group_id, Claim.id.in_(claim_ids)
            )
        }
        if set(claim_ids) - owned:
            raise HTTPException(status_code=400, detail="Claim not in your firm")
    try:
        create_grant(
            db,
            user_id=target.id,
            user_role=user_role,
            scope=scope,
            claim_ids=claim_ids,
            overrides={},
            granted_by_id=user.id,
        )
    except GrantValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/team/users/{user_id}", status_code=303)


@router.post("/grants/{grant_id}/revoke")
def team_revoke_grant(
    grant_id: str,
    user: CurrentUser = Depends(require_external_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    if grant.group_id != user.group_id:
        raise HTTPException(status_code=403, detail="Grant not in your firm")
    target_user_id = grant.user_id
    revoke_grant(db, grant_id)
    return RedirectResponse(url=f"/team/users/{target_user_id}", status_code=303)
