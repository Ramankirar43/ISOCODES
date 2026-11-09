from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.db.models import Correction, ExtractedField, GroundTruthLabel, UserRole

router = APIRouter()


@router.get("/accuracy")
def accuracy_report(db: DbSession, user: CurrentUser) -> dict[str, object]:
    if user.role not in {UserRole.EXECUTIVE, UserRole.MANAGER}:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Only staff can view accuracy reports")
    total_fields = db.scalar(select(func.count(ExtractedField.id))) or 0
    corrected_fields = db.scalar(select(func.count(func.distinct(Correction.field_id)))) or 0
    labels = db.execute(
        select(GroundTruthLabel, ExtractedField)
        .join(ExtractedField, ExtractedField.id == GroundTruthLabel.field_id)
        .order_by(GroundTruthLabel.created_at.desc())
    ).all()
    latest: dict[str, tuple[GroundTruthLabel, ExtractedField]] = {}
    for label, field in labels:
        latest.setdefault(field.id, (label, field))
    evaluations = list(latest.values())
    matches = sum(
        (field.original_value or "").strip().casefold() == (label.ground_truth_value or "").strip().casefold()
        for label, field in evaluations
    )
    field_wise: dict[str, dict[str, int | float | None]] = {}
    supplier_wise: dict[str, dict[str, int | float | None]] = {}
    for label, field in evaluations:
        field_stat = field_wise.setdefault(field.field_name, {"sample_size": 0, "correct": 0, "accuracy": None})
        field_stat["sample_size"] += 1
        field_stat["correct"] += int((field.original_value or "").strip().casefold() == (label.ground_truth_value or "").strip().casefold())
        supplier = label.supplier_name or "Unknown"
        supplier_stat = supplier_wise.setdefault(supplier, {"sample_size": 0, "correct": 0, "accuracy": None})
        supplier_stat["sample_size"] += 1
        supplier_stat["correct"] += int((field.original_value or "").strip().casefold() == (label.ground_truth_value or "").strip().casefold())
    for stat in [*field_wise.values(), *supplier_wise.values()]:
        stat["accuracy"] = stat["correct"] / stat["sample_size"] if stat["sample_size"] else None
    return {
        "evaluation_method": "Human-verified ground truth only",
        "labelled_fields": len(evaluations),
        "evaluation_sample_size": len(evaluations),
        "measured_accuracy": matches / len(evaluations) if evaluations else None,
        "field_wise_accuracy": field_wise,
        "supplier_wise_accuracy": supplier_wise,
        "total_extracted_fields": total_fields,
        "corrected_fields": corrected_fields,
        "note": (
            "Accuracy is unavailable until explicit ground-truth labels are recorded."
            if not evaluations
            else "Measured accuracy is based only on the latest explicit human ground-truth label per field."
        ) + " AI confidence is not accuracy.",
    }
