"""Read-only helpers that resolve a user's effective RBAC v2 permissions.

group_effective_matrix  -> group-wide baseline (group-scoped grants + overrides)
claim_effective_matrix  -> full resolution for one claim (delegates to the resolver)
claim_members_access    -> every firm member with any access on a claim
"""

from sqlalchemy.orm import Session

from claimos.dependencies import ROLE_HIERARCHY, CurrentUser, _external_effective_role
from claimos.models_auth import User
from claimos.models_grants import RoleGrant, RoleGrantOverride
from claimos.roles import OBJECT_TYPES, role_for_object


def group_effective_matrix(db: Session, user_id: str, group_id: str) -> dict[str, str | None]:
    """Max role per object type over the user's GROUP-scoped grants + overrides."""
    grants = (
        db.query(RoleGrant)
        .filter(
            RoleGrant.user_id == user_id,
            RoleGrant.group_id == group_id,
            RoleGrant.scope == "group",
        )
        .all()
    )
    matrix: dict[str, str | None] = {obj: None for obj in OBJECT_TYPES}
    for grant in grants:
        overrides = {
            o.object_type: o.role
            for o in db.query(RoleGrantOverride).filter(RoleGrantOverride.grant_id == grant.id)
        }
        for obj in OBJECT_TYPES:
            role = role_for_object(grant.user_role, obj)
            ov = overrides.get(obj)
            if ov is not None and (
                role is None or ROLE_HIERARCHY.get(ov, -1) > ROLE_HIERARCHY.get(role, -1)
            ):
                role = ov
            if role is None:
                continue
            current = matrix[obj]
            if current is None or ROLE_HIERARCHY.get(role, -1) > ROLE_HIERARCHY.get(current, -1):
                matrix[obj] = role
    return matrix


def claim_effective_matrix(db: Session, user: CurrentUser, claim_id: str) -> dict[str, str | None]:
    """Full per-claim resolution (group + claim-scoped grants + overrides)."""
    return {obj: _external_effective_role(db, user, claim_id, obj) for obj in OBJECT_TYPES}


def claim_members_access(
    db: Session, group_id: str, claim_id: str
) -> list[tuple[User, dict[str, str | None]]]:
    """Every firm member with any resolved access on the claim, with their matrix."""
    members = db.query(User).filter(User.group_id == group_id).order_by(User.email).all()
    rows: list[tuple[User, dict[str, str | None]]] = []
    for member in members:
        cu = CurrentUser(
            id=member.id,
            email=member.email,
            system_role=member.system_role,
            group_id=member.group_id,
            group_kind="external",
        )
        matrix = claim_effective_matrix(db, cu, claim_id)
        if all(v is None for v in matrix.values()) and member.system_role == "external_admin":
            from claimos.models import Claim

            claim = db.get(Claim, claim_id)
            if claim is not None and claim.owner_group_id == group_id:
                matrix = {obj: "manager" for obj in matrix}
        if any(v is not None for v in matrix.values()):
            rows.append((member, matrix))
    return rows
