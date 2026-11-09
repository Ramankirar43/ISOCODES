"""add human verified ground truth labels

Revision ID: 0003_ground_truth_labels
Revises: 0002_extraction_workflow
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_ground_truth_labels"
down_revision: Union[str, None] = "0002_extraction_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ground_truth_labels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("field_id", sa.String(36), sa.ForeignKey("extracted_fields.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("supplier_name", sa.String(255)),
        sa.Column("ground_truth_value", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ground_truth_labels_field_id", "ground_truth_labels", ["field_id"])
    op.create_index("ix_ground_truth_labels_reviewer_id", "ground_truth_labels", ["reviewer_id"])


def downgrade() -> None:
    op.drop_index("ix_ground_truth_labels_reviewer_id", table_name="ground_truth_labels")
    op.drop_index("ix_ground_truth_labels_field_id", table_name="ground_truth_labels")
    op.drop_table("ground_truth_labels")
