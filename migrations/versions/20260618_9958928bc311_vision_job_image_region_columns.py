"""vision_job_image region columns

Revision ID: 9958928bc311
Revises: 21c1bb38b418
Create Date: 2026-06-18 11:48:47.197432+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9958928bc311"
down_revision: Union[str, None] = "21c1bb38b418"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vision_job_images", sa.Column("region_left", sa.Integer(), nullable=True))
    op.add_column("vision_job_images", sa.Column("region_upper", sa.Integer(), nullable=True))
    op.add_column("vision_job_images", sa.Column("region_right", sa.Integer(), nullable=True))
    op.add_column("vision_job_images", sa.Column("region_lower", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("vision_job_images", "region_lower")
    op.drop_column("vision_job_images", "region_right")
    op.drop_column("vision_job_images", "region_upper")
    op.drop_column("vision_job_images", "region_left")
