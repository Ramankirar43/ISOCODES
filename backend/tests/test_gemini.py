import json

import httpx
import pytest

from app.schemas.extraction import InvoiceExtraction
from app.services.gemini import GeminiExtractionProvider, GeminiProviderError


def _invoice_payload() -> dict:
    present = {
        "state": "present",
        "value": "Acme Imports",
        "confidence": 0.94,
        "page_number": 1,
        "coordinates": {"x": 10, "y": 20, "width": 100, "height": 15},
    }
    return {
        "document_type": "invoice",
        "exporter": present,
        "importer": present,
        "invoice_number": {**present, "value": "INV-100"},
        "currency": {**present, "value": "USD"},
        "incoterm": {**present, "value": "FOB"},
        "line_items": [
            {"description": "Widget A", "quantity": 2, "unit_of_measure": "pcs", "unit_price": 10, "hsn_code": "1001"},
            {"description": "Widget B", "quantity": 3, "unit_of_measure": "pcs", "unit_price": 20, "hsn_code": "1002"},
        ],
    }


def test_gemini_provider_parses_structured_response() -> None:
    payload = _invoice_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "test-key"
        request_body = request.read()
        assert b"responseSchema" in request_body
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result, raw = GeminiExtractionProvider(api_key="test-key", client=client).extract_structured(
        "invoice text", "invoice", InvoiceExtraction
    )

    assert result["line_items"][1]["description"] == "Widget B"
    assert raw["candidates"]


def test_gemini_provider_rejects_malformed_json() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "not-json"}]}}]},
            )
        )
    )

    with pytest.raises(GeminiProviderError, match="AI_INVALID_RESPONSE"):
        GeminiExtractionProvider(api_key="test-key", client=client).extract_structured(
            "invoice text", "invoice", InvoiceExtraction
        )


def test_gemini_provider_requires_api_key() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    with pytest.raises(GeminiProviderError, match="AI_PROVIDER_UNAVAILABLE"):
        GeminiExtractionProvider(api_key="", client=client).extract_structured(
            "invoice text", "invoice", InvoiceExtraction
        )


def test_gemini_provider_reports_http_failures() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "unavailable"}))
    )

    with pytest.raises(GeminiProviderError, match="AI_PROVIDER_ERROR"):
        GeminiExtractionProvider(api_key="test-key", client=client).extract_structured(
            "invoice text", "invoice", InvoiceExtraction
        )
