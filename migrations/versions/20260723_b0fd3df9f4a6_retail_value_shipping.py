"""retail value + shipping

Revision ID: b0fd3df9f4a6
Revises: 9958928bc311
Create Date: 2026-07-23 02:51:08.050687+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0fd3df9f4a6'
down_revision: Union[str, None] = '9958928bc311'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("items", "rcv_unit_cents", new_column_name="retail_unit_cents")
    op.add_column(
        "items",
        sa.Column("shipping_cents", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_column("shipping_cents")
        batch_op.alter_column("retail_unit_cents", new_column_name="rcv_unit_cents")
