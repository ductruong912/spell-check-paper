import unicodedata
from typing import Dict, Tuple, Optional

from .detector import spellcheck_english_with_word
from .reference_finder import find_references_span


def _normalize_text(text: str) -> str:
    """Chuẩn hoá text để offset ổn định (NFC, bỏ BOM/zero-width)."""
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\ufeff", "")  # BOM
    t = t.replace("\u200b", "")  # zero-width space
    return t


def _clamp_span(span: Optional[Tuple[int, int]], text_len: int) -> Optional[Tuple[int, int]]:
    """Clamp ref_span vào biên [0, text_len]."""
    if not span:
        return None
    a, b = span
    a = max(0, min(int(a), text_len))
    b = max(0, min(int(b), text_len))
    if b <= a:
        return None
    return (a, b)


def spellcheck_auto(text: str, ref_span: Optional[Tuple[int, int]] = None) -> Dict:
    """Normalize text + ref_span rồi chạy spellcheck chính."""
    norm_text = _normalize_text(text)

    if ref_span is None:
        norm_ref_span = find_references_span(norm_text)
    else:
        norm_ref_span = _clamp_span(ref_span, len(norm_text))

    return spellcheck_english_with_word(norm_text, ref_span=norm_ref_span)
