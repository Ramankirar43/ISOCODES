from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import fitz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, ExtractionRun, ExtractionStatus, Shipment
from app.services.extraction import SCHEMAS, persist_extraction, validate_extraction
from app.services.ai_provider import AIProviderError, create_ai_provider
from app.services.ocr import OCRResult, PaddleOCRProvider


@dataclass(frozen=True)
class ProcessingResult:
    status: str
    extraction_run_id: str
    page_count: int
    text_length: int
    error: str | None = None


class OCRProvider(Protocol):
    def extract(self, path: Path, dpi: int = 200) -> OCRResult:
        ...


class VisionExtractionProvider(Protocol):
    def extract_structured(self, text: str, document_type: str, schema: type) -> tuple[dict, dict]:
        ...


class UnavailableOCRProvider:
    def extract_text(self, path: Path) -> tuple[int, str]:
        raise ValueError("OCR_REQUIRED: no OCR provider is configured")

    def extract(self, path: Path, dpi: int = 200) -> OCRResult:
        raise ValueError("OCR_REQUIRED: no OCR provider is configured")


class UnavailableVisionProvider:
    def extract_structured(self, text: str, document_type: str, schema: type) -> tuple[dict, dict]:
        raise ValueError("AI_PROVIDER_UNAVAILABLE: no vision extraction provider is configured")


def extract_digital_pdf_text(path: Path) -> tuple[int, str]:
    if path.suffix.lower() != ".pdf":
        raise ValueError("OCR_REQUIRED: image documents require an OCR provider")
    try:
        pdf = fitz.open(path)
    except (fitz.FileDataError, OSError) as exc:
        raise ValueError("INVALID_DOCUMENT: unable to open PDF") from exc
    with pdf:
        pages = [page.get_text("text") for page in pdf]
        text = "\n".join(pages).strip()
        if not text:
            raise ValueError("OCR_REQUIRED: PDF contains no extractable digital text")
        return len(pages), text


def extract_document_text(path: Path) -> tuple[int, str, dict]:
    try:
        return (*extract_digital_pdf_text(path), {"source": "digital_pdf"})
    except ValueError as error:
        if not str(error).startswith("OCR_REQUIRED:"):
            raise
    try:
        result = PaddleOCRProvider(settings.ocr_language).extract(path, settings.ocr_dpi)
    except ValueError:
        raise
    return result.page_count, result.text, {
        "source": "paddleocr",
        "pages": [
            {
                "page_number": page.page_number,
                "confidence": page.confidence,
                "coordinates": page.coordinates,
            }
            for page in result.pages
        ],
    }


def process_document(db: Session, document: Document) -> ProcessingResult:
    if document.processing_attempts >= settings.max_processing_attempts:
        raise ValueError("RETRY_LIMIT_REACHED: document processing retry limit exceeded")
    document.processing_attempts += 1
    document.processing_status = "processing"
    document.processing_error = None
    run = ExtractionRun(
        document_id=document.id,
        schema_name=document.document_type.value,
        provider=settings.ai_provider,
        status=ExtractionStatus.PENDING,
        attempt=document.processing_attempts,
    )
    db.add(run)
    db.flush()
    path = Path(settings.local_storage_path).resolve() / Path(document.storage_key).name
    try:
        page_count, text, text_metadata = extract_document_text(path)
    except ValueError as exc:
        run.status = ExtractionStatus.FAILED
        run.error_message = str(exc)
        document.processing_status = "failed"
        document.processing_error = str(exc)
        db.commit()
        return ProcessingResult("failed", run.id, 0, 0, str(exc))
    shipment = db.get(Shipment, document.shipment_id)
    if shipment is None:
        raise ValueError("INVALID_DOCUMENT: parent shipment not found")
    try:
        provider = create_ai_provider()
        payload, provider_response = provider.extract_structured(
            text, document.document_type.value, SCHEMAS[document.document_type]
        )
        extracted = validate_extraction(document.document_type, payload)
    except (AIProviderError, ValueError) as exc:
        run.status = ExtractionStatus.FAILED
        run.error_message = str(exc)
        run.raw_response = {"text": text, "page_count": page_count, "ocr": text_metadata}
        document.processing_status = "failed"
        document.processing_error = str(exc)
        db.commit()
        return ProcessingResult("failed", run.id, page_count, len(text), str(exc))
    persisted_run = persist_extraction(
        db,
        document,
        shipment,
        extracted,
        settings.ai_provider,
        {
            "text": text,
            "page_count": page_count,
            "ocr": text_metadata,
            "provider_response": provider_response,
        },
        run,
    )
    db.commit()
    return ProcessingResult("completed", persisted_run.id, page_count, len(text))
