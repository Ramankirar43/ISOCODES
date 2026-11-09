import csv
import io
import json
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.shipments import can_access_shipment
from app.core.config import settings
from app.db.models import (
    Approval,
    ApprovalDecision,
    ContainerNumber,
    Correction,
    Document,
    DocumentType,
    DocumentVersion,
    ExtractedField,
    ExtractionRun,
    ExtractionStatus,
    ExportLog,
    GroundTruthLabel,
    FieldReviewStatus,
    InvoiceLineItem,
    Shipment,
    ShipmentStatus,
    UserRole,
    ValidationResult,
    ValidationStatus,
)
from app.schemas.workflow import (
    ApprovalRequest,
    CorrectionHistoryResponse,
    DocumentResponse,
    FieldCorrectionRequest,
    GroundTruthLabelRequest,
    ValidationResponse,
)
from app.schemas.validation import ValidationRunRequest
from app.services.storage import save_private_upload
from app.services.processing import process_document
from app.services.validation import build_persisted_validation_inputs, validate_persisted_shipment
from app.services.extraction import persist_extraction as persist_validated_extraction, validate_extraction

router = APIRouter()

REVIEWED_FIELD_STATUSES = {FieldReviewStatus.CONFIRMED, FieldReviewStatus.CORRECTED}
BLOCKING_VALIDATION_STATUSES = {ValidationStatus.FAILED, ValidationStatus.NEEDS_REVIEW}


def get_accessible_shipment(db: DbSession, shipment_id: str, user: CurrentUser) -> Shipment:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if not can_access_shipment(user, shipment):
        raise HTTPException(status_code=403, detail="Shipment access denied")
    return shipment


def approval_blockers(db: DbSession, shipment: Shipment) -> list[str]:
    required_types = {DocumentType.INVOICE, DocumentType.PACKING_LIST, DocumentType.BILL_OF_LADING}
    available_types = set(db.scalars(select(Document.document_type).where(Document.shipment_id == shipment.id)).all())
    blockers = [f"Missing required document: {document_type.value}" for document_type in required_types - available_types]
    required_fields = {
        DocumentType.INVOICE: {"exporter", "importer", "invoice_number", "currency", "incoterm"},
        DocumentType.PACKING_LIST: {"exporter", "importer", "package_type"},
        DocumentType.BILL_OF_LADING: {"exporter", "consignee", "bill_number"},
    }
    fields = db.execute(
        select(ExtractedField, Document.document_type)
        .join(Document, Document.id == ExtractedField.document_id)
        .where(Document.shipment_id == shipment.id)
    )
    seen = {document_type: set() for document_type in required_types}
    for field, document_type in fields:
        seen[document_type].add(field.field_name)
        if field.review_status in {FieldReviewStatus.UNREVIEWED, FieldReviewStatus.MISSING, FieldReviewStatus.UNREADABLE}:
            blockers.append(f"Unresolved field: {field.field_name}")
        if (
            field.confidence is not None
            and field.confidence < 0.70
            and field.review_status not in REVIEWED_FIELD_STATUSES
        ):
            blockers.append(f"Low-confidence field requires confirmation: {field.field_name}")
    for document_type, names in required_fields.items():
        for field_name in names - seen[document_type]:
            blockers.append(f"Missing mandatory field: {field_name}")
    validations = db.scalars(select(ValidationResult).where(ValidationResult.shipment_id == shipment.id)).all()
    if not validations:
        blockers.append("Validation has not been run")
    blockers.extend(
        f"Validation {result.rule_id}: {result.status.value}"
        for result in validations
        if result.status in BLOCKING_VALIDATION_STATUSES and not result.human_confirmed
    )
    return blockers


