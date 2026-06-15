"""Shared OpenAI client creation used by both the structure and matching code.

This centralizes API-key validation and default-model resolution so the
structure checker and the journal-matching metadata extractor build their
OpenAI client the same way.
"""

from __future__ import annotations

from typing import Optional

from openai import OpenAI

from config import settings
from validation import APIValidationError, validate_openai_api_key


def create_openai_client() -> OpenAI:
    """Validate the configured API key and return an OpenAI client."""
    is_valid, api_key, error_msg = validate_openai_api_key()
    if not is_valid:
        raise APIValidationError(error_msg, f"OpenAI API validation failed: {error_msg}")
    return OpenAI(api_key=api_key)


def resolve_model(model: Optional[str] = None) -> str:
    """Return the explicit model if given, otherwise the configured default."""
    if model and model.strip():
        return model.strip()
    return settings.default_llm_model


__all__ = ["create_openai_client", "resolve_model"]
