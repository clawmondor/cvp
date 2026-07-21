from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.models import Base
from claimos.models_grants import RoleGrant, RoleGrantClaim, RoleGrantOverride


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_grant_with_claims_and_overrides_persist():
    db = _session()
    grant = RoleGrant(
        id="grant1",
        user_id="u1",
        group_id="g1",
        user_role="photographer",
        scope="claims",
        granted_by_id="admin1",
    )
    db.add(grant)
    db.add(RoleGrantClaim(id="rgc1", grant_id="grant1", claim_id="claimA"))
    db.add(RoleGrantOverride(id="rgo1", grant_id="grant1", object_type="items", role="contributor"))
    db.commit()

    loaded = db.get(RoleGrant, "grant1")
    assert loaded.scope == "claims"
    assert loaded.user_role == "photographer"
    assert [c.claim_id for c in loaded.claims] == ["claimA"]
    assert loaded.overrides[0].object_type == "items"
    assert loaded.overrides[0].role == "contributor"


def test_group_scoped_grant_has_no_claim_rows():
    db = _session()
    grant = RoleGrant(
        id="grant2",
        user_id="u2",
        group_id="g1",
        user_role="adjuster",
        scope="group",
        granted_by_id="admin1",
    )
    db.add(grant)
    db.commit()
    assert db.get(RoleGrant, "grant2").claims == []
