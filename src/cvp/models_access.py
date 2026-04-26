"""Matter access control ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid


class MatterAccess(Base):
    """Per-user, per-matter permission grant."""

    __tablename__ = "matter_access"
    __table_args__ = (
        UniqueConstraint("user_id", "matter_id", name="uq_user_matter"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    matter_id: Mapped[str] = mapped_column(
        String, ForeignKey("matters.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # viewer|editor|contributor|manager
    granted_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
