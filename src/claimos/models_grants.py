"""ORM models for RBAC v2 group-scoped role grants (external users)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from claimos.models import Base, _new_uuid


class RoleGrant(Base):
    """A User Role assigned to a user within a group, group-wide or claim-narrowed."""

    __tablename__ = "role_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", "user_role", "scope", name="uq_role_grant"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("groups.id"), nullable=False, index=True
    )
    user_role: Mapped[str] = mapped_column(String, nullable=False)  # roles.py key
    scope: Mapped[str] = mapped_column(String, nullable=False)  # "group" | "claims"
    granted_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    claims: Mapped[list["RoleGrantClaim"]] = relationship(
        "RoleGrantClaim", back_populates="grant", cascade="all, delete-orphan"
    )
    overrides: Mapped[list["RoleGrantOverride"]] = relationship(
        "RoleGrantOverride", back_populates="grant", cascade="all, delete-orphan"
    )


class RoleGrantClaim(Base):
    """Narrows a claims-scoped grant to a specific claim."""

    __tablename__ = "role_grant_claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    grant_id: Mapped[str] = mapped_column(
        String, ForeignKey("role_grants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id"), nullable=False, index=True
    )

    grant: Mapped["RoleGrant"] = relationship("RoleGrant", back_populates="claims")


class RoleGrantOverride(Base):
    """Per-object bump on top of a grant's User Role profile."""

    __tablename__ = "role_grant_overrides"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_uuid)
    grant_id: Mapped[str] = mapped_column(
        String, ForeignKey("role_grants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)

    grant: Mapped["RoleGrant"] = relationship("RoleGrant", back_populates="overrides")
