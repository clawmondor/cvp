"""Create/validate/list/revoke RBAC v2 role grants for external users."""

from sqlalchemy.orm import Session

from claimos.dependencies import ROLE_HIERARCHY
from claimos.models_auth import User
from claimos.models_grants import RoleGrant, RoleGrantClaim, RoleGrantOverride
from claimos.roles import OBJECT_TYPES, get_user_role
from claimos.services.access_cache import invalidate_user


class GrantValidationError(ValueError):
    """Raised when a grant request violates a structural rule."""


def create_grant(
    db: Session,
    *,
    user_id: str,
    user_role: str,
    scope: str,
    claim_ids: list[str],
    overrides: dict[str, str],
    granted_by_id: str,
) -> RoleGrant:
    role = get_user_role(user_role)
    if role is None:
        raise GrantValidationError(f"Unknown user role: {user_role}")
    if scope not in ("group", "claims"):
        raise GrantValidationError(f"Invalid scope: {scope}")

    grantee = db.get(User, user_id)
    if grantee is None:
        raise GrantValidationError("Grantee not found")
    if grantee.group_id is None:
        raise GrantValidationError("Grantee has no group")

    if role.single_claim_only:
        if scope != "claims" or len(claim_ids) != 1:
            raise GrantValidationError(f"{user_role} must be scoped to exactly one claim")
    if scope == "claims" and not claim_ids:
        raise GrantValidationError("claims scope requires at least one claim")

    grant = RoleGrant(
        user_id=user_id,
        group_id=grantee.group_id,
        user_role=user_role,
        scope=scope,
        granted_by_id=granted_by_id,
    )
    db.add(grant)
    db.flush()

    if scope == "claims":
        for cid in claim_ids:
            db.add(RoleGrantClaim(grant_id=grant.id, claim_id=cid))
    for object_type, ov_role in overrides.items():
        db.add(RoleGrantOverride(grant_id=grant.id, object_type=object_type, role=ov_role))

    db.commit()
    db.refresh(grant)
    invalidate_user(user_id)
    return grant


def list_grants(db: Session, user_id: str) -> list[RoleGrant]:
    return db.query(RoleGrant).filter(RoleGrant.user_id == user_id).all()


def revoke_grant(db: Session, grant_id: str) -> None:
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        return
    user_id = grant.user_id
    db.delete(grant)
    db.commit()
    invalidate_user(user_id)


def add_override(db: Session, grant_id: str, object_type: str, role: str) -> RoleGrantOverride:
    if object_type not in OBJECT_TYPES:
        raise GrantValidationError(f"Unknown object type: {object_type}")
    if role not in ROLE_HIERARCHY:
        raise GrantValidationError(f"Unknown role: {role}")
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        raise GrantValidationError("Grant not found")
    existing = (
        db.query(RoleGrantOverride)
        .filter(
            RoleGrantOverride.grant_id == grant_id,
            RoleGrantOverride.object_type == object_type,
        )
        .first()
    )
    if existing is not None:
        existing.role = role
        override = existing
    else:
        override = RoleGrantOverride(grant_id=grant_id, object_type=object_type, role=role)
        db.add(override)
    db.commit()
    db.refresh(override)
    invalidate_user(grant.user_id)
    return override


def remove_override(db: Session, grant_id: str, object_type: str) -> None:
    grant = db.get(RoleGrant, grant_id)
    if grant is None:
        return
    row = (
        db.query(RoleGrantOverride)
        .filter(
            RoleGrantOverride.grant_id == grant_id,
            RoleGrantOverride.object_type == object_type,
        )
        .first()
    )
    if row is not None:
        db.delete(row)
        db.commit()
        invalidate_user(grant.user_id)
