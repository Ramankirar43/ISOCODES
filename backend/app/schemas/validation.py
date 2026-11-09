from pydantic import BaseModel, Field


class ValidationRunRequest(BaseModel):
    invoice_gross_weight_kg: float | None = Field(default=None, ge=0)
    packing_list_gross_weight_kg: float | None = Field(default=None, ge=0)
    bol_gross_weight_kg: float | None = Field(default=None, ge=0)
    invoice_total: float | None = Field(default=None, ge=0)
    invoice_line_items: list[tuple[float | None, float | None]] = Field(default_factory=list)
    invoice_subtotal: float | None = Field(default=None, ge=0)
    invoice_taxes: float = Field(default=0, ge=0)
    invoice_discounts: float = Field(default=0, ge=0)
    invoice_additional_charges: float = Field(default=0, ge=0)
    tolerance_kg: float = Field(default=0.01, ge=0)
    tolerance_currency: float = Field(default=0.01, ge=0)
    invoice_supplier: str | None = None
    packing_list_supplier: str | None = None
    invoice_quantity: float | None = Field(default=None, ge=0)
    packing_list_quantity: float | None = Field(default=None, ge=0)
    invoice_package_count: float | None = Field(default=None, ge=0)
    packing_list_package_count: float | None = Field(default=None, ge=0)
    invoice_containers: list[str] = Field(default_factory=list)
    packing_list_containers: list[str] = Field(default_factory=list)
    bol_containers: list[str] = Field(default_factory=list)
