import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrantOverride
from claimos.services.grants import (
    GrantValidationError,
    add_override,
    create_grant,
    list_grants,
    remove_override,
    revoke_grant,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="Firm", kind="external"),
            Group(id="ig", name="Int", kind="internal"),
            Group(id="og", name="Other Firm", kind="external"),
            User(
                id="ph",
                email="p@f.com",
                display_name="P",
                password_hash="x",
                system_role="external_user",
                group_id="eg",
            ),
            User(
                id="adm",
                email="a@f.com",
                display_name="A",
                password_hash="x",
                system_role="external_admin",
                group_id="eg",
            ),
            Claim(id="cA", owner_group_id="eg"),
            Claim(id="cB", owner_group_id="eg"),
            Claim(id="cF", owner_group_id="og"),
        ]
    )
    s.commit()
    yield s
    s.close()


def test_create_group_scoped_grant(db):
    g = create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    assert g.scope == "group"
    assert g.claims == []
    assert g.group_id == "eg"  # derived from grantee's group


def test_create_claims_scoped_grant_with_override(db):
    g = create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="claims",
        claim_ids=["cA"],
        overrides={"items": "contributor"},
        granted_by_id="adm",
    )
    assert {c.claim_id for c in g.claims} == {"cA"}
    assert {(o.object_type, o.role) for o in g.overrides} == {("items", "contributor")}


def test_claims_scope_requires_at_least_one_claim(db):
    with pytest.raises(GrantValidationError):
        create_grant(
            db,
            user_id="ph",
            user_role="photographer",
            scope="claims",
            claim_ids=[],
            overrides={},
            granted_by_id="adm",
        )


def test_create_claims_scoped_grant_rejects_foreign_claim(db):
    """Cross-firm privilege escalation: a claim owned by a different group must
    be rejected regardless of caller — this is the root-cause guard.
    """
    with pytest.raises(GrantValidationError):
        create_grant(
            db,
            user_id="ph",
            user_role="valuator",
            scope="claims",
            claim_ids=["cF"],
            overrides={},
            granted_by_id="adm",
        )


def test_create_claims_scoped_grant_accepts_own_firm_claim(db):
    g = create_grant(
        db,
        user_id="ph",
        user_role="valuator",
        scope="claims",
        claim_ids=["cA"],
        overrides={},
        granted_by_id="adm",
    )
    assert {c.claim_id for c in g.claims} == {"cA"}


def test_claimant_must_be_single_claim(db):
    with pytest.raises(GrantValidationError):
        create_grant(
            db,
            user_id="ph",
            user_role="claimant",
            scope="group",
            claim_ids=[],
            overrides={},
            granted_by_id="adm",
        )
    with pytest.raises(GrantValidationError):
        create_grant(
            db,
            user_id="ph",
            user_role="claimant",
            scope="claims",
            claim_ids=["cA", "cB"],
            overrides={},
            granted_by_id="adm",
        )
    ok = create_grant(
        db,
        user_id="ph",
        user_role="claimant",
        scope="claims",
        claim_ids=["cA"],
        overrides={},
        granted_by_id="adm",
    )
    assert ok.user_role == "claimant"


def test_unknown_role_rejected(db):
    with pytest.raises(GrantValidationError):
        create_grant(
            db,
            user_id="ph",
            user_role="wizard",
            scope="group",
            claim_ids=[],
            overrides={},
            granted_by_id="adm",
        )


def test_list_and_revoke(db):
    g = create_grant(
        db,
        user_id="ph",
        user_role="valuator",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    assert [x.id for x in list_grants(db, "ph")] == [g.id]
    revoke_grant(db, g.id)
    assert list_grants(db, "ph") == []


def test_add_and_remove_override(db):
    g = create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    ov = add_override(db, g.id, "items", "contributor")
    assert ov.object_type == "items" and ov.role == "contributor"
    # upsert: same object updates, not duplicates
    add_override(db, g.id, "items", "approver")
    rows = db.query(RoleGrantOverride).filter(RoleGrantOverride.grant_id == g.id).all()
    assert len(rows) == 1 and rows[0].role == "approver"

    remove_override(db, g.id, "items")
    assert db.query(RoleGrantOverride).filter(RoleGrantOverride.grant_id == g.id).count() == 0


def test_override_validation(db):
    g = create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    with pytest.raises(GrantValidationError):
        add_override(db, g.id, "not_an_object", "contributor")
    with pytest.raises(GrantValidationError):
        add_override(db, g.id, "items", "not_a_role")
    with pytest.raises(GrantValidationError):
        add_override(db, "missing-grant", "items", "contributor")
