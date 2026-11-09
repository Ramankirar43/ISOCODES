from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentType, ExtractedField, ExtractionRun, ExtractionStatus

from app.db.models import ValidationStatus


@dataclass(frozen=True)
class ValidationOutcome:
    rule_id: str
    compared_field: str
    status: ValidationStatus
    values_compared: dict[str, float | str | None]
    difference: float | None
    explanation: str


def _latest_extractions(db: Session, shipment_id: str) -> dict[DocumentType, tuple[str, str, dict[str, Any]]]:
    rows = db.execute(
        select(Document, ExtractionRun)
        .join(ExtractionRun, ExtractionRun.document_id == Document.id)
        .where(Document.shipment_id == shipment_id, ExtractionRun.status == ExtractionStatus.COMPLETED)
        .order_by(ExtractionRun.created_at.desc())
    )
    latest: dict[DocumentType, tuple[str, str, dict[str, Any]]] = {}
    for document, run in rows:
        if document.document_type in latest:
            continue
        extracted = (run.raw_response or {}).get("extracted")
        if isinstance(extracted, dict):
            latest[document.document_type] = (document.id, run.id, extracted)
    return latest


def _value(extracted: dict[str, Any], name: str) -> Any:
    value = extracted.get(name)
    if isinstance(value, dict):
        return value.get("value") if value.get("state") == "present" else None
    return value


def build_persisted_validation_inputs(db: Session, shipment_id: str) -> dict[str, Any]:
    latest = _latest_extractions(db, shipment_id)
    invoice = latest.get(DocumentType.INVOICE)
    packing = latest.get(DocumentType.PACKING_LIST)
    bol = latest.get(DocumentType.BILL_OF_LADING)
    invoice_data = invoice[2] if invoice else {}
    packing_data = packing[2] if packing else {}
    bol_data = bol[2] if bol else {}
    for document_id, run_id, extracted in latest.values():
        fields = db.scalars(select(ExtractedField).where(ExtractedField.extraction_run_id == run_id)).all()
        for field in fields:
            if field.corrections:
                corrected = field.corrections[-1].corrected_value
                if field.field_name in extracted and isinstance(extracted[field.field_name], dict):
                    extracted[field.field_name]["value"] = corrected
                    extracted[field.field_name]["state"] = "present" if corrected else "missing"
    line_items = invoice_data.get("line_items", [])
    invoice_quantity = sum(
        float(item["quantity"]) for item in line_items
        if item.get("quantity") is not None
    ) if line_items and all(item.get("quantity") is not None for item in line_items) else None
    return {
        "documents": {name.value: document_id for name, (document_id, _, _) in latest.items()},
        "gross_weights": {
            "invoice": invoice_data.get("gross_weight_kg"),
            "packing_list": packing_data.get("gross_weight_kg"),
            "bill_of_lading": bol_data.get("gross_weight_kg"),
        },
        "net_weights": {"packing_list": packing_data.get("net_weight_kg")},
        "package_counts": {
            "invoice": invoice_data.get("package_count"),
            "packing_list": packing_data.get("package_count"),
            "bill_of_lading": bol_data.get("package_count"),
        },
        "suppliers": {
            "invoice": _value(invoice_data, "exporter"),
            "packing_list": _value(packing_data, "exporter"),
        },
        "quantities": {
            "invoice": invoice_quantity,
            "packing_list": packing_data.get("total_quantity"),
        },
        "containers": {
            "packing_list": packing_data.get("container_numbers", []) or [],
            "bill_of_lading": bol_data.get("container_numbers", []) or [],
        },
        "invoice_arithmetic": {
            "line_items": [
                (item.get("quantity"), item.get("unit_price")) for item in line_items
            ],
            "subtotal": invoice_data.get("subtotal"),
            "taxes": invoice_data.get("taxes"),
            "discounts": invoice_data.get("discounts"),
            "additional_charges": invoice_data.get("additional_charges"),
            "total": invoice_data.get("total"),
        },
    }


