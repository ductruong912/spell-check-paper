import unicodedata
from typing import Dict, Tuple, Optional

from .detector import spellcheck_english_with_word
from .reference_finder import find_references_span


def _normalize_text(text: str) -> str:
    """
    Normalize Unicode text to NFC and remove BOM/zero-width so offsets are stable.
    Must match DocumentCache normalization.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\ufeff", "")  # BOM
    t = t.replace("\u200b", "")  # zero-width space
    return t


def spellcheck_auto(text: str, ref_span: Optional[Tuple[int, int]] = None) -> Dict:
    norm_text = _normalize_text(text)
    norm_ref_span = find_references_span(norm_text)

    return spellcheck_english_with_word(norm_text, ref_span=norm_ref_span)
