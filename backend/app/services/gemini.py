"""Backward-compatible imports for the former Gemini provider module."""

from app.services.ai_provider import AIProviderError, GeminiExtractionProvider

GeminiProviderError = AIProviderError

__all__ = ["GeminiExtractionProvider", "GeminiProviderError"]
