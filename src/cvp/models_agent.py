"""ORM models for external AI agents: AgentKey and AiRecommendation."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base, _new_uuid


class AgentKey(Base):
    """A revocable API key identifying an external AI agent principal."""

    __tablename__ = "agent_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AiRecommendation(Base):
    """A pricing proposal from an external AI agent for a single item.

    Proposals never mutate the item until a specialist accepts one.
    """

    __tablename__ = "ai_recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"), nullable=False, index=True)
    item_crop_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("item_crops.id"), nullable=True
    )
    agent_key_id: Mapped[str] = mapped_column(String, ForeignKey("agent_keys.id"), nullable=False)
    proposed_retail_unit_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposed_shipping_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    source_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_retailer: Mapped[str] = mapped_column(String, nullable=False, default="")
    match_type: Mapped[str] = mapped_column(String, nullable=False, default="exact")
    product_title: Mapped[str] = mapped_column(String, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    source_captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