def export_rows(db: DbSession, shipment: Shipment) -> list[dict[str, object]]:
    documents = db.scalars(select(Document).where(Document.shipment_id == shipment.id)).all()
    extracted: dict[DocumentType, dict] = {}
    for document in documents:
        run = db.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.document_id == document.id, ExtractionRun.status == ExtractionStatus.COMPLETED)
            .order_by(ExtractionRun.created_at.desc())
        )
        if run and isinstance(run.raw_response, dict) and isinstance(run.raw_response.get("extracted"), dict):
            extracted[document.document_type] = json.loads(json.dumps(run.raw_response["extracted"]))
            fields = db.scalars(select(ExtractedField).where(ExtractedField.extraction_run_id == run.id)).all()
            for field in fields:
                if field.corrections and field.field_name in extracted[document.document_type]:
                    value = extracted[document.document_type][field.field_name]
                    if isinstance(value, dict):
                        corrected = field.corrections[-1].corrected_value
                        value["value"] = corrected
                        value["state"] = "present" if corrected else "missing"
    invoice = extracted.get(DocumentType.INVOICE, {})
    packing = extracted.get(DocumentType.PACKING_LIST, {})
    bol = extracted.get(DocumentType.BILL_OF_LADING, {})
    def value(data: dict, name: str) -> object:
        item = data.get(name)
        return item.get("value") if isinstance(item, dict) else item
    rows = invoice.get("line_items") or [{}]
    return [{
        "shipment_number": shipment.shipment_number,
        "importer_id": shipment.importer_id,
        "supplier_name": shipment.supplier_name or value(invoice, "exporter") or value(packing, "exporter") or "",
        "consignee": value(bol, "consignee") or "",
        "invoice_number": value(invoice, "invoice_number") or "",
        "invoice_date": invoice.get("invoice_date") or "",
        "currency": value(invoice, "currency") or "",
        "incoterm": value(invoice, "incoterm") or "",
        "line_item_description": item.get("description", ""),
        "hsn": item.get("hsn_code", ""),
        "quantity": item.get("quantity", ""),
        "unit_price": item.get("unit_price", ""),
        "taxes": invoice.get("taxes", ""),
        "discounts": invoice.get("discounts", ""),
        "additional_charges": invoice.get("additional_charges", ""),
        "invoice_total": invoice.get("total", ""),
        "package_count": packing.get("package_count", "") or bol.get("package_count", "") or invoice.get("package_count", ""),
        "gross_weight_kg": packing.get("gross_weight_kg", "") or bol.get("gross_weight_kg", "") or invoice.get("gross_weight_kg", ""),
        "net_weight_kg": packing.get("net_weight_kg", ""),
        "container_numbers": ", ".join(packing.get("container_numbers", []) or bol.get("container_numbers", []) or []),
    } for item in rows]


@router.post("/{shipment_id}/documents", response_model=DocumentResponse, status_code=201)
def upload_document(
    shipment_id: str,
    document_type: DocumentType,
    file: UploadFile,
    db: DbSession,
    user: CurrentUser,
) -> Document:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role == UserRole.IMPORTER and user.importer_id != shipment.importer_id:
        raise HTTPException(status_code=403, detail="Importer shipment access denied")
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER, UserRole.IMPORTER}:
        raise HTTPException(status_code=403, detail="User cannot upload shipment documents")
    key, digest, _ = save_private_upload(file)
    document = Document(
        shipment_id=shipment.id,
        document_type=document_type,
        original_filename=Path(file.filename or "document").name,
        storage_key=key,
        processing_status="uploaded",
    )
    db.add(document)
    db.flush()
    db.add(DocumentVersion(document_id=document.id, version_number=1, storage_key=key, sha256=digest))
    shipment.status = ShipmentStatus.UPLOADED
    db.commit()
    db.refresh(document)
    return document


@router.get("/{shipment_id}/documents", response_model=list[DocumentResponse])
def list_documents(shipment_id: str, db: DbSession, user: CurrentUser) -> list[Document]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    return list(db.scalars(select(Document).where(Document.shipment_id == shipment.id).order_by(Document.created_at)))


