"""ORM models for external AI agents: AgentKey and AiRecommendation."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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
    agent_run_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agent_runs.id"), nullable=True, index=True
    )
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


class AgentRun(Base):
    """One launch of an ephemeral pricing agent for a single item.

    Records which architecture and model produced a recommendation so that
    A/B comparison is a query. CVP is the only durable store for a run —
    the Cloudflare container keeps nothing.
    """

    __tablename__ = "agent_runs"

    #: Statuses after which no further progress is accepted.
    TERMINAL = frozenset({"succeeded", "failed"})

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"), nullable=False, index=True)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", server_default="queued"
    )
    status_message: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_impl: Mapped[str] = mapped_column(String, nullable=False)
    model_slug: Mapped[str] = mapped_column(String, nullable=False)
    image_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_micro_usd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    browser_run_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    agent_key_id: Mapped[str] = mapped_column(String, ForeignKey("agent_keys.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
