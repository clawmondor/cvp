"""add item groups

Revision ID: c1999a71280b
Revises: 73361c8303fb
Create Date: 2026-06-09 09:57:56.510399+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1999a71280b'
down_revision: Union[str, None] = '73361c8303fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_groups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_normalized", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_groups_matter_id", "item_groups", ["matter_id"])
    op.create_index(
        "uq_item_groups_matter_name_normalized",
        "item_groups",
        ["matter_id", "name_normalized"],
        unique=True,
    )

    with op.batch_alter_table("items") as batch_op:
        batch_op.add_column(sa.Column("item_group_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_items_item_group_id",
            "item_groups",
            ["item_group_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("evidence_files") as batch_op:
        batch_op.add_column(sa.Column("pinned_item_group_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evidence_files_pinned_item_group_id",
            "item_groups",
            ["pinned_item_group_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_files") as batch_op:
        batch_op.drop_constraint("fk_evidence_files_pinned_item_group_id", type_="foreignkey")
        batch_op.drop_column("pinned_item_group_id")

    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_constraint("fk_items_item_group_id", type_="foreignkey")
        batch_op.drop_column("item_group_id")

    op.drop_index("uq_item_groups_matter_name_normalized", table_name="item_groups")
    op.drop_index("ix_item_groups_matter_id", table_name="item_groups")
    op.drop_table("item_groups")
