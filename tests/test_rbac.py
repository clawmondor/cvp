"""Tests for RBAC models and dependencies."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import (
    ROLE_HIERARCHY,
    CurrentUser,
    _check_claim_access,
)
from claimos.models import Base, Claim
from claimos.models_access import ClaimAccess
from claimos.models_auth import Group, User


def test_claim_access_model_fields():
    ma = ClaimAccess(
        id="ma1",
        user_id="u1",
        claim_id="m1",
        role="editor",
        granted_by_id="u2",
    )
    assert ma.user_id == "u1"
    assert ma.claim_id == "m1"
    assert ma.role == "editor"
    assert ma.granted_by_id == "u2"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded_rbac_db(db_session):
    """Seed with groups, users, a claim, and access grants."""
    int_group = Group(id="ig", name="Internal", kind="internal")
    ext_group = Group(id="eg", name="External", kind="external")
    db_session.add_all([int_group, ext_group])

    sys_admin = User(
        id="sa",
        email="sa@test.com",
        display_name="SysAdmin",
        password_hash="x",
        system_role="system_admin",
        group_id="ig",
    )
    int_admin = User(
        id="ia",
        email="ia@test.com",
        display_name="IntAdmin",
        password_hash="x",
        system_role="internal_admin",
        group_id="ig",
    )
    int_user = User(
        id="iu",
        email="iu@test.com",
        display_name="IntUser",
        password_hash="x",
        system_role="internal_user",
        group_id="ig",
    )
    ext_admin = User(
        id="ea",
        email="ea@test.com",
        display_name="ExtAdmin",
        password_hash="x",
        system_role="external_admin",
        group_id="eg",
    )
    ext_user = User(
        id="eu",
        email="eu@test.com",
        display_name="ExtUser",
        password_hash="x",
        system_role="external_user",
        group_id="eg",
    )
    db_session.add_all([sys_admin, int_admin, int_user, ext_admin, ext_user])

    claim = Claim(id="m1", owner_group_id="ig", created_by_id="ia")
    db_session.add(claim)

    # Grant ext_user viewer access
    access = ClaimAccess(id="a1", user_id="eu", claim_id="m1", role="viewer", granted_by_id="ia")
    db_session.add(access)
    db_session.commit()
    return db_session


def test_role_hierarchy_ordering():
    assert ROLE_HIERARCHY["viewer"] < ROLE_HIERARCHY["editor"]
    assert ROLE_HIERARCHY["editor"] < ROLE_HIERARCHY["contributor"]
    assert ROLE_HIERARCHY["contributor"] < ROLE_HIERARCHY["manager"]


def test_system_admin_has_implicit_manager(seeded_rbac_db):
    user = CurrentUser(
        id="sa",
        email="sa@test.com",
        system_role="system_admin",
        group_id="ig",
        group_kind="internal",
    )
    result = _check_claim_access(seeded_rbac_db, user, "m1", "manager")
    assert result is True


def test_internal_admin_manager_on_own_group_claim(seeded_rbac_db):
    user = CurrentUser(
        id="ia",
        email="ia@test.com",
        system_role="internal_admin",
        group_id="ig",
        group_kind="internal",
    )
    result = _check_claim_access(seeded_rbac_db, user, "m1", "manager")
    assert result is True


def test_ext_user_has_viewer_access(seeded_rbac_db):
    user = CurrentUser(
        id="eu",
        email="eu@test.com",
        system_role="external_user",
        group_id="eg",
        group_kind="external",
    )
    result = _check_claim_access(seeded_rbac_db, user, "m1", "viewer")
    assert result is True


def test_ext_user_denied_editor_access(seeded_rbac_db):
    user = CurrentUser(
        id="eu",
        email="eu@test.com",
        system_role="external_user",
        group_id="eg",
        group_kind="external",
    )
    result = _check_claim_access(seeded_rbac_db, user, "m1", "editor")
    assert result is False


def test_no_access_for_ungranted_user(seeded_rbac_db):
    user = CurrentUser(
        id="ea",
        email="ea@test.com",
        system_role="external_admin",
        group_id="eg",
        group_kind="external",
    )
    # ext_admin has no claim_access row and claim is owned by internal group
    result = _check_claim_access(seeded_rbac_db, user, "m1", "viewer")
    assert result is False
