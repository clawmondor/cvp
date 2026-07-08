"""Tests for audit logging."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import claimos.models_audit  # noqa: F401
from claimos.models import Base
from claimos.models_audit import AuditLog
from claimos.services.audit import should_debounce_view


def test_audit_log_model():
    log = AuditLog(
        id="al1",
        user_id="u1",
        action="item.update",
        resource_type="item",
        resource_id="i1",
        claim_id="m1",
        detail={"old": {"price": 100}, "new": {"price": 200}},
        ip_address="127.0.0.1",
    )
    assert log.action == "item.update"
    assert log.detail_dict["old"]["price"] == 100


@pytest.fixture
def audit_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_should_debounce_view_no_prior_event(audit_db):
    """No prior event — should not debounce."""
    result = should_debounce_view(audit_db, "u1", "claim.view", "m1")
    assert result is False


def test_should_debounce_view_recent_event(audit_db):
    """Recent event exists — should debounce."""
    log = AuditLog(
        user_id="u1",
        action="claim.view",
        resource_id="m1",
        created_at=datetime.utcnow() - timedelta(minutes=1),
    )
    audit_db.add(log)
    audit_db.commit()

    result = should_debounce_view(audit_db, "u1", "claim.view", "m1")
    assert result is True


def test_should_debounce_view_old_event(audit_db):
    """Old event (>5 min) — should not debounce."""
    log = AuditLog(
        user_id="u1",
        action="claim.view",
        resource_id="m1",
        created_at=datetime.utcnow() - timedelta(minutes=10),
    )
    audit_db.add(log)
    audit_db.commit()

    result = should_debounce_view(audit_db, "u1", "claim.view", "m1")
    assert result is False


def test_get_client_ip_forwarded():
    from claimos.services.audit import get_client_ip

    class FakeRequest:
        headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
        client = None

    assert get_client_ip(FakeRequest()) == "1.2.3.4"


def test_get_client_ip_direct():
    from claimos.services.audit import get_client_ip

    class FakeClient:
        host = "9.9.9.9"

    class FakeRequest:
        headers = {}
        client = FakeClient()

    assert get_client_ip(FakeRequest()) == "9.9.9.9"
