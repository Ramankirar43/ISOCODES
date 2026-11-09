from pathlib import Path

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import (
    Document,
    DocumentType,
    ExtractedField,
    ExtractionRun,
    ExtractionStatus,
    FieldReviewStatus,
    Importer,
    InvoiceLineItem,
    Shipment,
    ShipmentStatus,
    User,
    UserRole,
)
from app.db.session import Base, SessionLocal, engine


def _present(value: str, confidence: float = 0.96) -> dict:
    return {"state": "present", "value": value, "confidence": confidence, "page_number": 1}


def _write_demo_pdf(relative_key: str, title: str) -> None:
    root = Path(settings.local_storage_path)
    path = root / relative_key
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    # Minimal valid PDF so private document preview and process paths have a file.
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
        b"4 0 obj<< /Length 44 >>stream\n"
        b"BT /F1 18 Tf 72 720 Td (" + title.encode("latin-1", "replace")[:28] + b") Tj ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
    )
    path.write_bytes(content)


def _add_fields(db, run_id: str, document_id: str, fields: list[tuple[str, str, float]]) -> None:
    for name, value, confidence in fields:
        status = FieldReviewStatus.CONFIRMED if confidence >= 0.70 else FieldReviewStatus.UNREVIEWED
        db.add(
            ExtractedField(
                extraction_run_id=run_id,
                document_id=document_id,
                field_name=name,
                original_value=value,
                confidence=confidence,
                page_number=1,
                review_status=status,
            )
        )


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        importer = db.query(Importer).filter_by(legal_name="Demo Importer").first()
        if importer is None:
            importer = Importer(legal_name="Demo Importer")
            db.add(importer)
            db.flush()
        accounts = [
            ("manager@example.com", "Demo Manager", UserRole.MANAGER, None),
            ("executive@example.com", "Demo Executive", UserRole.EXECUTIVE, None),
            ("importer@example.com", "Demo Importer User", UserRole.IMPORTER, importer.id),
        ]
        for email, name, role, importer_id in accounts:
            if db.query(User).filter_by(email=email).first() is None:
                db.add(
                    User(
                        email=email,
                        password_hash=hash_password("password"),
                        full_name=name,
                        role=role,
                        importer_id=importer_id,
                    )
                )
        db.flush()
        executive = db.query(User).filter_by(email="executive@example.com").first()
        if executive and db.query(Shipment).filter_by(shipment_number="SHP-24811").first() is None:
            shipment = Shipment(
                shipment_number="SHP-24811",
                importer_id=importer.id,
                supplier_name="Company B (China)",
                status=ShipmentStatus.REVIEW_REQUIRED,
                created_by=executive.id,
            )
            db.add(shipment)
            db.flush()

            invoice_key = "demo/SHP-24811-commercial-invoice.pdf"
            packing_key = "demo/SHP-24811-packing-list.pdf"
            bol_key = "demo/SHP-24811-bill-of-lading.pdf"
            _write_demo_pdf(invoice_key, "SHP-24811 Invoice")
            _write_demo_pdf(packing_key, "SHP-24811 Packing")
            _write_demo_pdf(bol_key, "SHP-24811 BOL")

            invoice_extracted = {
                "document_type": "invoice",
                "exporter": _present("Company B (China)"),
                "importer": _present("Demo Importer"),
                "invoice_number": _present("INV-24811"),
                "invoice_date": "2026-09-12",
                "currency": _present("USD"),
                "incoterm": _present("FOB"),
                "package_count": 48,
                "gross_weight_kg": 3120,
                "subtotal": 16320,
                "taxes": 0,
                "discounts": 0,
                "additional_charges": 0,
                "total": 16320,
                "line_items": [
                    {
                        "description": "LED panel light 40W",
                        "quantity": 2400,
                        "unit_of_measure": "PCS",
                        "unit_price": 6.8,
                        "hsn_code": "9405",
                    }
                ],
            }
            packing_extracted = {
                "document_type": "packing_list",
                "exporter": _present("Company B (China)"),
                "importer": _present("Demo Importer"),
                "item_descriptions": ["LED panel light 40W"],
                "total_quantity": 2400,
                "package_count": 48,
                "package_type": _present("CTN"),
                "gross_weight_kg": 3165,
                "net_weight_kg": 2980,
                "container_numbers": ["TCLU1234567"],
            }
            bol_extracted = {
                "document_type": "bill_of_lading",
                "exporter": _present("Company B (China)"),
                "consignee": _present("Demo Importer"),
                "notify_party": _present("Demo Importer"),
                "bill_number": _present("BOL-24811"),
                "gross_weight_kg": 3165,
                "package_count": 48,
                "container_numbers": ["TCLU1234567"],
            }

            for document_type, filename, storage_key, schema_name, extracted, field_defs in [
                (
                    DocumentType.INVOICE,
                    "SHP-24811-commercial-invoice.pdf",
                    invoice_key,
                    "InvoiceExtraction",
                    invoice_extracted,
                    [
                        ("exporter", "Company B (China)", 0.97),
                        ("importer", "Demo Importer", 0.95),
                        ("invoice_number", "INV-24811", 0.98),
                        ("currency", "USD", 0.99),
                        ("incoterm", "FOB", 0.92),
                    ],
                ),
                (
                    DocumentType.PACKING_LIST,
                    "SHP-24811-packing-list.pdf",
                    packing_key,
                    "PackingListExtraction",
                    packing_extracted,
                    [
                        ("exporter", "Company B (China)", 0.96),
                        ("importer", "Demo Importer", 0.94),
                        ("package_type", "CTN", 0.91),
                    ],
                ),
                (
                    DocumentType.BILL_OF_LADING,
                    "SHP-24811-bill-of-lading.pdf",
                    bol_key,
                    "BillOfLadingExtraction",
                    bol_extracted,
                    [
                        ("exporter", "Company B (China)", 0.95),
                        ("consignee", "Demo Importer", 0.93),
                        ("bill_number", "BOL-24811", 0.97),
                        ("notify_party", "Demo Importer", 0.88),
                    ],
                ),
            ]:
                document = Document(
                    shipment_id=shipment.id,
                    document_type=document_type,
                    original_filename=filename,
                    storage_key=storage_key,
                    processing_status="completed",
                )
                db.add(document)
                db.flush()
                run = ExtractionRun(
                    document_id=document.id,
                    schema_name=schema_name,
                    provider="synthetic-demo-data",
                    status=ExtractionStatus.COMPLETED,
                    raw_response={"demo": True, "extracted": extracted},
                )
                db.add(run)
                db.flush()
                _add_fields(db, run.id, document.id, field_defs)
                if document_type == DocumentType.INVOICE:
                    db.add(
                        InvoiceLineItem(
                            extraction_run_id=run.id,
                            description="LED panel light 40W",
                            quantity=2400,
                            unit_of_measure="PCS",
                            unit_price=6.8,
                            currency="USD",
                            hsn_code="9405",
                        )
                    )

            shipment_2 = Shipment(
                shipment_number="SHP-24812",
                importer_id=importer.id,
                supplier_name="Company C (Sweden)",
                status=ShipmentStatus.DRAFT,
                created_by=executive.id,
            )
            db.add(shipment_2)
            db.flush()
            invoice_2_key = "demo/SHP-24812-commercial-invoice.pdf"
            _write_demo_pdf(invoice_2_key, "SHP-24812 Invoice")
            document_2 = Document(
                shipment_id=shipment_2.id,
                document_type=DocumentType.INVOICE,
                original_filename="SHP-24812-commercial-invoice.pdf",
                storage_key=invoice_2_key,
                processing_status="completed",
            )
            db.add(document_2)
            db.flush()
            invoice_2_extracted = {
                "document_type": "invoice",
                "exporter": _present("Company C (Sweden)"),
                "importer": _present("Demo Importer"),
                "invoice_number": _present("INV-24812"),
                "invoice_date": "2026-09-18",
                "currency": _present("EUR"),
                "incoterm": _present("CIF"),
                "package_count": 12,
                "gross_weight_kg": 1460,
                "subtotal": 7650,
                "taxes": 0,
                "discounts": 0,
                "additional_charges": 0,
                "total": 7650,
                "line_items": [
                    {
                        "description": "Steel ball valve DN50",
                        "quantity": 180,
                        "unit_of_measure": "PCS",
                        "unit_price": 42.5,
                        "hsn_code": "8481",
                    }
                ],
            }
            run_2 = ExtractionRun(
                document_id=document_2.id,
                schema_name="InvoiceExtraction",
                provider="synthetic-demo-data",
                status=ExtractionStatus.COMPLETED,
                raw_response={"demo": True, "extracted": invoice_2_extracted},
            )
            db.add(run_2)
            db.flush()
            _add_fields(
                db,
                run_2.id,
                document_2.id,
                [
                    ("exporter", "Company C (Sweden)", 0.97),
                    ("importer", "Demo Importer", 0.95),
                    ("invoice_number", "INV-24812", 0.98),
                    ("currency", "EUR", 0.99),
                    ("incoterm", "CIF", 0.9),
                ],
            )
            db.add(
                InvoiceLineItem(
                    extraction_run_id=run_2.id,
                    description="Steel ball valve DN50",
                    quantity=180,
                    unit_of_measure="PCS",
                    unit_price=42.5,
                    currency="EUR",
                    hsn_code="8481",
                )
            )
            shipment_2.status = ShipmentStatus.REVIEW_REQUIRED
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
