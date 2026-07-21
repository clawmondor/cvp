"""Claim sharing endpoints — grant and revoke per-user access."""

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimos.db import get_db
from claimos.dependencies import CurrentUser, require_claim_role
from claimos.models_access import ClaimAccess
from claimos.models_auth import User

router = APIRouter()


@router.post("/api/claims/{claim_id}/access")
def grant_access(
    claim_id: str,
    user_id: str = Form(...),
    role: str = Form(...),
    user: CurrentUser = Depends(require_claim_role("manager", "users")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Grant a user access to a claim with a specific role."""
    valid_roles = {"viewer", "editor", "contributor", "manager"}
    if role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {sorted(valid_roles)}",
        )

    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Tenant isolation: External users can only grant access to their own group members
    if user.group_kind == "external" and target_user.group_id != user.group_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot grant access to users outside your group",
        )

    # RBAC v2: external users are resolved via role_grants, not claim_access — a
    # claim_access row written here would be silently inert for them. Reject
    # instead of misleading the grantor with a false "success".
    if target_user.group and target_user.group.kind == "external":
        raise HTTPException(
            status_code=400,
            detail="External users are managed via role grants; use the Roles & Access panel.",
        )

    existing = (
        db.query(ClaimAccess)
        .filter(ClaimAccess.user_id == user_id, ClaimAccess.claim_id == claim_id)
        .first()
    )

    if existing:
        existing.role = role
        existing.granted_by_id = user.id
    else:
        access = ClaimAccess(
            user_id=user_id,
            claim_id=claim_id,
            role=role,
            granted_by_id=user.id,
        )
        db.add(access)

    db.commit()
    return JSONResponse({"ok": True, "user_id": user_id, "role": role})


@router.delete("/api/claims/{claim_id}/access/{target_user_id}")
def revoke_access(
    claim_id: str,
    target_user_id: str,
    user: CurrentUser = Depends(require_claim_role("manager", "users")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Revoke a user's access to a claim."""
    # 1. Load the target user first
    target = db.get(User, target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    # 2. Tenant isolation guard before checking the grant
    if user.group_kind == "external" and target.group_id != user.group_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot revoke access for users outside your group",
        )

    # 3. Find the grant and 404 if not found
    access = (
        db.query(ClaimAccess)
        .filter(
            ClaimAccess.user_id == target_user_id,
            ClaimAccess.claim_id == claim_id,
        )
        .first()
    )
    if access is None:
        raise HTTPException(status_code=404, detail="Access grant not found")

    # 4. Delete
    db.delete(access)
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/api/claims/{claim_id}/access")
def list_access(
    claim_id: str,
    user: CurrentUser = Depends(require_claim_role("contributor", "users")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """List all users with access to a claim."""
    rows = db.execute(
        select(ClaimAccess, User)
        .join(User, ClaimAccess.user_id == User.id)
        .where(ClaimAccess.claim_id == claim_id)
    ).all()

    result = []
    for grant, target in rows:
        if user.group_kind == "external" and target.group_id != user.group_id:
            continue
        result.append(
            {
                "user_id": grant.user_id,
                "email": target.email,
                "display_name": target.display_name,
                "role": grant.role,
                "granted_by_id": grant.granted_by_id,
            }
        )

    return JSONResponse(result)
