import json

import httpx
import pytest

from app.schemas.extraction import InvoiceExtraction
from app.services.ai_provider import (
    AIProviderError,
    AnthropicExtractionProvider,
    OpenAICompatibleExtractionProvider,
)


def _payload() -> dict:
    present = {"state": "present", "value": "Acme", "confidence": 0.9, "page_number": 1}
    return {
        "document_type": "invoice",
        "exporter": present,
        "importer": present,
        "invoice_number": {**present, "value": "INV-1"},
        "currency": {**present, "value": "USD"},
        "incoterm": {**present, "value": "FOB"},
    }


def test_openai_compatible_provider_normalizes_response() -> None:
    payload = json.dumps(_payload())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer key"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": payload}}]})

    provider = OpenAICompatibleExtractionProvider(
        api_key="key",
        model="test-model",
        base_url="https://example.test/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result, _ = provider.extract_structured("text", "invoice", InvoiceExtraction)
    assert result["invoice_number"]["value"] == "INV-1"


def test_anthropic_provider_normalizes_response() -> None:
    payload = json.dumps(_payload())
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"content": [{"type": "text", "text": payload}]})
        )
    )
    provider = AnthropicExtractionProvider(
        api_key="key", model="claude-test", client=client
    )
    result, _ = provider.extract_structured("text", "invoice", InvoiceExtraction)
    assert result["currency"]["value"] == "USD"


def test_provider_rejects_non_object_json() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(["not", "an", "object"])}}]}
            )
        )
    )
    provider = OpenAICompatibleExtractionProvider(
        api_key="key", base_url="https://example.test/v1", client=client
    )
    with pytest.raises(AIProviderError, match="AI_INVALID_RESPONSE"):
        provider.extract_structured("text", "invoice", InvoiceExtraction)
