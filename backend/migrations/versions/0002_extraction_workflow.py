"""add extraction, review, approval, and export tables

Revision ID: 0002_extraction_workflow
Revises: 0001_initial
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_extraction_workflow"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    enums = {
        "extractionstatus": ["PENDING", "COMPLETED", "FAILED"],
        "fieldreviewstatus": ["UNREVIEWED", "CONFIRMED", "CORRECTED", "MISSING", "UNREADABLE"],
        "validationstatus": ["PASSED", "FAILED", "NEEDS_REVIEW", "NOT_AVAILABLE"],
        "approvaldecision": ["APPROVED", "REJECTED"],
    }
    if bind.dialect.name != "sqlite":
        for name, values in enums.items():
            sa.Enum(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("schema_name", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("status", sa.Enum(*enums["extractionstatus"], name="extractionstatus"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("raw_response", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_extraction_runs_document_id", "extraction_runs", ["document_id"])
    op.create_table(
        "extracted_fields",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_run_id", sa.String(36), sa.ForeignKey("extraction_runs.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("field_name", sa.String(120), nullable=False),
        sa.Column("original_value", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("page_number", sa.Integer()),
        sa.Column("source_coordinates", sa.JSON()),
        sa.Column("review_status", sa.Enum(*enums["fieldreviewstatus"], name="fieldreviewstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_extracted_fields_run_id", "extracted_fields", ["extraction_run_id"])
    op.create_index("ix_extracted_fields_document_id", "extracted_fields", ["document_id"])
    op.create_index("ix_extracted_fields_field_name", "extracted_fields", ["field_name"])
    op.create_table(
        "invoice_line_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_run_id", sa.String(36), sa.ForeignKey("extraction_runs.id"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Float()),
        sa.Column("unit_of_measure", sa.String(40)),
        sa.Column("unit_price", sa.Float()),
        sa.Column("currency", sa.String(3)),
        sa.Column("hsn_code", sa.String(32)),
    )
    op.create_index("ix_invoice_line_items_run_id", "invoice_line_items", ["extraction_run_id"])
    op.create_table(
        "container_numbers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("extraction_run_id", sa.String(36), sa.ForeignKey("extraction_runs.id"), nullable=False),
        sa.Column("container_number", sa.String(32), nullable=False),
    )
    op.create_index("ix_container_numbers_run_id", "container_numbers", ["extraction_run_id"])
    op.create_index("ix_container_numbers_number", "container_numbers", ["container_number"])
    op.create_table(
        "corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("field_id", sa.String(36), sa.ForeignKey("extracted_fields.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_value", sa.Text()),
        sa.Column("corrected_value", sa.Text()),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_corrections_field_id", "corrections", ["field_id"])
    op.create_table(
        "validation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("rule_id", sa.String(80), nullable=False),
        sa.Column("compared_field", sa.String(120), nullable=False),
        sa.Column("source_documents", sa.JSON(), nullable=False),
        sa.Column("values_compared", sa.JSON(), nullable=False),
        sa.Column("difference", sa.Float()),
        sa.Column("status", sa.Enum(*enums["validationstatus"], name="validationstatus"), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_validation_results_shipment_id", "validation_results", ["shipment_id"])
    op.create_index("ix_validation_results_rule_id", "validation_results", ["rule_id"])
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("manager_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.Enum(*enums["approvaldecision"], name="approvaldecision"), nullable=False),
        sa.Column("comments", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approvals_shipment_id", "approvals", ["shipment_id"])
    op.create_table(
        "export_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("export_format", sa.String(10), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_export_logs_shipment_id", "export_logs", ["shipment_id"])


def downgrade() -> None:
    op.drop_table("export_logs")
    op.drop_index("ix_approvals_shipment_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_validation_results_rule_id", table_name="validation_results")
    op.drop_index("ix_validation_results_shipment_id", table_name="validation_results")
    op.drop_table("validation_results")
    op.drop_index("ix_corrections_field_id", table_name="corrections")
    op.drop_table("corrections")
    op.drop_index("ix_container_numbers_number", table_name="container_numbers")
    op.drop_index("ix_container_numbers_run_id", table_name="container_numbers")
    op.drop_table("container_numbers")
    op.drop_index("ix_invoice_line_items_run_id", table_name="invoice_line_items")
    op.drop_table("invoice_line_items")
    op.drop_index("ix_extracted_fields_field_name", table_name="extracted_fields")
    op.drop_index("ix_extracted_fields_document_id", table_name="extracted_fields")
    op.drop_index("ix_extracted_fields_run_id", table_name="extracted_fields")
    op.drop_table("extracted_fields")
    op.drop_index("ix_extraction_runs_document_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
