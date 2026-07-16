"""Approver gate on item confirmation. Uses the shared app test client pattern."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access
from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.services.grants import create_grant


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all(
        [
            Group(id="eg", name="F", kind="external"),
            User(
                id="val",
                email="v@f.com",
                display_name="V",
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
        ]
    )
    s.commit()
    return s


def _cu(uid):
    return CurrentUser(
        id=uid, email="x@f.com", system_role="external_user", group_id="eg", group_kind="external"
    )


def test_valuator_cannot_approve_but_can_edit():
    db = _db()
    create_grant(
        db,
        user_id="val",
        user_role="valuator",
        scope="group",
        claim_ids=[],
        overrides={},
        granted_by_id="adm",
    )
    # contributor on items clears editor, but not approver
    assert _check_claim_access(db, _cu("val"), "cA", "editor", "items") is True
    assert _check_claim_access(db, _cu("val"), "cA", "approver", "items") is False


def test_valuator_with_items_approver_override_can_approve():
    db = _db()
    create_grant(
        db,
        user_id="val",
        user_role="valuator",
        scope="group",
        claim_ids=[],
        overrides={"items": "approver"},
        granted_by_id="adm",
    )
    assert _check_claim_access(db, _cu("val"), "cA", "approver", "items") is True
