"""make password_hash nullable for invites

Revision ID: acce28426f15
Revises: 7d17b10b2888
Create Date: 2026-04-26 19:20:19.447337+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acce28426f15'
down_revision: Union[str, None] = '7d17b10b2888'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('password_hash', nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('password_hash', nullable=False)
