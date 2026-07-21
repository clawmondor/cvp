"""Approver gate on item confirmation. Uses the shared app test client pattern."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimos.db import SessionLocal as RealSessionLocal
from claimos.db import engine as real_engine
from claimos.dependencies import CurrentUser, _check_claim_access, get_current_user
from claimos.main import app
from claimos.models import Base, Category, Claim, Item
from claimos.models_audit import AuditLog
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


# ---------------------------------------------------------------------------
# Audit logging on confirm / unconfirm — POST /api/items/{item_id}/confirm
# and /unconfirm must each write an audit.log entry (restored after the
# toggle-confirm -> confirm/unconfirm split dropped it).
# ---------------------------------------------------------------------------

APPROVER_ID = "approver-audit"
CLAIM_ID = "claim-audit-confirm"


@pytest.fixture
def approver_client():
    """Full app TestClient with a system_admin user (implicit approver on
    everything) so confirm/unconfirm requests pass the role gate. Seeds a
    claim, category, and item directly into the shared real DB, since
    require_claim_role and write_audit_log both use SessionLocal() (the real
    engine) rather than a test override.
    """
    Base.metadata.create_all(real_engine)
    db = RealSessionLocal()
    item_id = f"item-{uuid.uuid4().hex[:8]}"
    try:
        db.merge(Claim(id=CLAIM_ID, policyholder_name="P", loss_type="total_loss"))
        db.merge(
            Category(id=999, name="Audit Test Category", useful_life_years=5, acv_floor_pct=0.2)
        )
        db.add(
            Item(
                id=item_id,
                claim_id=CLAIM_ID,
                category_id=999,
                line_number=1,
                description="audit test item",
                quantity=1,
                age_years=0.0,
                condition="average",
                rcv_unit_cents=1000,
                confirmed=False,
            )
        )
        db.commit()
    finally:
        db.close()

    async def mock_admin():
        return CurrentUser(
            id=APPROVER_ID,
            email="approver@test.com",
            system_role="system_admin",
            group_id=None,
            group_kind="internal",
        )

    app.dependency_overrides[get_current_user] = mock_admin
    with TestClient(app) as c:
        yield c, item_id
    app.dependency_overrides.clear()


def _latest_audit_action(action: str, resource_id: str) -> AuditLog | None:
    real_db = RealSessionLocal()
    try:
        return (
            real_db.query(AuditLog)
            .filter_by(action=action, resource_id=resource_id)
            .order_by(AuditLog.id.desc())
            .first()
        )
    finally:
        real_db.close()


def test_confirm_item_writes_audit_log(approver_client):
    client, item_id = approver_client
    resp = client.post(f"/api/items/{item_id}/confirm")
    assert resp.status_code == 200

    log = _latest_audit_action("item.confirm", item_id)
    assert log is not None
    assert log.user_id == APPROVER_ID
    assert log.claim_id == CLAIM_ID


def test_unconfirm_item_writes_audit_log(approver_client):
    client, item_id = approver_client
    client.post(f"/api/items/{item_id}/confirm")
    resp = client.post(f"/api/items/{item_id}/unconfirm")
    assert resp.status_code == 200

    log = _latest_audit_action("item.unconfirm", item_id)
    assert log is not None
    assert log.user_id == APPROVER_ID
    assert log.claim_id == CLAIM_ID
