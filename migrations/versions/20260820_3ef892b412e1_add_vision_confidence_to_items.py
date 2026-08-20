"""add vision_confidence to items

Revision ID: 3ef892b412e1
Revises: ec422cfad035
Create Date: 2026-08-20 05:32:53.779971+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3ef892b412e1'
down_revision: Union[str, None] = 'ec422cfad035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("items", sa.Column("vision_confidence", sa.String(), nullable=True))
    op.create_index("ix_items_vision_confidence", "items", ["vision_confidence"])

    # Backfill from the legacy notes string using the same parser as runtime.
    from cvp.services.confidence import parse_confidence_from_notes

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, notes FROM items")).fetchall()
    for row in rows:
        conf = parse_confidence_from_notes(row.notes)
        if conf is not None:
            bind.execute(
                sa.text("UPDATE items SET vision_confidence = :c WHERE id = :id"),
                {"c": conf, "id": row.id},
            )


def downgrade() -> None:
    op.drop_index("ix_items_vision_confidence", table_name="items")
    op.drop_column("items", "vision_confidence")
