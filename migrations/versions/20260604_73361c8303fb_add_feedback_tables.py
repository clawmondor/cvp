"""add feedback tables

Revision ID: 73361c8303fb
Revises: 56a54cc0c202
Create Date: 2026-06-04 08:48:58.737428+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73361c8303fb'
down_revision: Union[str, None] = '56a54cc0c202'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("author_group_id", sa.String(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("status_changed_at", sa.DateTime(), nullable=True),
        sa.Column("status_changed_by_user_id", sa.String(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(), nullable=True),
        sa.Column("last_admin_read_at", sa.DateTime(), nullable=True),
        sa.Column("last_author_read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["author_group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["status_changed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending','reviewing','backlog','canceled','done')",
            name="ck_feedback_status",
        ),
    )
    op.create_index(
        "ix_feedback_author_created", "feedback", ["author_user_id", "created_at"]
    )
    op.create_index(
        "ix_feedback_status_created", "feedback", ["status", "created_at"]
    )

    op.create_table(
        "feedback_comments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("feedback_id", sa.String(), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_comments_feedback_created",
        "feedback_comments",
        ["feedback_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_comments_feedback_created", table_name="feedback_comments")
    op.drop_table("feedback_comments")
    op.drop_index("ix_feedback_status_created", table_name="feedback")
    op.drop_index("ix_feedback_author_created", table_name="feedback")
    op.drop_table("feedback")
