"""Dev-only helper: seed an RBAC v2 demo tenant for manual permission testing.

Creates one external "firm" group, one external user per interesting User Role,
two claims owned by the firm, and a sample item + evidence file, then assigns the
matching role grants. Prints each user's id so you can drop it straight into
`AUTO_LOGIN_USER_ID` (with `ENVIRONMENT=dev`) and browse as that user.

Entry point: ``uv run seed-rbac-demo``

External users only — RBAC v2 governs the external (firm) surface; internal users
keep the legacy claim_access model. Re-running wipes and recreates the demo
tenant, so it is safe to run repeatedly. Refuses to run against a production
environment so it can never pollute real data.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from claimos.config import settings
from claimos.db import SessionLocal
from claimos.models import Category, Claim, EvidenceFile, Item
from claimos.models_auth import Group, User
from claimos.models_grants import RoleGrant
from claimos.services.grants import create_grant

DEMO_GROUP_NAME = "Demo Firm (RBAC v2)"

# (email, display_name, system_role, user_role, scope, claim_keys, overrides)
# user_role=None marks the external_admin (Lawyer): owns the firm's claims, so
# it resolves to manager implicitly and needs no grant.
DEMO_USERS: list[tuple[str, str, str, str | None, str | None, list[str] | None, dict[str, str]]] = [
    ("lawyer@demo.local", "Dana Lawyer", "external_admin", None, None, None, {}),
    (
        "photographer@demo.local",
        "Pat Photographer",
        "external_user",
        "photographer",
        "group",
        None,
        {},
    ),
    (
        "photog-plus@demo.local",
        "Robin Photographer+",
        "external_user",
        "photographer",
        "group",
        None,
        {"items": "contributor"},
    ),
    ("valuator@demo.local", "Val Valuator", "external_user", "valuator", "group", None, {}),
    ("adjuster@demo.local", "Alex Adjuster", "external_user", "adjuster", "group", None, {}),
    ("claimant@demo.local", "Cameron Claimant", "external_user", "claimant", "claims", ["A"], {}),
]


def _wipe_demo(db: Session) -> None:
    """Delete a previously-seeded demo tenant (idempotent re-runs)."""
    group = db.query(Group).filter(Group.name == DEMO_GROUP_NAME).first()
    if group is None:
        return

    user_ids = [u.id for u in db.query(User).filter(User.group_id == group.id).all()]
    if user_ids:
        # Delete grants first (cascades role_grant_claims / role_grant_overrides).
        for grant in db.query(RoleGrant).filter(RoleGrant.user_id.in_(user_ids)).all():
            db.delete(grant)
    # Delete claims via ORM so items / evidence / rooms cascade.
    for claim in db.query(Claim).filter(Claim.owner_group_id == group.id).all():
        db.delete(claim)
    db.flush()
    for user in db.query(User).filter(User.group_id == group.id).all():
        db.delete(user)
    db.delete(group)
    db.commit()


def seed_demo(db: Session) -> dict:
    """Create the demo tenant and its grants. Returns {group, users, claims}."""
    _wipe_demo(db)

    # Items need a category. Reuse a seeded one if present, else create a stub so
    # this helper is self-contained even before `uv run seed`.
    category = db.query(Category).order_by(Category.id).first()
    if category is None:
        category = Category(name="Demo Category", acv_floor_pct=0.2, useful_life_years=10)
        db.add(category)
        db.flush()

    group = Group(name=DEMO_GROUP_NAME, kind="external")
    db.add(group)
    db.flush()

    users: dict[str, User] = {}
    for email, name, system_role, *_rest in DEMO_USERS:
        user = User(
            email=email,
            display_name=name,
            password_hash="__demo_no_login__",  # AUTO_LOGIN_USER_ID bypasses passwords
            system_role=system_role,
            group_id=group.id,
        )
        db.add(user)
        db.flush()
        users[email] = user

    lawyer = users["lawyer@demo.local"]

    # Two claims owned by the firm. Claim B stays out of the claimant's grant so
    # you can verify single-claim isolation (claimant → 403 on Claim B).
    claim_a = Claim(
        owner_group_id=group.id,
        created_by_id=lawyer.id,
        firm_name=DEMO_GROUP_NAME,
        policyholder_name="Demo Policyholder A",
        loss_event="Demo Fire",
        status="draft",
    )
    claim_b = Claim(
        owner_group_id=group.id,
        created_by_id=lawyer.id,
        firm_name=DEMO_GROUP_NAME,
        policyholder_name="Demo Policyholder B",
        loss_event="Demo Fire",
        status="draft",
    )
    db.add_all([claim_a, claim_b])
    db.flush()
    claims = {"A": claim_a, "B": claim_b}

    # A sample item + evidence on Claim A to exercise item/evidence permissions.
    db.add(
        Item(
            claim_id=claim_a.id,
            category_id=category.id,
            description="Demo sofa",
            quantity=1,
            condition="average",
        )
    )
    db.add(
        EvidenceFile(
            claim_id=claim_a.id,
            filename="demo.jpg",
            stored_path="demo/placeholder.jpg",  # no real file; row is enough for RBAC
            mime_type="image/jpeg",
            kind="photo",
        )
    )
    db.flush()

    # Grants. The Lawyer (external_admin) owns the claims → implicit manager, no grant.
    for email, _name, _system_role, user_role, scope, claim_keys, overrides in DEMO_USERS:
        if user_role is None:
            continue
        claim_ids = [claims[key].id for key in (claim_keys or [])]
        create_grant(
            db,
            user_id=users[email].id,
            user_role=user_role,
            scope=scope,  # type: ignore[arg-type]
            claim_ids=claim_ids,
            overrides=overrides,
            granted_by_id=lawyer.id,
        )

    db.commit()
    return {"group": group, "users": users, "claims": claims}


def _print_summary(result: dict) -> None:
    users = result["users"]
    claims = result["claims"]
    print("\nRBAC v2 demo tenant seeded.\n")
    print(f"Firm group : {result['group'].name} (external)")
    print(f"Claim A    : {claims['A'].id}")
    print(f"Claim B    : {claims['B'].id}\n")
    print("Users — set AUTO_LOGIN_USER_ID to one of these ids, then restart `uv run dev`:")
    for email, _name, _system_role, user_role, scope, claim_keys, overrides in DEMO_USERS:
        user = users[email]
        if user_role is None:
            desc = "external_admin (owns claims → manager)"
        else:
            desc = f"{user_role} [{scope}"
            if claim_keys:
                desc += ":" + ",".join(claim_keys)
            desc += "]"
            if overrides:
                desc += f" +override {overrides}"
        print(f"  {user.id}  {email:26} {desc}")
    print("\nExpected behavior to verify in the UI:")
    print("  photographer    : upload evidence OK, edit item DENIED, confirm DENIED")
    print("  photog-plus     : same, but edit item OK (items→contributor override)")
    print("  valuator        : edit item OK, export DENIED, confirm DENIED")
    print("  adjuster        : confirm/approve item OK, export OK")
    print("  claimant        : Claim A read-only OK, Claim B → 403 (single-claim)")
    print("  lawyer          : full access to both claims\n")


def main() -> None:
    if settings.environment.strip().lower().startswith("prod"):
        print(
            "seed-rbac-demo: refusing to run — this looks like a production "
            f"environment (ENVIRONMENT={settings.environment!r}). "
            "Set ENVIRONMENT=dev (or development) for local testing."
        )
        raise SystemExit(1)

    db = SessionLocal()
    try:
        result = seed_demo(db)
        _print_summary(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
