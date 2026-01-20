"""Cache tài liệu để tránh parse/đọc DOCX lặp lại."""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger("utils.cache")


def _normalize_text(text: str) -> str:
    """Chuẩn hoá text để offset ổn định (NFC, bỏ BOM/zero-width)."""
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\ufeff", "")  # BOM
    t = t.replace("\u200b", "")  # zero-width space
    return t


@dataclass
class DocumentCache:
    """Giữ text/paras/ref_span sau khi đọc DOCX 1 lần."""
    text: str  # Full extracted text (normalized)
    paras: List  # List of DocPara from structure module
    word_count: int  # Total words in document (normalized text)
    checked_words: int  # Words before references (for reporting)
    ref_span: Optional[Tuple[int, int]] = None  # (start, end) of references section

    @classmethod
    def from_docx(cls, file_path: str) -> "DocumentCache":
        """Parse DOCX một lần, trả cache dùng chung cho các bước check."""
        # Absolute imports to avoid relative import issues
        from structure.parser import extract_docx_paragraphs
        from spell.reference_finder import find_references_span
        from document_backend import extract_text_from_docx

        logger.debug(f"Creating document cache from: {file_path}")

        raw_text = extract_text_from_docx(file_path)
        paras = extract_docx_paragraphs(file_path)

        text = _normalize_text(raw_text)
        total_words = len(text.split())

        ref_span = find_references_span(text)

        # Số từ trước references (chỉ phục vụ báo cáo)
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