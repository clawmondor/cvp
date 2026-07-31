"""export templates

Revision ID: ec422cfad035
Revises: a1b2c3d4e5f6
Create Date: 2026-07-31 21:46:20.286078+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec422cfad035'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('export_templates',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('group_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('created_by_id', sa.String(), nullable=True),
    sa.Column('include_needs_review', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('include_excluded', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('sort_field', sa.String(), server_default='line_number', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('export_template_columns',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('template_id', sa.String(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('field_key', sa.String(), nullable=True),
    sa.Column('header_label', sa.String(), nullable=True),
    sa.Column('static_value', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['template_id'], ['export_templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('export_template_columns')
    op.drop_table('export_templates')
