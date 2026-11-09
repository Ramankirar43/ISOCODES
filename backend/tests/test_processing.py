from pathlib import Path

import fitz

from app.services.processing import UnavailableOCRProvider, extract_digital_pdf_text
from app.services.ocr import OCRPage, OCRResult


def test_extract_digital_pdf_text(tmp_path: Path) -> None:
    path = tmp_path / "invoice.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Invoice INV-24811\nGross weight: 3120 kg")
    pdf.save(path)
    pdf.close()

    page_count, text = extract_digital_pdf_text(path)

    assert page_count == 1
    assert "INV-24811" in text
    assert "3120 kg" in text


def test_scanned_pdf_requires_ocr(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(path)
    pdf.close()

    try:
        extract_digital_pdf_text(path)
    except ValueError as error:
        assert str(error).startswith("OCR_REQUIRED:")
    else:
        raise AssertionError("scanned PDF should require OCR")


def test_unconfigured_ocr_is_explicit() -> None:
    try:
        UnavailableOCRProvider().extract_text(Path("scan.png"))
    except ValueError as error:
        assert str(error) == "OCR_REQUIRED: no OCR provider is configured"
    else:
        raise AssertionError("unconfigured OCR should fail explicitly")


def test_ocr_result_preserves_confidence_and_coordinates() -> None:
    result = OCRResult(
        page_count=1,
        text="INV-1",
        pages=[OCRPage(1, "INV-1", 0.96, [{"x": 10, "y": 20, "width": 40, "height": 12}])],
    )

    assert result.pages[0].confidence == 0.96
    assert result.pages[0].coordinates[0]["width"] == 40
