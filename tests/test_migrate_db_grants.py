"""C1: `migrate-db` must convert freshly-copied external `claim_access` rows into
`role_grants` as its FINAL step (after the parity check), or external users are
locked out post-cutover with an inert `claim_access` row.

These tests build a target DB in the POST-COPY state (schema + rows already
present, as if `migrate()` had just run) and exercise `convert_external_access`
directly — the same helper `main()` calls after `raise_on_parity_mismatch`
succeeds. Without `convert_external_access` (and its wiring into `main()`), the
external user's `claim_access` row would stay inert and `_check_claim_access`
would deny them; with it, the row becomes a `role_grant` (+ `role_grant_claim`)
and access resolves correctly.
"""

import sqlalchemy as sa

from claimos.dependencies import CurrentUser, _check_claim_access
from claimos.migrate_db import convert_external_access
from claimos.models import Base, Claim
from claimos.models_access import ClaimAccess
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant


def _make_post_copy_target_db(url: str) -> None:
    """Target DB in the state migrate-db leaves it in right after `migrate()`:
    full ClaimOS schema, plus an external user's and an internal user's
    claim_access row (as if just copied from legacy matter_access)."""
    engine = sa.create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(bind=engine) as db:
        db.add_all(
            [
                Group(id="eg", name="External Firm", kind="external"),
                Group(id="ig", name="Internal", kind="internal"),
                User(
                    id="eu",
                    email="eu@ext.com",
                    display_name="Ext User",
                    password_hash="x",
                    system_role="external_user",
                    group_id="eg",
                ),
                User(
                    id="iu",
                    email="iu@int.com",
                    display_name="Int User",
                    password_hash="x",
                    system_role="internal_user",
                    group_id="ig",
                ),
                Claim(id="c1", owner_group_id="ig", nickname="Claim One"),
                ClaimAccess(
                    id="ca-ext",
                    user_id="eu",
                    claim_id="c1",
                    role="contributor",
                    granted_by_id="seed",
                ),
                ClaimAccess(
                    id="ca-int",
                    user_id="iu",
                    claim_id="c1",
                    role="viewer",
                    granted_by_id="seed",
                ),
            ]
        )
        db.commit()


def test_convert_external_access_converts_post_copy_external_row(tmp_path):
    """Reproduces the C1 ordering bug's fix: a claim_access row for an external
    user that was JUST COPIED by migrate-db (post-parity-check state) is
    converted into a role_grant, and the external user's access now resolves
    via _check_claim_access (the resolver external users actually use)."""
    tgt = f"sqlite:///{tmp_path / 'claimos.db'}"
    _make_post_copy_target_db(tgt)

    converted = convert_external_access(tgt)
    assert converted == 1

    engine = sa.create_engine(tgt)
    from sqlalchemy.orm import Session

    with Session(bind=engine) as db:
        # External row converted to a role_grant and removed from claim_access.
        assert db.query(RoleGrant).filter(RoleGrant.user_id == "eu").count() == 1
        assert db.query(ClaimAccess).filter(ClaimAccess.user_id == "eu").count() == 0

        # Internal row is left intact — internal users still resolve via
        # claim_access, not role_grants.
        internal_row = db.query(ClaimAccess).filter(ClaimAccess.user_id == "iu").first()
        assert internal_row is not None
        assert internal_row.role == "viewer"

        # The external user's access now resolves through the RBAC v2 resolver
        # that require_claim_role actually uses for external users.
        eu = CurrentUser(
            id="eu",
            email="eu@ext.com",
            system_role="external_user",
            group_id="eg",
            group_kind="external",
        )
        assert _check_claim_access(db, eu, "c1", "contributor", "evidence") is True
        assert _check_claim_access(db, eu, "c1", "manager", "evidence") is False

        # Internal user's access is untouched and still resolves via the legacy
        # claim_access path.
        iu = CurrentUser(
            id="iu",
            email="iu@int.com",
            system_role="internal_user",
            group_id="ig",
            group_kind="internal",
        )
        assert _check_claim_access(db, iu, "c1", "viewer", "evidence") is True
        assert _check_claim_access(db, iu, "c1", "contributor", "evidence") is False


def test_convert_external_access_is_zero_when_no_external_rows(tmp_path):
    """Sanity check: an all-internal target converts 0 rows (matches the
    alembic-upgrade-only in-place-update path, where there's no migrate-db)."""
    tgt = f"sqlite:///{tmp_path / 'claimos.db'}"
    engine = sa.create_engine(tgt)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(bind=engine) as db:
        db.add_all(
            [
                Group(id="ig", name="Internal", kind="internal"),
                User(
                    id="iu",
                    email="iu@int.com",
                    display_name="Int User",
                    password_hash="x",
                    system_role="internal_user",
                    group_id="ig",
                ),
                Claim(id="c1", owner_group_id="ig", nickname="Claim One"),
                ClaimAccess(
                    id="ca-int", user_id="iu", claim_id="c1", role="viewer", granted_by_id="seed"
                ),
            ]
        )
        db.commit()

    assert convert_external_access(tgt) == 0
