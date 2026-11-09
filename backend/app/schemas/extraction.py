from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class FieldState(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNREADABLE = "unreadable"


class ExtractedValue(BaseModel):
    state: FieldState
    value: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    page_number: int | None = Field(default=None, ge=1)
    coordinates: dict[str, float] | None = None

    @model_validator(mode="after")
    def require_value_for_present(self) -> "ExtractedValue":
        if self.state == FieldState.PRESENT and not self.value:
            raise ValueError("present extraction fields require a value")
        return self


class InvoiceLineItemExtraction(BaseModel):
    description: str
    quantity: float | None = Field(default=None, ge=0)
    unit_of_measure: str | None = None
    unit_price: float | None = Field(default=None, ge=0)
    hsn_code: str | None = None


class InvoiceExtraction(BaseModel):
    document_type: str = "invoice"
    exporter: ExtractedValue
    importer: ExtractedValue
    invoice_number: ExtractedValue
    invoice_date: date | None = None
    currency: ExtractedValue
    incoterm: ExtractedValue
    package_count: float | None = Field(default=None, ge=0)
    gross_weight_kg: float | None = Field(default=None, ge=0)
    subtotal: float | None = Field(default=None, ge=0)
    taxes: float = Field(default=0, ge=0)
    discounts: float = Field(default=0, ge=0)
    additional_charges: float = Field(default=0, ge=0)
    total: float | None = Field(default=None, ge=0)
    line_items: list[InvoiceLineItemExtraction] = Field(default_factory=list)


class PackingListExtraction(BaseModel):
    document_type: str = "packing_list"
    exporter: ExtractedValue
    importer: ExtractedValue
    item_descriptions: list[str] = Field(default_factory=list)
    total_quantity: float | None = Field(default=None, ge=0)
    package_count: float | None = Field(default=None, ge=0)
    package_type: ExtractedValue
    gross_weight_kg: float | None = Field(default=None, ge=0)
    net_weight_kg: float | None = Field(default=None, ge=0)
    container_numbers: list[str] = Field(default_factory=list)


class BillOfLadingExtraction(BaseModel):
    document_type: str = "bill_of_lading"
    exporter: ExtractedValue
    consignee: ExtractedValue
    notify_party: ExtractedValue
    bill_number: ExtractedValue
    gross_weight_kg: float | None = Field(default=None, ge=0)
    package_count: float | None = Field(default=None, ge=0)
    container_numbers: list[str] = Field(default_factory=list)