def validate_persisted_shipment(
    db: Session,
    shipment_id: str,
    tolerance_kg: Decimal = Decimal("0.01"),
    tolerance_currency: Decimal = Decimal("0.01"),
) -> list[ValidationOutcome]:
    values = build_persisted_validation_inputs(db, shipment_id)
    arithmetic = values["invoice_arithmetic"]
    documents = values["documents"]
    return [
        compare_numbers("gross_weight", "gross_weight_kg", values["gross_weights"], tolerance_kg),
        compare_numbers("net_weight", "net_weight_kg", values["net_weights"], tolerance_kg),
        compare_numbers("package_count", "package_count", values["package_counts"]),
        compare_text("supplier_identity", "supplier", values["suppliers"]),
        compare_numbers("quantity", "quantity", values["quantities"]),
        compare_sets("container_numbers", "container_numbers", values["containers"]),
        validate_invoice_total(tolerance=tolerance_currency, **arithmetic),
    ]


def compare_text(
    rule_id: str,
    field: str,
    values: dict[str, str | None],
) -> ValidationOutcome:
    available = {name: value.strip() for name, value in values.items() if value and value.strip()}
    if len(available) < 2:
        return ValidationOutcome(rule_id, field, ValidationStatus.NOT_AVAILABLE, values, None, "At least two applicable document values are required.")
    normalized = {value.casefold() for value in available.values()}
    passed = len(normalized) == 1
    return ValidationOutcome(
        rule_id, field, ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        values, None,
        "Values match." if passed else "Document values differ; human review is required.",
    )


def compare_sets(
    rule_id: str,
    field: str,
    values: dict[str, list[str]],
) -> ValidationOutcome:
    available = {name: {item.strip().upper() for item in items if item.strip()} for name, items in values.items() if items}
    if len(available) < 2:
        return ValidationOutcome(rule_id, field, ValidationStatus.NOT_AVAILABLE, values, None, "At least two applicable document values are required.")
    passed = len(set(map(frozenset, available.values()))) == 1
    return ValidationOutcome(
        rule_id, field, ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        values, None,
        "Document sets match." if passed else "Document sets differ; human review is required.",
    )


def compare_numbers(
    rule_id: str,
    field: str,
    values: dict[str, float | None],
    tolerance: Decimal = Decimal("0.01"),
) -> ValidationOutcome:
    available = {name: value for name, value in values.items() if value is not None}
    if len(available) < 2:
        return ValidationOutcome(
            rule_id, field, ValidationStatus.NOT_AVAILABLE, values, None,
            "At least two applicable document values are required.",
        )
    reference = Decimal(str(next(iter(available.values()))))
    difference = max(abs(reference - Decimal(str(value))) for value in available.values())
    difference = difference.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    status = ValidationStatus.PASSED if difference <= tolerance else ValidationStatus.FAILED
    explanation = "Values are within the configured tolerance." if status == ValidationStatus.PASSED else "Values differ beyond the configured tolerance; human review is required."
    return ValidationOutcome(rule_id, field, status, values, float(difference), explanation)


def validate_invoice_total(
    line_items: list[tuple[float | None, float | None]],
    subtotal: float | None,
    taxes: float,
    discounts: float,
    additional_charges: float,
    total: float | None,
    tolerance: Decimal = Decimal("0.01"),
) -> ValidationOutcome:
    if total is None or not line_items:
        return ValidationOutcome(
            "invoice_total", "invoice_total", ValidationStatus.NOT_AVAILABLE,
            {"calculated": None, "document_total": total}, None,
            "Line items and invoice total are required.",
        )
    calculated_lines = sum(Decimal(str(qty)) * Decimal(str(price)) for qty, price in line_items if qty is not None and price is not None)
    base = Decimal(str(subtotal)) if subtotal is not None else calculated_lines
    calculated = base + Decimal(str(taxes)) + Decimal(str(additional_charges)) - Decimal(str(discounts))
    difference = abs(calculated - Decimal(str(total))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    status = ValidationStatus.PASSED if difference <= tolerance else ValidationStatus.FAILED
    return ValidationOutcome(
        "invoice_total", "invoice_total", status,
        {"calculated": float(calculated), "document_total": total}, float(difference),
        "Invoice arithmetic is consistent." if status == ValidationStatus.PASSED else "Invoice total does not reconcile with line items and charges.",
    )
