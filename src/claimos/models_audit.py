"""Audit log ORM model."""

import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from claimos.models import Base, _new_uuid


class AuditLog(Base):
    """Immutable audit trail entry."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_claim_id", "claim_id"),
        Index("ix_audit_logs_action", "action"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[str] = mapped_column(String, nullable=True, default="")
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    claim_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # stored as JSON
    ip_address: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __init__(self, **kwargs: object) -> None:
        if "detail" in kwargs and isinstance(kwargs["detail"], dict):
            kwargs["detail"] = json.dumps(kwargs["detail"])
        super().__init__(**kwargs)

    @property
    def detail_dict(self) -> dict:
        if self.detail and isinstance(self.detail, str):
            return json.loads(self.detail)
        if isinstance(self.detail, dict):
            return self.detail
        return {}
