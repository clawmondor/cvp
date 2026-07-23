"""I2: PDF export is an EXPORT action (same class as CSV), not an on-screen
preview, so `routers/exports.py::export_pdf` must require the `exports` object
type, not `reports`. The on-screen preview route (`claims.py::claim_preview`)
stays tagged `reports`.

These tests use the Claimant User Role, which is deliberately asymmetric:
`reports: viewer` (so on-screen preview works) but NO `exports` entry at all
(default-deny). That asymmetry lets a single fixture distinguish the two tags:
if `export_pdf` were still gated on `reports`, a Claimant would incorrectly
clear it (they have viewer+ on reports); gated on `exports`, they correctly get
denied (no grant on exports at all).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.dependencies import CurrentUser, _check_claim_access
from claimos.models import Base, Claim
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant, RoleGrantClaim


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_claimant(db):
    db.add_all(
        [
            Group(id="eg", name="Firm", kind="external"),
            User(
                id="claimant1",
                email="claimant@test.com",
                display_name="Claimant",
                password_hash="x",
                system_role="external_user",
                group_id="eg",
            ),
            Claim(id="c1", owner_group_id="eg", nickname="Claim One"),
        ]
    )
    grant = RoleGrant(
        id="g1",
        user_id="claimant1",
        group_id="eg",
        user_role="claimant",
        scope="claims",
        granted_by_id="admin",
    )
    db.add(grant)
    db.add(RoleGrantClaim(id="rgc1", grant_id="g1", claim_id="c1"))
    db.commit()


def test_pdf_export_object_type_is_exports_not_reports():
    """The dependency `require_claim_role("contributor", "exports")` used by
    export_pdf must deny a Claimant (no `exports` grant) even though Claimant
    clears `reports` at viewer. This is the exact scenario that would have
    passed incorrectly if export_pdf were still tagged "reports"."""
    db = _make_db()
    _seed_claimant(db)
    user = CurrentUser(
        id="claimant1",
        email="claimant@test.com",
        system_role="external_user",
        group_id="eg",
        group_kind="external",
    )

    # Claimant clears the on-screen preview route's tag (reports, viewer).
    assert _check_claim_access(db, user, "c1", "viewer", "reports") is True

    # Claimant must NOT clear the export route's tag (exports, contributor) —
    # this is what export_pdf now requires. Default-deny: no "exports" entry
    # in the Claimant profile at all.
    assert _check_claim_access(db, user, "c1", "contributor", "exports") is False


def test_export_pdf_route_is_tagged_exports():
    """Direct regression pin on the route's dependency object_type: parses the
    default value baked into the route's Depends(...) closure via its FastAPI
    dependant, so a future edit that reintroduces the "reports" tag fails loudly
    here instead of only being caught by the behavioral test above."""
    from claimos.main import app

    route = next(
        r
        for r in app.routes
        if getattr(r, "path", None) == "/api/claims/{claim_id}/exports/pdf"
        and "POST" in getattr(r, "methods", set())
    )
    # The `user` param's dependency is `require_claim_role("contributor", "exports")`,
    # a closure — inspect its defaults/closure cells for the bound object_type.
    user_dependant = next(d for d in route.dependant.dependencies if d.name == "user")
    closure_cells = user_dependant.call.__closure__
    freevars = user_dependant.call.__code__.co_freevars
    bound = dict(zip(freevars, (c.cell_contents for c in closure_cells)))
    assert bound["object_type"] == "exports"
    assert bound["minimum_role"] == "contributor"
