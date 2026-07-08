"""SQLAlchemy 2.x ORM models for ClaimOS database schema."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def _new_uuid() -> str:
    """Generate a new UUID string for primary keys."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Claim(Base):
    """A claim case. One claim = one attorney's claim, one report."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    firm_name: Mapped[str] = mapped_column(String, default="")
    attorney_name: Mapped[str] = mapped_column(String, default="")
    attorney_email: Mapped[str] = mapped_column(String, default="")
    policyholder_name: Mapped[str] = mapped_column(String, default="")
    loss_location: Mapped[str] = mapped_column(String, default="")
    loss_type: Mapped[str] = mapped_column(String, default="total_loss")
    loss_event: Mapped[str] = mapped_column(String, default="")
    loss_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    carrier: Mapped[str] = mapped_column(String, default="")
    policy_number: Mapped[str] = mapped_column(String, default="")
    claim_number: Mapped[str] = mapped_column(String, default="")
    coverage_c_limit: Mapped[int] = mapped_column(Integer, default=0)
    firm_file_number: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="draft")
    target_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivered_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    owner_group_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("groups.id"), nullable=True
    )
    created_by_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    rooms: Mapped[list["Room"]] = relationship(
        "Room", back_populates="claim", cascade="all, delete-orphan"
    )
    items: Mapped[list["Item"]] = relationship(
        "Item", back_populates="claim", cascade="all, delete-orphan"
    )
    evidence_files: Mapped[list["EvidenceFile"]] = relationship(
        "EvidenceFile", back_populates="claim", cascade="all, delete-orphan"
    )
    vision_runs: Mapped[list["VisionRun"]] = relationship(
        "VisionRun", back_populates="claim", cascade="all, delete-orphan"
    )


class Room(Base):
    """A room or space in the insured property."""

    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    name: Mapped[str] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    claim: Mapped["Claim"] = relationship("Claim", back_populates="rooms")
    items: Mapped[list["Item"]] = relationship("Item", back_populates="room")


class ItemGroup(Base):
    """An on-site organizational group (e.g. items grouped under a numbered placard).

    Named `ItemGroup` to avoid collision with the auth/RBAC `Group` model
    (`src/claimos/models_auth.py`). The user-facing label in the UI is "Group".
    """

    __tablename__ = "item_groups"
    __table_args__ = (
        Index("ix_item_groups_claim_id", "claim_id"),
        Index(
            "uq_item_groups_claim_name_normalized",
            "claim_id",
            "name_normalized",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    name: Mapped[str] = mapped_column(String)
    name_normalized: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Category(Base):
    """Depreciation category (seed data, 42 rows per depreciation schedule)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    useful_life_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acv_floor_pct: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str] = mapped_column(String, default="")

    # Relationships
    items: Mapped[list["Item"]] = relationship("Item", back_populates="category")


class Item(Base):
    """A line item in the contents inventory."""

    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    room_id: Mapped[str | None] = mapped_column(String, ForeignKey("rooms.id"), nullable=True)
    item_group_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("item_groups.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String, default="")
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    age_years: Mapped[float] = mapped_column(Float, default=0.0)
    condition: Mapped[str] = mapped_column(String, default="average")
    rcv_unit_cents: Mapped[int] = mapped_column(Integer, default=0)
    rcv_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    acv_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    acv_override_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acv_override_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    match_type: Mapped[str] = mapped_column(String, default="exact")
    source_retailer: Mapped[str] = mapped_column(String, default="")
    source_url: Mapped[str] = mapped_column(String, default="")
    source_captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_screenshot_path: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    search_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    claim: Mapped["Claim"] = relationship("Claim", back_populates="items")
    room: Mapped["Room | None"] = relationship("Room", back_populates="items")
    category: Mapped["Category"] = relationship("Category", back_populates="items")
    item_group: Mapped["ItemGroup | None"] = relationship("ItemGroup")
    crops: Mapped[list["ItemCrop"]] = relationship(
        "ItemCrop", back_populates="item", cascade="all, delete-orphan"
    )


class EvidenceFile(Base):
    """A file (photo, video, PDF, etc.) uploaded for a claim."""

    __tablename__ = "evidence_files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String, default="other")
    pinned_item_group_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("item_groups.id", ondelete="SET NULL"), nullable=True
    )
    scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    claim: Mapped["Claim"] = relationship("Claim", back_populates="evidence_files")
    pinned_item_group: Mapped["ItemGroup | None"] = relationship("ItemGroup")
    vision_runs: Mapped[list["VisionRun"]] = relationship(
        "VisionRun", back_populates="evidence_file", cascade="all, delete-orphan"
    )
    crops: Mapped[list["ItemCrop"]] = relationship(
        "ItemCrop", back_populates="evidence_file", cascade="all, delete-orphan"
    )


