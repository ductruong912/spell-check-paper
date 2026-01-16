"""Bộ nhớ đệm tài liệu để tránh phân tích lại file DOCX."""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger("utils.cache")


def _normalize_text(text: str) -> str:
    """Chuẩn hoá văn bản để đồng nhất offset cho các thành phần (refs, spell, UI).

    Hành động: NFC, loại BOM/zero-width, giữ nguyên xuống dòng.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\ufeff", "")  # BOM
    t = t.replace("\u200b", "")  # zero-width space
    return t


@dataclass
class DocumentCache:
    """Bộ nhớ đệm chung sau khi trích xuất DOCX, tránh đọc lặp lại."""
    text: str  # Full extracted text (normalized)
    paras: List  # List of DocPara from structure module
    word_count: int  # Total words in document (normalized text)
    checked_words: int  # Words before references (for reporting)
    ref_span: Optional[Tuple[int, int]] = None  # (start, end) of references section

    @classmethod
    def from_docx(cls, file_path: str) -> "DocumentCache":
        """Phân tích DOCX một lần và tạo DocumentCache."""
        # Absolute imports to avoid relative import issues
        from structure.parser import extract_docx_paragraphs
        from spell.reference_finder import find_references_span
        from document_backend import extract_text_from_docx

        logger.debug(f"Creating document cache from: {file_path}")

        # Trích xuất văn bản thô và danh sách đoạn
        raw_text = extract_text_from_docx(file_path)
        paras = extract_docx_paragraphs(file_path)

        # Chuẩn hóa văn bản 1 lần để offset ổn định
        text = _normalize_text(raw_text)

        total_words = len(text.split())

        # Phát hiện span references trên văn bản đã chuẩn hoá
        ref_span = find_references_span(text)

        # Tính số từ trước phần references để báo cáo (không dùng cho cắt offset)
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
