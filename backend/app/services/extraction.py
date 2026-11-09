from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import (
    ContainerNumber,
    Document,
    DocumentType,
    ExtractedField,
    ExtractionRun,
    ExtractionStatus,
    FieldReviewStatus,
    InvoiceLineItem,
    Shipment,
    ShipmentStatus,
)
from app.schemas.extraction import BillOfLadingExtraction, InvoiceExtraction, PackingListExtraction

SCHEMAS: dict[DocumentType, type[BaseModel]] = {
    DocumentType.INVOICE: InvoiceExtraction,
    DocumentType.PACKING_LIST: PackingListExtraction,
    DocumentType.BILL_OF_LADING: BillOfLadingExtraction,
}

FIELD_NAMES = (
    "exporter",
    "importer",
    "invoice_number",
    "currency",
    "incoterm",
    "package_type",
    "consignee",
    "notify_party",
    "bill_number",
)


def validate_extraction(document_type: DocumentType, payload: dict[str, Any]) -> BaseModel:
    return SCHEMAS[document_type].model_validate(payload)


def persist_extraction(
    db: Session,
    document: Document,
    shipment: Shipment,
    extracted: BaseModel,
    provider: str,
    raw_response: dict[str, Any],
    run: ExtractionRun | None = None,
) -> ExtractionRun:
    if run is None:
        run = ExtractionRun(
            document_id=document.id,
            schema_name=type(extracted).__name__,
            provider=provider,
            status=ExtractionStatus.COMPLETED,
            raw_response={**raw_response, "extracted": extracted.model_dump(mode="json")},
        )
        db.add(run)
        db.flush()
    else:
        run.schema_name = type(extracted).__name__
        run.provider = provider
        run.status = ExtractionStatus.COMPLETED
        run.raw_response = {**raw_response, "extracted": extracted.model_dump(mode="json")}
    for field_name in FIELD_NAMES:
        value = getattr(extracted, field_name, None)
        if value is not None:
            db.add(ExtractedField(
                extraction_run_id=run.id,
                document_id=document.id,
                field_name=field_name,
                original_value=value.value,
                confidence=value.confidence,
                page_number=value.page_number,
                source_coordinates=value.coordinates,
                review_status=FieldReviewStatus.MISSING if value.state.value == "missing" else FieldReviewStatus.UNREADABLE if value.state.value == "unreadable" else FieldReviewStatus.UNREVIEWED,
            ))
    if isinstance(extracted, InvoiceExtraction):
        for item in extracted.line_items:
            db.add(InvoiceLineItem(extraction_run_id=run.id, **item.model_dump()))
    for container in getattr(extracted, "container_numbers", []):
        db.add(ContainerNumber(extraction_run_id=run.id, container_number=container))
    document.processing_status = "completed"
    shipment.status = ShipmentStatus.REVIEW_REQUIRED
    return run
