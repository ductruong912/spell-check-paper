"""Normalization helpers for valid-paper titles and keywords."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from documents import normalize_whitespace

_KEYWORDS_PREFIX_RE = re.compile(
    r"^\s*(?:key\s*words?|keywords?|keyword(?:\s*\([^)]*\))?|từ\s*kho[áa]|tu\s*khoa)\s*[:：-]?\s*",
    re.I,
)
_LEADING_PUNCT_RE = re.compile(r"^[\s:;\-–—•·]+")
_TRAILING_PUNCT_RE = re.compile(r"[\s\.:;，,。…]+$")
_SPLIT_KEYWORDS_RE = re.compile(r"[,;]")


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\uFFFD", "'")
    text = text.replace("\u00A0", " ")
    text = normalize_whitespace(text)
    text = _KEYWORDS_PREFIX_RE.sub("", text)
    text = _LEADING_PUNCT_RE.sub("", text)
    text = _TRAILING_PUNCT_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_title(title: str | None) -> str:
    """Clean title text for storage and embedding."""
    return _normalize_text(title).casefold()


def normalize_keyword_tokens(keywords: Iterable[str] | str | None) -> list[str]:
    """Split, clean, lowercase, and deduplicate keyword tokens while preserving order."""
    if keywords is None:
        return []

    if isinstance(keywords, str):
        raw_items: list[str] = [keywords]
    else:
        raw_items = [str(item) for item in keywords if item is not None]

    cleaned_keywords: list[str] = []
    seen: set[str] = set()

    for raw_item in raw_items:
        for part in _SPLIT_KEYWORDS_RE.split(raw_item):
            token = _normalize_text(part)
            if not token:
                continue
            token = token.casefold()
            key = token
            if key in seen:
                continue
            seen.add(key)
            cleaned_keywords.append(token)

    return cleaned_keywords


def normalize_keywords_text(keywords: Iterable[str] | str | None) -> str:
    """Return cleaned keywords as a single comma-separated string."""
    tokens = normalize_keyword_tokens(keywords)
    return ", ".join(tokens)
