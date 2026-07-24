import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access
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
            Group(id="eg", name="F", kind="external"),
            User(
                id="ph",
                email="p@f.com",
                display_name="P",
                password_hash="x",
                system_role="external_user",
                group_id="eg",
            ),
            User(
                id="adj",
                email="j@f.com",
                display_name="J",
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
            Claim(id="cA", owner_group_id="eg", nickname="Claim A"),
        ]
    )
    s.commit()
    yield s
    s.close()


def _cu(uid):
    return CurrentUser(
        id=uid, email="x@f.com", system_role="external_user", group_id="eg", group_kind="external"
    )


def test_photographer_can_create_rooms_and_item_groups(db):
    create_grant(
        db,
        user_id="ph",
        user_role="photographer",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "rooms") is True
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "item_groups") is True
    # ...but cannot export (not in profile) or delete rooms (needs manager)
    assert _check_claim_access(db, _cu("ph"), "cA", "contributor", "exports") is False
    assert _check_claim_access(db, _cu("ph"), "cA", "manager", "rooms") is False


def test_adjuster_can_export_and_view_users_but_not_manage_users(db):
    create_grant(
        db,
        user_id="adj",
        user_role="adjuster",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    assert _check_claim_access(db, _cu("adj"), "cA", "contributor", "exports") is True
    assert _check_claim_access(db, _cu("adj"), "cA", "contributor", "users") is True
    assert _check_claim_access(db, _cu("adj"), "cA", "manager", "users") is False
