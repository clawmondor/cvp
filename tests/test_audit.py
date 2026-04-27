"""Tests for audit logging."""

from cvp.models_audit import AuditLog
from cvp.services.audit import should_debounce_view


def test_audit_log_model():
    log = AuditLog(
        id="al1",
        user_id="u1",
        action="item.update",
        resource_type="item",
        resource_id="i1",
        matter_id="m1",
        detail={"old": {"price": 100}, "new": {"price": 200}},
        ip_address="127.0.0.1",
    )
    assert log.action == "item.update"
    assert log.detail_dict["old"]["price"] == 100
