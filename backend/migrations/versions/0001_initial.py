"""create authentication and shipment tables

Revision ID: 0001_initial
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role = sa.Enum("EXECUTIVE", "MANAGER", "IMPORTER", name="userrole")
    shipment_status = sa.Enum(
        "DRAFT", "UPLOADED", "PROCESSING", "REVIEW_REQUIRED", "PENDING_APPROVAL",
        "APPROVED", "REJECTED", "EXPORTED", "PROCESSING_FAILED", name="shipmentstatus"
    )
    document_type = sa.Enum("INVOICE", "PACKING_LIST", "BILL_OF_LADING", name="documenttype")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        user_role.create(bind, checkfirst=True)
        shipment_status.create(bind, checkfirst=True)
        document_type.create(bind, checkfirst=True)

    op.create_table(
        "importers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("legal_name", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("importer_id", sa.String(36), sa.ForeignKey("importers.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_table(
        "shipments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shipment_number", sa.String(40), nullable=False),
        sa.Column("importer_id", sa.String(36), sa.ForeignKey("importers.id"), nullable=False),
        sa.Column("supplier_name", sa.String(255)),
        sa.Column("status", shipment_status, nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("shipment_number", name="uq_shipments_number"),
    )
    op.create_index("ix_shipments_number", "shipments", ["shipment_number"])
    op.create_index("ix_shipments_importer_id", "shipments", ["importer_id"])
    op.create_index("ix_shipments_status", "shipments", ["status"])
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("document_type", document_type, nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("processing_status", sa.String(40), nullable=False),
        sa.Column("processing_attempts", sa.Integer(), nullable=False),
        sa.Column("processing_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_shipment_id", "documents", ["shipment_id"])
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Index("ix_document_versions_document_id", "document_id"),
    )


def downgrade() -> None:
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_index("ix_shipments_status", table_name="shipments")
    op.drop_index("ix_shipments_importer_id", table_name="shipments")
    op.drop_index("ix_shipments_number", table_name="shipments")
    op.drop_table("shipments")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("importers")
