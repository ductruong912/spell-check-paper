"""Document cache to avoid redundant DOCX parsing."""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger("utils.cache")


def _normalize_text(text: str) -> str:
    """
    Keep text consistent across:
      - reference_finder span offsets
      - spellchecker offsets
      - UI highlight offsets

    Normalize:
      - NFC
      - remove BOM and zero-width spaces
      - keep original newlines (do not collapse)
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\ufeff", "")  # BOM
    t = t.replace("\u200b", "")  # zero-width space
    return t


@dataclass
class DocumentCache:
    """Shared document parsing cache to avoid redundant DOCX reads."""
    text: str  # Full extracted text (normalized)
    paras: List  # List of DocPara from structure module
    word_count: int  # Total words in document (normalized text)
    checked_words: int  # Words before references (for reporting)
    ref_span: Optional[Tuple[int, int]] = None  # (start, end) of references section

    @classmethod
    def from_docx(cls, file_path: str) -> "DocumentCache":
        """Parse DOCX file once and create cache."""
        # Absolute imports to avoid relative import issues
        from structure.parser import extract_docx_paragraphs
        from spell.reference_finder import find_references_span
        from document_backend import extract_text_from_docx

        logger.debug(f"Creating document cache from: {file_path}")

        # Extract raw text & paragraphs
        raw_text = extract_text_from_docx(file_path)
        paras = extract_docx_paragraphs(file_path)

        # ✅ Normalize text ONCE here to keep offsets stable everywhere else
        text = _normalize_text(raw_text)

        total_words = len(text.split())

        # ✅ Detect references span on normalized text
        ref_span = find_references_span(text)

        # ✅ Calculate checked words for reporting (NOT used for offset truncation)
        if ref_span:
            ref_start = max(0, min(ref_span[0], len(text)))
            checked_words = len(text[:ref_start].split())
        else:
            checked_words = total_words

        logger.info(
            f"Document cache created: total_words={total_words}, checked_words={checked_words}, ref_span={ref_span}"
        )

        return cls(
            text=text,
            paras=paras,
            word_count=total_words,
            checked_words=checked_words,
            ref_span=ref_span,
        )
