"""Seed initial System Admin user and Internal group.

Entry point: uv run seed-auth
Idempotent: safe to run multiple times.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from cvp.auth import generate_invite_code, hash_token
from cvp.db import SessionLocal
from cvp.models_auth import Group, User


def seed_auth(db: Session) -> None:
    """Create the Internal group and first System Admin if they don't exist."""
    # Create Internal group
    internal_group = db.query(Group).filter(Group.kind == "internal").first()
    if internal_group is None:
        internal_group = Group(
            name="Contents Valuation LLC",
            kind="internal",
        )
        db.add(internal_group)
        db.flush()
        print(f"Created Internal group: {internal_group.name} (id: {internal_group.id})")
    else:
        print(f"Internal group already exists: {internal_group.name}")

    # Create System Admin user with invite code
    admin = db.query(User).filter(User.system_role == "system_admin").first()
    if admin is None:
        raw_invite = generate_invite_code()
        admin = User(
            email="admin@contentsvaluation.com",
            display_name="System Admin",
            password_hash="__invite_pending__",  # Not a valid bcrypt hash
            system_role="system_admin",
            group_id=internal_group.id,
            invite_code=hash_token(raw_invite),
            invite_expires_at=datetime.now(tz=timezone.utc) + timedelta(days=7),
        )
        db.add(admin)
        db.flush()
        print(f"Created System Admin: {admin.email}")
        print(f"Invite URL: /register/{raw_invite}")
        print("(This invite expires in 7 days)")
    else:
        print(f"System Admin already exists: {admin.email}")

    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        seed_auth(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
