"""Add human_confirmed to validation_results.

Revision ID: 0004_validation_human_confirmed
Revises: 0003_ground_truth_labels
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_validation_human_confirmed"
down_revision = "0003_ground_truth_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "validation_results",
        sa.Column("human_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("validation_results", "human_confirmed")
