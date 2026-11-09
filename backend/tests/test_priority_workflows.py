from datetime import datetime, timezone

from app.api.routes.reports import accuracy_report
from app.api.routes.workflow import approval_blockers, export_rows
from app.core.security import hash_password
from app.db.models import (
    Document,
    DocumentType,
    ExtractedField,
    ExtractionRun,
    ExtractionStatus,
    FieldReviewStatus,
    GroundTruthLabel,
    Importer,
    Shipment,
    ShipmentStatus,
    User,
    UserRole,
    ValidationResult,
    ValidationStatus,
)
from app.db.session import Base, SessionLocal, engine


def setup_function() -> None:
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _shipment(db):
    importer = Importer(legal_name="Accuracy Importer")
    user = User(
        email="accuracy-manager@example.com",
        password_hash=hash_password("password"),
        full_name="Accuracy Manager",
        role=UserRole.MANAGER,
    )
    db.add_all([importer, user])
    db.flush()
    shipment = Shipment(
        shipment_number="SHP-PRIORITY-1",
        importer_id=importer.id,
        created_by=user.id,
        supplier_name="Supplier A",
        status=ShipmentStatus.REVIEW_REQUIRED,
    )
    db.add(shipment)
    db.flush()
    return shipment, user


def test_accuracy_uses_latest_ground_truth_and_reports_breakdowns() -> None:
    db = SessionLocal()
    try:
        shipment, user = _shipment(db)
        document = Document(
            shipment_id=shipment.id,
            document_type=DocumentType.INVOICE,
            original_filename="invoice.pdf",
            storage_key="priority/invoice.pdf",
            processing_status="completed",
        )
        db.add(document)
        db.flush()
        run = ExtractionRun(
            document_id=document.id,
            schema_name="InvoiceExtraction",
            provider="test",
            status=ExtractionStatus.COMPLETED,
            raw_response={"extracted": {}},
        )
        db.add(run)
        db.flush()
        correct = ExtractedField(
            extraction_run_id=run.id,
            document_id=document.id,
            field_name="invoice_number",
            original_value="INV-1",
            confidence=0.95,
            review_status=FieldReviewStatus.CONFIRMED,
        )
        incorrect = ExtractedField(
            extraction_run_id=run.id,
            document_id=document.id,
            field_name="currency",
            original_value="EUR",
            confidence=0.95,
            review_status=FieldReviewStatus.CONFIRMED,
        )
        db.add_all([correct, incorrect])
        db.flush()
        created = datetime.now(timezone.utc)
        db.add_all([
            GroundTruthLabel(field_id=correct.id, reviewer_id=user.id, supplier_name="Supplier A", ground_truth_value="INV-1", created_at=created),
            GroundTruthLabel(field_id=incorrect.id, reviewer_id=user.id, supplier_name="Supplier A", ground_truth_value="USD", created_at=created),
        ])
        db.commit()

        report = accuracy_report(db, user)

        assert report["evaluation_sample_size"] == 2
        assert report["measured_accuracy"] == 0.5
        assert report["field_wise_accuracy"]["invoice_number"]["accuracy"] == 1.0
        assert report["supplier_wise_accuracy"]["Supplier A"]["sample_size"] == 2
    finally:
        db.close()


def test_approval_blockers_require_documents_fields_and_validations() -> None:
    db = SessionLocal()
    try:
        shipment, _ = _shipment(db)
        blockers = approval_blockers(db, shipment)

        assert any("Missing required document" in blocker for blocker in blockers)
        assert "Validation has not been run" in blockers
    finally:
        db.close()


def test_corrected_low_confidence_and_confirmed_failures_clear_blockers() -> None:
    db = SessionLocal()
    try:
        shipment, _ = _shipment(db)
        for document_type, filename, fields in [
            (DocumentType.INVOICE, "invoice.pdf", [("exporter", "A"), ("importer", "B"), ("invoice_number", "1"), ("currency", "USD"), ("incoterm", "FOB")]),
            (DocumentType.PACKING_LIST, "packing.pdf", [("exporter", "A"), ("importer", "B"), ("package_type", "CTN")]),
            (DocumentType.BILL_OF_LADING, "bol.pdf", [("exporter", "A"), ("consignee", "B"), ("bill_number", "BOL-1")]),
        ]:
            document = Document(
                shipment_id=shipment.id,
                document_type=document_type,
                original_filename=filename,
                storage_key=f"priority/{filename}",
                processing_status="completed",
            )
            db.add(document)
            db.flush()
            run = ExtractionRun(
                document_id=document.id,
                schema_name="Demo",
                provider="test",
                status=ExtractionStatus.COMPLETED,
                raw_response={"extracted": {}},
            )
            db.add(run)
            db.flush()
            for name, value in fields:
                db.add(
                    ExtractedField(
                        extraction_run_id=run.id,
                        document_id=document.id,
                        field_name=name,
                        original_value=value,
                        confidence=0.4 if name == "incoterm" else 0.95,
                        review_status=FieldReviewStatus.CORRECTED if name == "incoterm" else FieldReviewStatus.CONFIRMED,
                    )
                )
        db.add(
            ValidationResult(
                shipment_id=shipment.id,
                rule_id="gross_weight",
                compared_field="gross_weight_kg",
                source_documents=[],
                values_compared={"invoice": 3120, "packing_list": 3165},
                difference=45,
                status=ValidationStatus.FAILED,
                explanation="Weights differ",
                human_confirmed=True,
            )
        )
        db.add(
            ValidationResult(
                shipment_id=shipment.id,
                rule_id="net_weight",
                compared_field="net_weight_kg",
                source_documents=[],
                values_compared={"packing_list": 10},
                difference=None,
                status=ValidationStatus.NOT_AVAILABLE,
                explanation="Only one value",
                human_confirmed=False,
            )
        )
        db.commit()

        assert approval_blockers(db, shipment) == []
    finally:
        db.close()


def test_export_rows_emit_one_row_per_invoice_line_item() -> None:
    db = SessionLocal()
    try:
        shipment, _ = _shipment(db)
        document = Document(
            shipment_id=shipment.id,
            document_type=DocumentType.INVOICE,
            original_filename="invoice.pdf",
            storage_key="priority/export-invoice.pdf",
            processing_status="completed",
        )
        db.add(document)
        db.flush()
        db.add(
            ExtractionRun(
                document_id=document.id,
                schema_name="InvoiceExtraction",
                provider="test",
                status=ExtractionStatus.COMPLETED,
                raw_response={
                    "extracted": {
                        "invoice_number": {"state": "present", "value": "INV-2"},
                        "currency": {"state": "present", "value": "USD"},
                        "line_items": [
                            {"description": "Widget A", "quantity": 2, "unit_price": 5, "hsn_code": "1001"},
                            {"description": "Widget B", "quantity": 3, "unit_price": 7, "hsn_code": "1002"},
                        ],
                    }
                },
            )
        )
        db.commit()

        rows = export_rows(db, shipment)

        assert len(rows) == 2
        assert rows[0]["line_item_description"] == "Widget A"
        assert rows[1]["hsn"] == "1002"
    finally:
        db.close()
