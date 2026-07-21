"""migrate external claim_access

Revision ID: c9851834200b
Revises: f8eb20311be3
Create Date: 2026-07-16 06:42:23.839158+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9851834200b'
down_revision: Union[str, None] = 'f8eb20311be3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy.orm import Session

    from claimos.migrate_claim_access import migrate_external_claim_access

    bind = op.get_bind()
    session = Session(bind=bind)
    migrate_external_claim_access(session)


def downgrade() -> None:
    # One-way data migration; external grants are not reverted to claim_access.
    pass
