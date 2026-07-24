"""claim nickname

Revision ID: 4f97bbe2ad3c
Revises: 515c6c0e7711
Create Date: 2026-07-23 09:37:55.074824+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f97bbe2ad3c'
down_revision: Union[str, None] = '515c6c0e7711'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable so existing rows survive the ALTER.
    op.add_column("claims", sa.Column("nickname", sa.String(), nullable=True))
    # 2. Backfill every existing row to a unique, non-null placeholder.
    op.execute("UPDATE claims SET nickname = 'Claim ' || substr(id, 1, 8)")
    # 3. Enforce NOT NULL now that no nulls remain (batch mode for SQLite).
    with op.batch_alter_table("claims") as batch_op:
        batch_op.alter_column("nickname", existing_type=sa.String(), nullable=False)
    # 4. Case-insensitive per-group unique index.
    op.create_index(
        "uq_claims_group_nickname_ci",
        "claims",
        ["owner_group_id", sa.text("lower(nickname)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_claims_group_nickname_ci", table_name="claims")
    with op.batch_alter_table("claims") as batch_op:
        batch_op.drop_column("nickname")
