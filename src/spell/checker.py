"""Spell checking entry points."""

import unicodedata
from typing import Dict, Optional, Tuple

from .pipeline import spellcheck_text as _spellcheck_text
from .reference_finder import find_references_span


def _normalize_text(text: str) -> str:
	"""Chuẩn hoá text để offset ổn định (NFC, bỏ BOM/zero-width)."""
	if not text:
		return ""
	normalized = unicodedata.normalize("NFC", text)
	normalized = normalized.replace("\ufeff", "")
	normalized = normalized.replace("\u200b", "")
	return normalized


def _clamp_span(span: Optional[Tuple[int, int]], text_len: int) -> Optional[Tuple[int, int]]:
	if not span:
		return None
	start, end = span
	start = max(0, min(int(start), text_len))
	end = max(0, min(int(end), text_len))
	return (start, end) if end > start else None


def spellcheck_text(text: str, ref_span: Optional[Tuple[int, int]] = None, *, language: str = "en") -> Dict:
	"""Normalize text rồi chạy spellcheck chính."""
	norm_text = _normalize_text(text)
	norm_ref_span = _clamp_span(ref_span, len(norm_text)) if ref_span else find_references_span(norm_text)

	return _spellcheck_text(norm_text, ref_span=norm_ref_span, language=language, is_normalized=True)


__all__ = ["spellcheck_text", "find_references_span"]
