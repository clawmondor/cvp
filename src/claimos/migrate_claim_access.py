"""Convert external users' single-role claim_access rows into RBAC v2 grants."""

from sqlalchemy.orm import Session

from claimos.models_access import ClaimAccess
from claimos.models_auth import User
from claimos.models_grants import RoleGrant, RoleGrantClaim


def migrate_external_claim_access(db: Session) -> int:
    """Idempotent-ish: converts and deletes external claim_access rows. Returns count."""
    rows = db.query(ClaimAccess).all()
    migrated = 0
    for row in rows:
        user = db.get(User, row.user_id)
        if user is None or user.group_id is None:
            continue
        group = user.group
        if group is None or group.kind != "external":
            continue  # leave internal rows alone
        grant = RoleGrant(
            user_id=row.user_id,
            group_id=user.group_id,
            user_role=f"_uniform:{row.role}",
            scope="claims",
            granted_by_id=row.granted_by_id,
        )
        db.add(grant)
        db.flush()
        db.add(RoleGrantClaim(grant_id=grant.id, claim_id=row.claim_id))
        db.delete(row)
        migrated += 1
    db.commit()
    return migrated
