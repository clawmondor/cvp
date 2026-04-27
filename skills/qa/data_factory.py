"""
Test data factory — creates and destroys QA test data using SQLAlchemy directly.

All test records use the QA_ prefix with a run timestamp suffix so they can be
identified and cleaned up independently of normal data.

Naming convention:
  Users:   email = qa_{role}_{ts}@qa.local
  Groups:  name  = QA_Group_{ts}
  Matters: firm_name = QA_Firm_{ts}
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Ensure the project src is importable
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "src"))

from cvp.auth import hash_password  # noqa: E402
from cvp.db import SessionLocal  # noqa: E402
from cvp.models import Matter, Room  # noqa: E402
from cvp.models_access import MatterAccess  # noqa: E402
from cvp.models_auth import Group, User  # noqa: E402


class DataFactory:
    """
    Creates test data for a single QA run (identified by run_ts).
    Call teardown() when the run finishes (or after each suite if preferred).
    """

    def __init__(self, run_ts: int) -> None:
        self.run_ts = run_ts
        self.ts = str(run_ts)
        self._db = SessionLocal()

        # Track created IDs for teardown
        self._user_ids: list[str] = []
        self._group_ids: list[str] = []
        self._matter_ids: list[str] = []

    # ── Groups ──────────────────────────────────────────────────────────────

    def create_internal_group(self) -> Group:
        """Return the existing internal group (there can only be one)."""
        db = self._db
        group = db.query(Group).filter(Group.kind == "internal").first()
        if group is None:
            group = Group(name=f"QA_Internal_{self.ts}", kind="internal")
            db.add(group)
            db.commit()
            db.refresh(group)
            self._group_ids.append(group.id)
        return group

    def create_external_group(self, suffix: str = "") -> Group:
        name = f"QA_Group_{self.ts}" + (f"_{suffix}" if suffix else "")
        db = self._db
        group = Group(name=name, kind="external")
        db.add(group)
        db.commit()
        db.refresh(group)
        self._group_ids.append(group.id)
        return group

    # ── Users ───────────────────────────────────────────────────────────────

    def _make_user(
        self,
        role_slug: str,
        system_role: str,
        group: Group,
        password: str = "QApassword1234!",
    ) -> User:
        email = f"qa_{role_slug}_{self.ts}@qa.local"
        db = self._db
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            self._user_ids.append(existing.id)
            return existing
        user = User(
            email=email,
            display_name=f"QA {role_slug} {self.ts}",
            password_hash=hash_password(password),
            system_role=system_role,
            group_id=group.id,
            is_active=True,
            password_changed_at=datetime.utcnow(),  # marks invite as completed
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        self._user_ids.append(user.id)
        return user

    def create_system_admin(self, group: Group | None = None) -> User:
        g = group or self.create_internal_group()
        return self._make_user("sysadmin", "system_admin", g)

    def create_internal_admin(self, group: Group | None = None) -> User:
        g = group or self.create_internal_group()
        return self._make_user("intadmin", "internal_admin", g)

    def create_internal_user(self, group: Group | None = None) -> User:
        g = group or self.create_internal_group()
        return self._make_user("intuser", "internal_user", g)

    def create_external_admin(self, group: Group) -> User:
        return self._make_user("extadmin", "external_admin", group)

    def create_external_user(self, group: Group, suffix: str = "") -> User:
        role_slug = f"extuser{('_' + suffix) if suffix else ''}"
        return self._make_user(role_slug, "external_user", group)

    # ── Matters ─────────────────────────────────────────────────────────────

    def create_matter(
        self,
        owner_group: Group,
        created_by: User,
        suffix: str = "",
    ) -> Matter:
        firm = f"QA_Firm_{self.ts}" + (f"_{suffix}" if suffix else "")
        db = self._db
        matter = Matter(
            firm_name=firm,
            attorney_name=f"QA Attorney {self.ts}",
            attorney_email=f"qa_attorney_{self.ts}@qa.local",
            policyholder_name=f"QA Policyholder {self.ts}",
            loss_location="123 QA St, Test City, CA 90000",
            loss_type="total_loss",
            loss_event="QA Test Fire",
            carrier="QA Insurance Co",
            policy_number=f"QA-POL-{self.ts}",
            claim_number=f"QA-CLM-{self.ts}",
            coverage_c_limit=10000000,  # $100,000 in cents
            status="draft",
            owner_group_id=owner_group.id,
            created_by_id=created_by.id,
        )
        db.add(matter)
        db.commit()
        db.refresh(matter)
        self._matter_ids.append(matter.id)
        return matter

    def create_room(self, matter: Matter, name: str = "Living Room") -> Room:
        db = self._db
        room = Room(matter_id=matter.id, name=name)
        db.add(room)
        db.commit()
        db.refresh(room)
        return room

    # ── Matter Access ────────────────────────────────────────────────────────

    def grant_matter_access(
        self,
        user: User,
        matter: Matter,
        role: str,
        granted_by: User,
    ) -> MatterAccess:
        db = self._db
        # Remove existing grant if any (upsert)
        existing = (
            db.query(MatterAccess)
            .filter(MatterAccess.user_id == user.id, MatterAccess.matter_id == matter.id)
            .first()
        )
        if existing:
            existing.role = role
            db.commit()
            return existing
        access = MatterAccess(
            user_id=user.id,
            matter_id=matter.id,
            role=role,
            granted_by_id=granted_by.id,
        )
        db.add(access)
        db.commit()
        db.refresh(access)
        return access

    def revoke_matter_access(self, user: User, matter: Matter) -> None:
        db = self._db
        db.query(MatterAccess).filter(
            MatterAccess.user_id == user.id, MatterAccess.matter_id == matter.id
        ).delete()
        db.commit()

    # ── Teardown ─────────────────────────────────────────────────────────────

    def teardown(self) -> None:
        """Delete all data created by this factory run."""
        db = self._db
        try:
            # Delete matter access for created users or matters
            if self._user_ids:
                db.query(MatterAccess).filter(MatterAccess.user_id.in_(self._user_ids)).delete(
                    synchronize_session=False
                )
            if self._matter_ids:
                db.query(MatterAccess).filter(MatterAccess.matter_id.in_(self._matter_ids)).delete(
                    synchronize_session=False
                )

            # Delete rooms and items in created matters
            if self._matter_ids:
                from cvp.models import EvidenceFile, Item, Room

                db.query(Item).filter(Item.matter_id.in_(self._matter_ids)).delete(
                    synchronize_session=False
                )
                db.query(EvidenceFile).filter(EvidenceFile.matter_id.in_(self._matter_ids)).delete(
                    synchronize_session=False
                )
                db.query(Room).filter(Room.matter_id.in_(self._matter_ids)).delete(
                    synchronize_session=False
                )
                db.query(Matter).filter(Matter.id.in_(self._matter_ids)).delete(
                    synchronize_session=False
                )

            # Delete created users
            if self._user_ids:
                db.query(User).filter(User.id.in_(self._user_ids)).delete(synchronize_session=False)

            # Delete created external groups
            if self._group_ids:
                db.query(Group).filter(
                    Group.id.in_(self._group_ids),
                    Group.kind == "external",  # never delete the internal group
                ).delete(synchronize_session=False)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"  WARNING: teardown error: {e}")
        finally:
            db.close()

    def password_for(self, role_slug: str = "") -> str:
        """Return the default password used for all QA users."""
        return "QApassword1234!"
