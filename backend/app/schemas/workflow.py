from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ApprovalDecision, FieldReviewStatus, ValidationStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_type: str
    original_filename: str
    processing_status: str
    created_at: datetime


class FieldCorrectionRequest(BaseModel):
    corrected_value: str | None = None
    reason: str = Field(min_length=3, max_length=1000)


class ValidationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str
    compared_field: str
    status: ValidationStatus
    difference: float | None
    explanation: str
    human_confirmed: bool = False


class CorrectionHistoryResponse(BaseModel):
    id: str
    field_id: str
    field_name: str
    document_name: str
    user_id: str
    original_value: str | None
    corrected_value: str | None
    reason: str
    created_at: datetime


class ApprovalRequest(BaseModel):
    decision: ApprovalDecision
    comments: str | None = Field(default=None, max_length=2000)


class GroundTruthLabelRequest(BaseModel):
    ground_truth_value: str | None = None
