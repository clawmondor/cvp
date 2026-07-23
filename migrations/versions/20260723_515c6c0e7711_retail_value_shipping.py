"""retail value + shipping

Revision ID: 515c6c0e7711
Revises: c9851834200b
Create Date: 2026-07-23 02:08:58.538735+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '515c6c0e7711'
down_revision: Union[str, None] = 'c9851834200b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("items", "rcv_unit_cents", new_column_name="retail_unit_cents")
    op.add_column(
        "items",
        sa.Column("shipping_cents", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("items", "shipping_cents")
    op.alter_column("items", "retail_unit_cents", new_column_name="rcv_unit_cents")
