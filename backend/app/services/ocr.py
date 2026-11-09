from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OCRPage:
    page_number: int
    text: str
    confidence: float | None
    coordinates: list[dict[str, float]]


@dataclass(frozen=True)
class OCRResult:
    page_count: int
    text: str
    pages: list[OCRPage]


def preprocess_image(image: Any) -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise ValueError("OCR_UNAVAILABLE: install the processing extras for OpenCV") from exc
    if image is None:
        raise ValueError("OCR_INVALID_IMAGE: unable to decode image")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    thresholded = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    return thresholded


def _coordinates(box: Any) -> dict[str, float]:
    points = [(float(point[0]), float(point[1])) for point in box]
    return {
        "x": min(point[0] for point in points),
        "y": min(point[1] for point in points),
        "width": max(point[0] for point in points) - min(point[0] for point in points),
        "height": max(point[1] for point in points) - min(point[1] for point in points),
    }


class PaddleOCRProvider:
    def __init__(self, language: str = "en") -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ValueError("OCR_UNAVAILABLE: install the processing extras for PaddleOCR") from exc
        self._ocr = PaddleOCR(lang=language, use_doc_orientation_classify=False,
                              use_doc_unwarping=False, use_textline_orientation=False)

    def _recognize(self, image: Any) -> tuple[str, float | None, list[dict[str, float]]]:
        try:
            output = self._ocr.ocr(image, cls=True)
            lines = output[0] if output else []
            texts: list[str] = []
            scores: list[float] = []
            coordinates: list[dict[str, float]] = []
            for line in lines:
                box, result = line
                value, score = result
                if value:
                    texts.append(str(value))
                    scores.append(float(score))
                    coordinates.append(_coordinates(box))
            confidence = sum(scores) / len(scores) if scores else None
            return "\n".join(texts), confidence, coordinates
        except AttributeError:
            results = self._ocr.predict(image)
            texts = []
            scores = []
            coordinates = []
            for result in results:
                data = result.json if hasattr(result, "json") else result
                if callable(data):
                    data = data()
                data = data.get("res", data) if isinstance(data, dict) else {}
                for value, score in zip(data.get("rec_texts", []), data.get("rec_scores", [])):
                    texts.append(str(value))
                    scores.append(float(score))
                for box in data.get("rec_polys", []):
                    coordinates.append(_coordinates(box))
            confidence = sum(scores) / len(scores) if scores else None
            return "\n".join(texts), confidence, coordinates

    def extract(self, path: Path, dpi: int = 200) -> OCRResult:
        try:
            import cv2
            import fitz
        except ImportError as exc:
            raise ValueError("OCR_UNAVAILABLE: install the processing extras for OpenCV and PyMuPDF") from exc
        pages: list[OCRPage] = []
        if path.suffix.lower() == ".pdf":
            try:
                pdf = fitz.open(path)
            except (fitz.FileDataError, OSError) as exc:
                raise ValueError("INVALID_DOCUMENT: unable to open PDF") from exc
            with pdf:
                rendered = [
                    page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                    for page in pdf
                ]
            for number, pixmap in enumerate(rendered, start=1):
                image = cv2.imdecode(
                    __import__("numpy").frombuffer(pixmap.tobytes("png"), dtype="uint8"),
                    cv2.IMREAD_COLOR,
                )
                text, confidence, coordinates = self._recognize(preprocess_image(image))
                pages.append(OCRPage(number, text, confidence, coordinates))
        elif path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            image = cv2.imread(str(path))
            text, confidence, coordinates = self._recognize(preprocess_image(image))
            pages.append(OCRPage(1, text, confidence, coordinates))
        else:
            raise ValueError("OCR_REQUIRED: unsupported document format")
        text = "\n".join(page.text for page in pages).strip()
        if not text:
            raise ValueError("OCR_EMPTY: no readable text found; use manual entry")
        return OCRResult(len(pages), text, pages)
