"""Matter sharing endpoints — grant and revoke per-user access."""

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from cvp.db import get_db
from cvp.dependencies import CurrentUser, require_matter_role
from cvp.models_access import MatterAccess
from cvp.models_auth import User

router = APIRouter()


@router.post("/api/matters/{matter_id}/access")
def grant_access(
    matter_id: str,
    user_id: str = Form(...),
    role: str = Form(...),
    user: CurrentUser = Depends(require_matter_role("manager")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Grant a user access to a matter with a specific role."""
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

    existing = (
        db.query(MatterAccess)
        .filter(MatterAccess.user_id == user_id, MatterAccess.matter_id == matter_id)
        .first()
    )

    if existing:
        existing.role = role
        existing.granted_by_id = user.id
    else:
        access = MatterAccess(
            user_id=user_id,
            matter_id=matter_id,
            role=role,
            granted_by_id=user.id,
        )
        db.add(access)

    db.commit()
    return JSONResponse({"ok": True, "user_id": user_id, "role": role})


@router.delete("/api/matters/{matter_id}/access/{target_user_id}")
def revoke_access(
    matter_id: str,
    target_user_id: str,
    user: CurrentUser = Depends(require_matter_role("manager")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Revoke a user's access to a matter."""
    access = (
        db.query(MatterAccess)
        .filter(
            MatterAccess.user_id == target_user_id,
            MatterAccess.matter_id == matter_id,
        )
        .first()
    )
    if access is None:
        raise HTTPException(status_code=404, detail="Access grant not found")

    # Tenant isolation
    if user.group_kind == "external":
        target = db.get(User, target_user_id)
        if target and target.group_id != user.group_id:
            raise HTTPException(
                status_code=403,
                detail="Cannot revoke access for users outside your group",
            )

    db.delete(access)
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/api/matters/{matter_id}/access")
def list_access(
    matter_id: str,
    user: CurrentUser = Depends(require_matter_role("manager")),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """List all users with access to a matter."""
    grants = db.query(MatterAccess).filter(MatterAccess.matter_id == matter_id).all()

    result = []
    for g in grants:
        target = db.get(User, g.user_id)
        if target is None:
            continue
        # Tenant isolation: external users only see their own group's users
        if user.group_kind == "external" and target.group_id != user.group_id:
            continue
        result.append(
            {
                "user_id": g.user_id,
                "email": target.email,
                "display_name": target.display_name,
                "role": g.role,
                "granted_by_id": g.granted_by_id,
            }
        )

    return JSONResponse(result)