@router.get("/{shipment_id}/documents/{document_id}/content")
def stream_document_content(shipment_id: str, document_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    shipment = get_accessible_shipment(db, shipment_id, user)
    document = db.get(Document, document_id)
    if document is None or document.shipment_id != shipment.id:
        raise HTTPException(status_code=404, detail="Document not found")
    root = Path(settings.local_storage_path).resolve()
    path = (root / document.storage_key).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Document content not found")
    media_types = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    media_type = media_types.get(path.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=415, detail="Unsupported document format")
    return FileResponse(path, media_type=media_type, filename=document.original_filename)


@router.get("/{shipment_id}/fields")
def list_fields(shipment_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    rows = db.execute(
        select(ExtractedField, Document.original_filename)
        .join(Document, Document.id == ExtractedField.document_id)
        .where(Document.shipment_id == shipment.id)
        .order_by(ExtractedField.created_at)
    )
    return [
        {
            "id": field.id,
            "document_id": field.document_id,
            "document_name": filename,
            "field_name": field.field_name,
            "original_value": field.original_value,
            "confidence": field.confidence,
            "page_number": field.page_number,
            "source_coordinates": field.source_coordinates,
            "review_status": field.review_status.value,
            "corrected_value": field.corrections[-1].corrected_value if field.corrections else None,
        }
        for field, filename in rows
    ]


@router.post("/{shipment_id}/documents/{document_id}/process")
def process_uploaded_document(
    shipment_id: str,
    document_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | int | None]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can process shipment documents")
    document = db.get(Document, document_id)
    if document is None or document.shipment_id != shipment.id:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        result = process_document(db, document)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "document_id": document.id,
        "status": result.status,
        "extraction_run_id": result.extraction_run_id,
        "page_count": result.page_count,
        "text_length": result.text_length,
        "error": result.error,
    }


@router.post("/{shipment_id}/documents/{document_id}/extraction", status_code=201)
def persist_extraction(
    shipment_id: str,
    document_id: str,
    payload: dict,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can persist extraction")
    document = db.get(Document, document_id)
    if document is None or document.shipment_id != shipment.id:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        extracted = validate_extraction(document.document_type, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid extraction response: {exc}") from exc
    run = persist_validated_extraction(
        db, document, shipment, extracted, "manual-validated", extracted.model_dump(mode="json")
    )
    db.commit()
    return {"extraction_run_id": run.id, "status": run.status.value}


@router.patch("/{shipment_id}/fields/{field_id}")
def correct_field(
    shipment_id: str,
    field_id: str,
    payload: FieldCorrectionRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can correct fields")
    field = db.get(ExtractedField, field_id)
    if field is None or db.get(Document, field.document_id).shipment_id != shipment.id:
        raise HTTPException(status_code=404, detail="Field not found")
    db.add(Correction(field_id=field.id, user_id=user.id, original_value=field.original_value, corrected_value=payload.corrected_value, reason=payload.reason))
    field.review_status = FieldReviewStatus.CORRECTED
    db.query(ValidationResult).filter(ValidationResult.shipment_id == shipment.id).delete()
    db.commit()
    return {"field_id": field.id, "review_status": field.review_status.value}


@router.post("/{shipment_id}/fields/{field_id}/confirm")
def confirm_field(shipment_id: str, field_id: str, db: DbSession, user: CurrentUser) -> dict[str, str]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can confirm fields")
    field = db.get(ExtractedField, field_id)
    document = db.get(Document, field.document_id) if field else None
    if field is None or document is None or document.shipment_id != shipment.id:
        raise HTTPException(status_code=404, detail="Field not found")
    if field.review_status in {FieldReviewStatus.MISSING, FieldReviewStatus.UNREADABLE}:
        raise HTTPException(status_code=409, detail="Missing or unreadable fields cannot be confirmed")
    field.review_status = FieldReviewStatus.CONFIRMED
    db.query(ValidationResult).filter(ValidationResult.shipment_id == shipment.id).delete()
    db.commit()
    return {"field_id": field.id, "review_status": field.review_status.value}


@router.post("/{shipment_id}/validate", response_model=list[ValidationResponse])
def validate_shipment(
    shipment_id: str,
    payload: ValidationRunRequest,
    db: DbSession,
    user: CurrentUser,
) -> list[ValidationResult]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can validate shipments")
    db.query(ValidationResult).filter(ValidationResult.shipment_id == shipment.id).delete()
    outcomes = validate_persisted_shipment(
        db,
        shipment.id,
        tolerance_kg=Decimal(str(payload.tolerance_kg)),
        tolerance_currency=Decimal(str(payload.tolerance_currency)),
    )
    source_documents = list(build_persisted_validation_inputs(db, shipment.id)["documents"].values())
    results = [
        ValidationResult(
            shipment_id=shipment.id,
            rule_id=outcome.rule_id,
            compared_field=outcome.compared_field,
            source_documents=source_documents,
            values_compared=outcome.values_compared,
            difference=outcome.difference,
            status=outcome.status,
            explanation=outcome.explanation,
        )
        for outcome in outcomes
    ]
    db.add_all(results)
    db.commit()
    return results


@router.get("/{shipment_id}/validations", response_model=list[ValidationResponse])
def list_validations(shipment_id: str, db: DbSession, user: CurrentUser) -> list[ValidationResult]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    return list(db.scalars(select(ValidationResult).where(ValidationResult.shipment_id == shipment.id)))


@router.post("/{shipment_id}/validations/{validation_id}/confirm", response_model=ValidationResponse)
def confirm_validation(
    shipment_id: str,
    validation_id: str,
    db: DbSession,
    user: CurrentUser,
) -> ValidationResult:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can confirm validations")
    result = db.get(ValidationResult, validation_id)
    if result is None or result.shipment_id != shipment.id:
        raise HTTPException(status_code=404, detail="Validation result not found")
    if result.status not in BLOCKING_VALIDATION_STATUSES:
        raise HTTPException(status_code=409, detail="Only failed or needs-review validations can be confirmed")
    result.human_confirmed = True
    db.commit()
    db.refresh(result)
    return result


@router.get("/{shipment_id}/corrections", response_model=list[CorrectionHistoryResponse])
def list_corrections(shipment_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    rows = db.execute(
        select(Correction, ExtractedField, Document.original_filename)
        .join(ExtractedField, ExtractedField.id == Correction.field_id)
        .join(Document, Document.id == ExtractedField.document_id)
        .where(Document.shipment_id == shipment.id)
        .order_by(Correction.created_at.desc())
    )
    return [
        {
            "id": correction.id,
            "field_id": field.id,
            "field_name": field.field_name,
            "document_name": filename,
            "user_id": correction.user_id,
            "original_value": correction.original_value,
            "corrected_value": correction.corrected_value,
            "reason": correction.reason,
            "created_at": correction.created_at,
        }
        for correction, field, filename in rows
    ]


@router.post("/{shipment_id}/submit", response_model=dict[str, str])
def submit_for_approval(shipment_id: str, db: DbSession, user: CurrentUser) -> dict[str, str]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role != UserRole.EXECUTIVE:
        raise HTTPException(status_code=403, detail="Only executives can submit shipments")
    blockers = approval_blockers(db, shipment)
    if blockers:
        raise HTTPException(status_code=409, detail={"message": "Shipment cannot be submitted", "blockers": blockers})
    shipment.status = ShipmentStatus.PENDING_APPROVAL
    db.commit()
    return {"shipment_id": shipment.id, "status": shipment.status.value}


@router.post("/{shipment_id}/approve", response_model=dict[str, str])
def approve_shipment(shipment_id: str, payload: ApprovalRequest, db: DbSession, user: CurrentUser) -> dict[str, str]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role != UserRole.MANAGER:
        raise HTTPException(status_code=403, detail="Only managers can approve shipments")
    if shipment.status != ShipmentStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail="Shipment is not pending approval")
    if payload.decision == ApprovalDecision.APPROVED:
        blockers = approval_blockers(db, shipment)
        if blockers:
            raise HTTPException(status_code=409, detail={"message": "Shipment cannot be approved", "blockers": blockers})
        shipment.status = ShipmentStatus.APPROVED
    else:
        shipment.status = ShipmentStatus.REJECTED
    db.add(Approval(shipment_id=shipment.id, manager_id=user.id, decision=payload.decision, comments=payload.comments))
    db.commit()
    return {"shipment_id": shipment.id, "status": shipment.status.value}


@router.get("/{shipment_id}/export.csv")
def export_csv(shipment_id: str, db: DbSession, user: CurrentUser) -> StreamingResponse:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can export shipments")
    if shipment.status not in {ShipmentStatus.APPROVED, ShipmentStatus.EXPORTED}:
        raise HTTPException(status_code=409, detail="Only approved shipments can be exported")
    blockers = approval_blockers(db, shipment)
    if blockers:
        raise HTTPException(status_code=409, detail={"message": "Export blocked", "blockers": blockers})
    output = io.StringIO()
    rows = export_rows(db, shipment)
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    db.add(ExportLog(
        shipment_id=shipment.id,
        user_id=user.id,
        export_format="csv",
        storage_key=f"exports/{shipment.shipment_number}.csv",
    ))
    shipment.status = ShipmentStatus.EXPORTED
    db.commit()
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{shipment.shipment_number}.csv"'})


@router.get("/{shipment_id}/export.xlsx")
def export_xlsx(shipment_id: str, db: DbSession, user: CurrentUser) -> StreamingResponse:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can export shipments")
    if shipment.status not in {ShipmentStatus.APPROVED, ShipmentStatus.EXPORTED}:
        raise HTTPException(status_code=409, detail="Only approved shipments can be exported")
    if approval_blockers(db, shipment):
        raise HTTPException(status_code=409, detail="Export blocked until approval requirements are complete")
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Excel export requires the export dependencies") from exc
    workbook = Workbook()
    sheet = workbook.active
    rows = export_rows(db, shipment)
    headers = list(rows[0])
    sheet.append(headers)
    for row in rows:
        sheet.append([row[header] for header in headers])
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    db.add(ExportLog(shipment_id=shipment.id, user_id=user.id, export_format="xlsx", storage_key=f"exports/{shipment.shipment_number}.xlsx"))
    shipment.status = ShipmentStatus.EXPORTED
    db.commit()
    return StreamingResponse(iter([output.getvalue()]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{shipment.shipment_number}.xlsx"'})


@router.post("/{shipment_id}/fields/{field_id}/ground-truth")
def label_ground_truth(
    shipment_id: str,
    field_id: str,
    payload: GroundTruthLabelRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    shipment = get_accessible_shipment(db, shipment_id, user)
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only staff can label ground truth")
    field = db.get(ExtractedField, field_id)
    document = db.get(Document, field.document_id) if field else None
    if field is None or document is None or document.shipment_id != shipment.id:
        raise HTTPException(status_code=404, detail="Field not found")
    db.add(GroundTruthLabel(field_id=field.id, reviewer_id=user.id, supplier_name=shipment.supplier_name, ground_truth_value=payload.ground_truth_value))
    db.commit()
    return {"field_id": field.id, "status": "labelled"}
