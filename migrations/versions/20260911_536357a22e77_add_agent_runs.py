"""add agent_runs

Revision ID: 536357a22e77
Revises: 46e5951cae12
Create Date: 2026-09-11 07:21:01.964432+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '536357a22e77'
down_revision: Union[str, None] = '46e5951cae12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="queued", nullable=False),
        sa.Column("status_message", sa.String(), nullable=True),
        sa.Column("agent_impl", sa.String(), nullable=False),
        sa.Column("model_slug", sa.String(), nullable=False),
        sa.Column("image_tag", sa.String(), nullable=True),
        sa.Column("cost_micro_usd", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("browser_run_used", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_by_id", sa.String(), nullable=True),
        sa.Column("agent_key_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"]),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["agent_key_id"], ["agent_keys.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_item_id"), "agent_runs", ["item_id"])
    with op.batch_alter_table("ai_recommendations") as batch:
        batch.add_column(sa.Column("agent_run_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_ai_recommendations_agent_run_id", "agent_runs", ["agent_run_id"], ["id"]
        )
    op.create_index(
        op.f("ix_ai_recommendations_agent_run_id"), "ai_recommendations", ["agent_run_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_recommendations_agent_run_id"), table_name="ai_recommendations")
    with op.batch_alter_table("ai_recommendations") as batch:
        batch.drop_constraint("fk_ai_recommendations_agent_run_id", type_="foreignkey")
        batch.drop_column("agent_run_id")
    op.drop_index(op.f("ix_agent_runs_item_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
