import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser
from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.services.effective_permissions import (
    claim_effective_matrix,
    claim_members_access,
    group_effective_matrix,
)
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
                system_role="external_user",
                group_id="eg",
            ),
            User(
                id="adm",
                email="a@f.com",
                display_name="A",
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


def _cu(uid):
    return CurrentUser(
        id=uid, email="x@f.com", system_role="external_user", group_id="eg", group_kind="external"
    )


def test_group_matrix_from_group_scoped_grant_and_override(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={"items": "contributor"},
        granted_by_id="adm",
    )
    matrix = group_effective_matrix(db, "ph", "eg")
    assert matrix["evidence"] == "contributor"
    assert matrix["items"] == "contributor"  # override raised from viewer
    assert matrix["exports"] is None  # not in photographer profile


def test_group_matrix_excludes_claim_scoped_grants(db):
    create_grant(
        db,
        user_id="ph",
        user_role="valuator",
        scope="claims",
        claim_ids=["cA"],
        overrides={},
        granted_by_id="adm",
    )
    matrix = group_effective_matrix(db, "ph", "eg")
    assert matrix["items"] is None  # claim-scoped grant does not affect the group matrix


def test_claim_matrix_includes_claim_scoped(db):
    create_grant(
        db,
        user_id="ph",
        user_role="valuator",
        scope="claims",
        claim_ids=["cA"],
        overrides={},
        granted_by_id="adm",
    )
    m_a = claim_effective_matrix(db, _cu("ph"), "cA")
    m_b = claim_effective_matrix(db, _cu("ph"), "cB")
    assert m_a["items"] == "contributor"
    assert m_b["items"] is None  # not granted on cB


def test_claim_members_access_lists_only_members_with_access(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    rows = claim_members_access(db, "eg", "cA")
    ids = {u.id for u, _m in rows}
    assert "ph" in ids
    # adm (external_admin) owns the claim → has access too
    assert "adm" in ids
