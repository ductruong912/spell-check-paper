"""Spell checking entry points."""
import re
import unicodedata
from typing import Dict, Optional, Tuple

from .pipeline import spellcheck_text as _spellcheck_text
from .reference_finder import find_references_span


def _normalize_text(text: str) -> str:
    """Normalize text while preserving offsets as much as possible."""
    if not text:
        return ""

    text = unicodedata.normalize("NFC", text)

    replacements = {
        "\ufeff": "",   # BOM
        "\u200b": "",   # zero width space
        "\u200c": "",   # zero width non-joiner
        "\u200d": "",   # zero width joiner
        "\u2060": "",   # word joiner

        "\u00a0": " ",  # NBSP
        "\u2009": " ",  # thin space
        "\u202f": " ",  # narrow nbsp

        "\u00ad": "",   # soft hyphen
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    return text


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
