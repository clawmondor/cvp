"""Feedback ORM models: top-level feedback items and comment threads."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid

ALLOWED_STATUSES = ("pending", "reviewing", "backlog", "canceled", "done")


class Feedback(Base):
    """A single piece of feedback from a user, with status and a comment thread."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALLOWED_STATUSES)})",
            name="ck_feedback_status",
        ),
        Index("ix_feedback_author_created", "author_user_id", "created_at"),
        Index("ix_feedback_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    author_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    author_group_id: Mapped[str] = mapped_column(String, ForeignKey("groups.id"), nullable=False)
    page_url: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_changed_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    last_admin_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_author_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FeedbackComment(Base):
    """A comment posted on a feedback thread."""

    __tablename__ = "feedback_comments"
    __table_args__ = (Index("ix_feedback_comments_feedback_created", "feedback_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    feedback_id: Mapped[str] = mapped_column(String, ForeignKey("feedback.id"), nullable=False)
    author_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
