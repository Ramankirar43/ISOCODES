from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.extraction import ExtractedValue, FieldState, InvoiceExtraction
from app.services.validation import compare_numbers, validate_invoice_total
from app.db.models import ValidationStatus


def present(value: str) -> dict:
    return {"state": FieldState.PRESENT, "value": value, "confidence": 0.94, "page_number": 1}


def test_invoice_schema_supports_multiple_items() -> None:
    invoice = InvoiceExtraction(
        exporter=present("Company B"),
        importer=present("Importer"),
        invoice_number=present("INV-1"),
        currency=present("USD"),
        incoterm=present("FOB"),
        line_items=[
            {"description": "LED panel", "quantity": 2400, "unit_price": 6.8, "hsn_code": "9405"},
            {"description": "Cable", "quantity": 10, "unit_price": 2.5},
        ],
        total=16345,
    )
    assert len(invoice.line_items) == 2


def test_present_value_requires_text() -> None:
    with pytest.raises(ValidationError):
        ExtractedValue(state=FieldState.PRESENT)


def test_invoice_total_accounts_for_charges() -> None:
    result = validate_invoice_total(
        line_items=[(2, 10), (1, 5)],
        subtotal=None,
        taxes=2,
        discounts=1,
        additional_charges=3,
        total=29,
        tolerance=Decimal("0.01"),
    )
    assert result.status == ValidationStatus.PASSED


def test_weight_mismatch_is_failed() -> None:
    result = compare_numbers(
        "gross_weight",
        "gross_weight_kg",
        {"invoice": 3120, "packing_list": 3165, "bill_of_lading": 3165},
    )
    assert result.status == ValidationStatus.FAILED
    assert result.difference == 45


def test_invoice_schema_includes_weight_and_packages() -> None:
    invoice = InvoiceExtraction(
        exporter=present("Company B"),
        importer=present("Importer"),
        invoice_number=present("INV-1"),
        currency=present("USD"),
        incoterm=present("FOB"),
        package_count=48,
        gross_weight_kg=3120,
        line_items=[{"description": "LED panel", "quantity": 2400, "unit_price": 6.8}],
        total=16320,
    )
    assert invoice.gross_weight_kg == 3120
    assert invoice.package_count == 48


def test_missing_document_values_are_not_available() -> None:
    from app.services.validation import compare_numbers

    result = compare_numbers("net_weight", "net_weight_kg", {"packing_list": 10, "bill_of_lading": None})

    assert result.status == ValidationStatus.NOT_AVAILABLE
