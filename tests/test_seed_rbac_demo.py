"""Smoke tests for the RBAC v2 demo seeder (dev helper)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access
from claimos.models import Base
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant
from claimos.seed_rbac_demo import DEMO_GROUP_NAME, DEMO_USERS, seed_demo


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _cu(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email,
        system_role=user.system_role,
        group_id=user.group_id,
        group_kind="external",
    )


def test_seed_demo_creates_tenant_and_resolves_permissions():
    db = _db()
    result = seed_demo(db)
    users = result["users"]
    claims = result["claims"]

    assert len(users) == len(DEMO_USERS)

    # Photographer: viewer on items, contributor on evidence, cannot edit items.
    photog = users["photographer@demo.local"]
    assert db.query(RoleGrant).filter(RoleGrant.user_id == photog.id).count() == 1
    assert _check_claim_access(db, _cu(photog), claims["A"].id, "viewer", "items")
    assert not _check_claim_access(db, _cu(photog), claims["A"].id, "editor", "items")
    assert _check_claim_access(db, _cu(photog), claims["A"].id, "contributor", "evidence")

    # Photographer + override: can now edit items.
    photog_plus = users["photog-plus@demo.local"]
    assert _check_claim_access(db, _cu(photog_plus), claims["A"].id, "contributor", "items")

    # Adjuster can approve items; valuator cannot.
    adjuster = users["adjuster@demo.local"]
    valuator = users["valuator@demo.local"]
    assert _check_claim_access(db, _cu(adjuster), claims["A"].id, "approver", "items")
    assert not _check_claim_access(db, _cu(valuator), claims["A"].id, "approver", "items")

    # Claimant is confined to Claim A (single-claim isolation).
    claimant = users["claimant@demo.local"]
    assert _check_claim_access(db, _cu(claimant), claims["A"].id, "viewer", "items")
    assert not _check_claim_access(db, _cu(claimant), claims["B"].id, "viewer", "items")


def test_seed_demo_is_idempotent():
    db = _db()
    seed_demo(db)
    seed_demo(db)  # rerun wipes and recreates rather than duplicating

    assert db.query(Group).filter(Group.name == DEMO_GROUP_NAME).count() == 1
    demo_group = db.query(Group).filter(Group.name == DEMO_GROUP_NAME).first()
    assert db.query(User).filter(User.group_id == demo_group.id).count() == len(DEMO_USERS)
