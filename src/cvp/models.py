"""SQLAlchemy 2.x ORM models for CVP database schema."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
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


class Matter(Base):
    """A claim case. One matter = one attorney's claim, one report."""

    __tablename__ = "matters"

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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    rooms: Mapped[list["Room"]] = relationship(
        "Room", back_populates="matter", cascade="all, delete-orphan"
    )
    items: Mapped[list["Item"]] = relationship(
        "Item", back_populates="matter", cascade="all, delete-orphan"
    )
    evidence_files: Mapped[list["EvidenceFile"]] = relationship(
        "EvidenceFile", back_populates="matter", cascade="all, delete-orphan"
    )
    vision_runs: Mapped[list["VisionRun"]] = relationship(
        "VisionRun", back_populates="matter", cascade="all, delete-orphan"
    )


class Room(Base):
    """A room or space in the insured property."""

    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    name: Mapped[str] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    matter: Mapped["Matter"] = relationship("Matter", back_populates="rooms")
    items: Mapped[list["Item"]] = relationship("Item", back_populates="room")


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
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    room_id: Mapped[str | None] = mapped_column(String, ForeignKey("rooms.id"), nullable=True)
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
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    matter: Mapped["Matter"] = relationship("Matter", back_populates="items")
    room: Mapped["Room | None"] = relationship("Room", back_populates="items")
    category: Mapped["Category"] = relationship("Category", back_populates="items")


class EvidenceFile(Base):
    """A file (photo, video, PDF, etc.) uploaded for a matter."""

    __tablename__ = "evidence_files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String, default="other")
    scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    matter: Mapped["Matter"] = relationship("Matter", back_populates="evidence_files")
    vision_runs: Mapped[list["VisionRun"]] = relationship(
        "VisionRun", back_populates="evidence_file"
    )


class VisionRun(Base):
    """A record of a Vision API call on an evidence file."""

    __tablename__ = "vision_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    matter_id: Mapped[str] = mapped_column(String, ForeignKey("matters.id"), nullable=False)
    evidence_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_files.id"), nullable=False
    )
    model: Mapped[str] = mapped_column(String, default="")
    prompt_version: Mapped[str] = mapped_column(String, default="")
    raw_response: Mapped[str] = mapped_column(Text, default="")
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    matter: Mapped["Matter"] = relationship("Matter", back_populates="vision_runs")
    evidence_file: Mapped["EvidenceFile"] = relationship(
        "EvidenceFile", back_populates="vision_runs"
    )
