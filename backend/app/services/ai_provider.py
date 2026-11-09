import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings


class AIProviderError(ValueError):
    pass


def _json_text(value: str) -> dict[str, Any]:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIProviderError("AI_INVALID_RESPONSE: provider returned invalid structured JSON") from exc
    if not isinstance(parsed, dict):
        raise AIProviderError("AI_INVALID_RESPONSE: provider response must be a JSON object")
    return parsed


def _prompt(text: str, document_type: str, schema: type[BaseModel]) -> str:
    return (
        "Extract customs document data from the supplied text. Return only JSON matching this schema. "
        "For unknown values use state='missing'; for unreadable values use state='unreadable'. "
        "Never infer or invent values. Document type: "
        f"{document_type}.\nJSON schema:\n{json.dumps(schema.model_json_schema())}\n"
        f"Document text:\n{text}"
    )


class AIExtractionProvider(ABC):
    provider_name: str

    @abstractmethod
    def extract_structured(
        self, text: str, document_type: str, schema: type[BaseModel]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ...


class HTTPAIProvider(AIExtractionProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or settings.ai_api_key or settings.gemini_api_key
        self.model = model or settings.ai_model or settings.gemini_model
        self.base_url = (base_url or settings.ai_base_url or "").rstrip("/")
        self.client = client or httpx.Client(timeout=settings.ai_timeout_seconds)

    def _request(
        self, method: str, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        if not self.api_key:
            raise AIProviderError("AI_PROVIDER_UNAVAILABLE: CUSTOMS_AI_API_KEY is not configured")
        try:
            response = self.client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIProviderError(f"AI_PROVIDER_ERROR: {self.provider_name} request failed") from exc
        if not isinstance(body, dict):
            raise AIProviderError("AI_INVALID_RESPONSE: provider response must be an object")
        return body


class GeminiExtractionProvider(HTTPAIProvider):
    provider_name = "gemini"

    def extract_structured(self, text: str, document_type: str, schema: type[BaseModel]) -> tuple[dict, dict]:
        base_url = self.base_url or settings.gemini_base_url.rstrip("/")
        url = f"{base_url}/models/{self.model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": _prompt(text, document_type, schema)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema.model_json_schema(),
            },
        }
        response_body = self._request("POST", url, params={"key": self.api_key}, json=body)
        try:
            parts = response_body["candidates"][0]["content"]["parts"]
            response_text = "".join(part["text"] for part in parts if "text" in part).strip()
            if not response_text:
                raise KeyError("empty response")
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("AI_INVALID_RESPONSE: Gemini returned no text") from exc
        return _json_text(response_text), response_body


class OpenAICompatibleExtractionProvider(HTTPAIProvider):
    provider_name = "openai-compatible"

    def extract_structured(self, text: str, document_type: str, schema: type[BaseModel]) -> tuple[dict, dict]:
        if not self.base_url:
            raise AIProviderError("AI_CONFIGURATION_ERROR: CUSTOMS_AI_BASE_URL is required")
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": _prompt(text, document_type, schema)}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        response_body = self._request(
            "POST", url, headers={"Authorization": f"Bearer {self.api_key}"}, json=body
        )
        try:
            response_text = response_body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("AI_INVALID_RESPONSE: OpenAI-compatible response has no message") from exc
        return _json_text(response_text), response_body


class AnthropicExtractionProvider(HTTPAIProvider):
    provider_name = "anthropic"

    def extract_structured(self, text: str, document_type: str, schema: type[BaseModel]) -> tuple[dict, dict]:
        base_url = self.base_url or "https://api.anthropic.com/v1"
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0,
            "messages": [{"role": "user", "content": _prompt(text, document_type, schema)}],
        }
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": settings.ai_anthropic_version,
            "content-type": "application/json",
        }
        response_body = self._request("POST", f"{base_url}/messages", headers=headers, json=body)
        try:
            response_text = "".join(block["text"] for block in response_body["content"] if block["type"] == "text")
        except (KeyError, TypeError) as exc:
            raise AIProviderError("AI_INVALID_RESPONSE: Anthropic response has no text") from exc
        return _json_text(response_text), response_body


def create_ai_provider() -> AIExtractionProvider:
    provider = settings.ai_provider.strip().lower()
    if provider == "gemini":
        return GeminiExtractionProvider()
    if provider in {"openai", "openai-compatible", "azure-openai", "ollama", "vllm", "lm-studio"}:
        return OpenAICompatibleExtractionProvider()
    if provider == "anthropic":
        return AnthropicExtractionProvider()
    raise AIProviderError(
        f"AI_CONFIGURATION_ERROR: unsupported CUSTOMS_AI_PROVIDER '{settings.ai_provider}'"
    )
