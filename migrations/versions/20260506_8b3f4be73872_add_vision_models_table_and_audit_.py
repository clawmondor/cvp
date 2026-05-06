"""add vision_models table and audit columns

Revision ID: 8b3f4be73872
Revises: 6d40e8b7090d
Create Date: 2026-05-06 10:23:03.654096+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b3f4be73872"
down_revision: Union[str, None] = "6d40e8b7090d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = insp.get_table_names()

    # Create vision_models table (idempotent — conftest create_all may have run first)
    if "vision_models" not in existing_tables:
        op.create_table(
            "vision_models",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("adapter", sa.String(), nullable=False),
            sa.Column("prompt_image_cost_cents", sa.Integer(), nullable=True),
            sa.Column("context_length", sa.Integer(), nullable=True),
            sa.Column("supports_bbox", sa.Boolean(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False),
            sa.Column("recommended", sa.Boolean(), nullable=False),
            sa.Column("added_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("added_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )

    # Partial unique index — enforces at most one row with is_default=TRUE
    existing_indexes = {idx["name"] for idx in insp.get_indexes("vision_models")}
    if "ix_vision_models_one_default" not in existing_indexes:
        op.create_index(
            "ix_vision_models_one_default",
            "vision_models",
            ["is_default"],
            unique=True,
            postgresql_where=sa.text("is_default IS TRUE"),
            sqlite_where=sa.text("is_default = 1"),
        )

    # Seed the default model row (skip if already present)
    is_sqlite = bind.dialect.name == "sqlite"
    true_val = "1" if is_sqlite else "TRUE"
    existing = bind.execute(sa.text("SELECT count(*) FROM vision_models WHERE slug='anthropic/claude-opus-4'")).scalar()
    if not existing:
        op.execute(
            f"INSERT INTO vision_models "
            f"(slug, display_name, adapter, supports_bbox, is_default, is_enabled, recommended) "
            f"VALUES ('anthropic/claude-opus-4', 'Claude Opus 4', 'pixel_passthrough', "
            f"{true_val}, {true_val}, {true_val}, {true_val})"
        )

    # Add audit columns to users (idempotent)
    users_cols = {c["name"] for c in insp.get_columns("users")}
    if "last_vision_model_slug" not in users_cols:
        op.add_column("users", sa.Column("last_vision_model_slug", sa.String(), nullable=True))

    # Add audit columns to vision_runs (idempotent)
    vr_cols = {c["name"] for c in insp.get_columns("vision_runs")}
    if "adapter" not in vr_cols:
        op.add_column(
            "vision_runs",
            sa.Column(
                "adapter",
                sa.String(),
                nullable=False,
                server_default=sa.text("'none'"),
            ),
        )
    if "cost_cents_estimated" not in vr_cols:
        op.add_column(
            "vision_runs", sa.Column("cost_cents_estimated", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    op.drop_column("vision_runs", "cost_cents_estimated")
    op.drop_column("vision_runs", "adapter")
    op.drop_column("users", "last_vision_model_slug")
    op.drop_index("ix_vision_models_one_default", table_name="vision_models")
    op.drop_table("vision_models")
