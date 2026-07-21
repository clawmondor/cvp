from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access
from claimos.migrate_claim_access import migrate_external_claim_access
from claimos.models import Base, Claim
from claimos.models_access import ClaimAccess
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant


def test_external_grant_parity_after_migration():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all(
        [
            Group(id="eg", name="F", kind="external"),
            Group(id="ig", name="I", kind="internal"),
            User(
                id="eu",
                email="e@f.com",
                display_name="E",
                password_hash="x",
                system_role="external_user",
                group_id="eg",
            ),
            User(
                id="iu",
                email="i@i.com",
                display_name="I",
                password_hash="x",
                system_role="internal_user",
                group_id="ig",
            ),
            Claim(id="cA", owner_group_id="eg"),
            ClaimAccess(
                id="a1", user_id="eu", claim_id="cA", role="contributor", granted_by_id="x"
            ),
            ClaimAccess(id="a2", user_id="iu", claim_id="cA", role="viewer", granted_by_id="x"),
        ]
    )
    db.commit()

    migrate_external_claim_access(db)

    # External row converted to a grant; internal row untouched.
    assert db.query(RoleGrant).filter(RoleGrant.user_id == "eu").count() == 1
    assert db.query(ClaimAccess).filter(ClaimAccess.user_id == "eu").count() == 0
    assert db.query(ClaimAccess).filter(ClaimAccess.user_id == "iu").count() == 1

    eu = CurrentUser(
        id="eu", email="e@f.com", system_role="external_user", group_id="eg", group_kind="external"
    )
    # Parity: old contributor role still clears contributor on any object.
    assert _check_claim_access(db, eu, "cA", "contributor", "evidence") is True
    assert _check_claim_access(db, eu, "cA", "manager", "evidence") is False
