"""Audit logging service — write, debounce, query."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from cvp.db import SessionLocal
from cvp.models_audit import AuditLog

VIEW_DEBOUNCE_MINUTES = 5


def write_audit_log(
    *,
    user_id: str | None,
    action: str,
    resource_type: str = "",
    resource_id: str | None = None,
    matter_id: str | None = None,
    detail: dict | None = None,
    ip_address: str = "",
) -> None:
    """Write an audit log entry. Intended to be called as a BackgroundTask."""
    db = SessionLocal()
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            matter_id=matter_id,
            detail=detail,
            ip_address=ip_address,
        )
        db.add(log)
        db.commit()
    finally:
        db.close()


def should_debounce_view(
    db: Session,
    user_id: str,
    action: str,
    resource_id: str,
) -> bool:
    """Return True if a view event should be skipped (same user+resource within 5 min)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=VIEW_DEBOUNCE_MINUTES)
    existing = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == user_id,
            AuditLog.action == action,
            AuditLog.resource_id == resource_id,
            AuditLog.created_at >= cutoff,
        )
        .first()
    )
    return existing is not None


def get_client_ip(request: object) -> str:
    """Extract client IP from request, checking X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""
