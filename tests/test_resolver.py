import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access, _external_effective_role
from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.services.grants import create_grant


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="Firm", kind="external"),
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
        ]
    )
    s.commit()
    yield s
    s.close()


def _cu(uid, role="external_user"):
    return CurrentUser(
        id=uid, email="x@f.com", system_role=role, group_id="eg", group_kind="external"
    )


def test_group_scope_covers_all_group_claims(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    assert _external_effective_role(db, _cu("ph"), "cA", "evidence") == "contributor"
    assert _external_effective_role(db, _cu("ph"), "cB", "evidence") == "contributor"
    assert _external_effective_role(db, _cu("ph"), "cA", "items") == "viewer"
    assert _external_effective_role(db, _cu("ph"), "cA", "exports") is None


def test_claims_scope_only_covers_listed_claim(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="claims",
        claim_ids=["cA"],
        overrides={},
        granted_by_id="adm",
    )
    assert _external_effective_role(db, _cu("ph"), "cA", "evidence") == "contributor"
    assert _external_effective_role(db, _cu("ph"), "cB", "evidence") is None


def test_override_raises_object_level(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={"items": "contributor"},
        granted_by_id="adm",
    )
    assert _external_effective_role(db, _cu("ph"), "cA", "items") == "contributor"


def test_max_across_multiple_grants(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    create_grant(
        db,
        user_id="ph",
        user_role="valuator",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    # photographer=viewer on items, valuator=contributor on items -> contributor
    assert _external_effective_role(db, _cu("ph"), "cA", "items") == "contributor"


def test_check_claim_access_uses_object_type_for_external(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    # contributor on evidence clears a contributor minimum
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "evidence") is True
    # viewer on items does NOT clear an editor minimum
    assert _check_claim_access(db, _cu("ph"), "cA", "editor", "items") is False


def test_external_admin_owns_claim_is_manager(db):
    # No grant needed; external_admin whose group owns the claim => manager-level.
    assert _check_claim_access(db, _cu("adm", "external_admin"), "cA", "manager", "items") is True