class VisionRun(Base):
    """A record of a Vision API call on an evidence file."""

    __tablename__ = "vision_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    evidence_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_files.id"), nullable=False
    )
    model: Mapped[str] = mapped_column(String, default="")
    prompt_version: Mapped[str] = mapped_column(String, default="")
    raw_response: Mapped[str] = mapped_column(Text, default="")
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    adapter: Mapped[str] = mapped_column(String, nullable=False, default="none")
    cost_cents_estimated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    claim: Mapped["Claim"] = relationship("Claim", back_populates="vision_runs")
    evidence_file: Mapped["EvidenceFile"] = relationship(
        "EvidenceFile", back_populates="vision_runs"
    )


class VisionJob(Base):
    """A batch vision scan job — groups one or more VisionJobImages."""

    __tablename__ = "vision_jobs"
    __table_args__ = (Index("ix_vision_jobs_claim_created", "claim_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), nullable=False)
    model_slug: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="running")  # running | done | error
    created_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    images: Mapped[list["VisionJobImage"]] = relationship(
        "VisionJobImage", back_populates="job", cascade="all, delete-orphan"
    )


class VisionJobImage(Base):
    """One image within a VisionJob, tracking its individual scan status."""

    __tablename__ = "vision_job_images"
    __table_args__ = (
        Index("ix_vision_job_images_status_created", "status", "created_at"),
        Index("ix_vision_job_images_evidence_file_id", "evidence_file_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    job_id: Mapped[str] = mapped_column(
        String, ForeignKey("vision_jobs.id", ondelete="CASCADE"), nullable=False
    )
    evidence_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_files.id", ondelete="CASCADE"), nullable=False
    )
    # pending | running | done | error
    status: Mapped[str] = mapped_column(String, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    # Region rescan: when all four are set, the worker scans only this
    # sub-rectangle of the evidence image (original-image pixel coords).
    region_left: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_upper: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_right: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_lower: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def region_bbox(self) -> tuple[int, int, int, int] | None:
        vals = (self.region_left, self.region_upper, self.region_right, self.region_lower)
        if all(v is not None for v in vals):
            return (
                self.region_left,
                self.region_upper,
                self.region_right,
                self.region_lower,
            )
        return None

    job: Mapped["VisionJob"] = relationship("VisionJob", back_populates="images")


class ItemCrop(Base):
    """A cropped image of a single item extracted from an evidence photo."""

    __tablename__ = "item_crops"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"), nullable=False)
    evidence_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_files.id"), nullable=False
    )
    bbox_left: Mapped[int] = mapped_column(Integer, default=0)
    bbox_upper: Mapped[int] = mapped_column(Integer, default=0)
    bbox_right: Mapped[int] = mapped_column(Integer, default=0)
    bbox_lower: Mapped[int] = mapped_column(Integer, default=0)
    adjusted_bbox_left: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_bbox_upper: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_bbox_right: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_bbox_lower: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crop_path: Mapped[str] = mapped_column(String, default="")
    crop_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def effective_bbox(self) -> tuple[int, int, int, int]:
        if all(
            v is not None
            for v in (
                self.adjusted_bbox_left,
                self.adjusted_bbox_upper,
                self.adjusted_bbox_right,
                self.adjusted_bbox_lower,
            )
        ):
            return (
                self.adjusted_bbox_left,
                self.adjusted_bbox_upper,
                self.adjusted_bbox_right,
                self.adjusted_bbox_lower,
            )
        return (self.bbox_left, self.bbox_upper, self.bbox_right, self.bbox_lower)

    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="crops")
    evidence_file: Mapped["EvidenceFile"] = relationship("EvidenceFile", back_populates="crops")
    serp_searches: Mapped[list["SerpSearch"]] = relationship(
        "SerpSearch", back_populates="item_crop", cascade="all, delete-orphan"
    )


class SerpSearch(Base):
    """A SerpAPI search run against a specific item crop."""

    __tablename__ = "serp_searches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    item_crop_id: Mapped[str] = mapped_column(String, ForeignKey("item_crops.id"), nullable=False)
    service: Mapped[str] = mapped_column(String, default="google_lens")
    image_url: Mapped[str] = mapped_column(String, default="")
    request_url: Mapped[str] = mapped_column(String, default="")
    request_params: Mapped[str] = mapped_column(Text, default="")
    response_json: Mapped[str] = mapped_column(Text, default="")
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    item_crop: Mapped["ItemCrop"] = relationship("ItemCrop", back_populates="serp_searches")


import claimos.models_access as _access_models  # noqa: F401, E402 — register access tables with Base
import claimos.models_app_setting as _app_setting_models  # noqa: F401, E402 — register app_setting table with Base
import claimos.models_audit as _audit_models  # noqa: F401, E402
import claimos.models_auth as _auth_models  # noqa: F401, E402 — register auth tables with Base
import claimos.models_comments as _comment_models  # noqa: F401, E402 — register comments table with Base
import claimos.models_feedback as _feedback_models  # noqa: F401, E402 — register feedback tables with Base
import claimos.models_vision as _vision_models  # noqa: F401, E402 — register vision_models table with Base
