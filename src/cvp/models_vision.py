"""Admin-curated catalog of vision models exposed in the per-scan picker."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid


class VisionModel(Base):
    __tablename__ = "vision_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    adapter: Mapped[str] = mapped_column(String, nullable=False, default="none")
    prompt_image_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_bbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
