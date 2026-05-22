"""add_vision_job_tables

Revision ID: 56a54cc0c202
Revises: d41ffbf06ede
Create Date: 2026-05-22 07:52:46.292086+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56a54cc0c202'
down_revision: Union[str, None] = 'd41ffbf06ede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vision_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        sa.Column("model_slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"]),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_vision_jobs_matter_created",
        "vision_jobs",
        ["matter_id", "created_at"],
        if_not_exists=True,
    )
    op.create_table(
        "vision_job_images",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("evidence_file_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("items_created", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["evidence_file_id"], ["evidence_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["vision_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_vision_job_images_evidence_file_id",
        "vision_job_images",
        ["evidence_file_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_vision_job_images_status_created",
        "vision_job_images",
        ["status", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_vision_job_images_evidence_file_id", table_name="vision_job_images")
    op.drop_index("ix_vision_job_images_status_created", table_name="vision_job_images")
    op.drop_table("vision_job_images")
    op.drop_index("ix_vision_jobs_matter_created", table_name="vision_jobs")
    op.drop_table("vision_jobs")
