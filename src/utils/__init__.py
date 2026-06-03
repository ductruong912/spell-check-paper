"""Shared utilities exposed at the package root."""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import List

logger = logging.getLogger("utils.cache")


def _normalize_text(text: str) -> str:
    """Normalize text for stable downstream processing."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\ufeff", "")
    normalized = normalized.replace("\u200b", "")
    return normalized


@dataclass
class DocumentCache:
    """Text and paragraph cache created after reading a DOCX file once."""

    text: str
    paras: List
    word_count: int

    @classmethod
    def from_docx(cls, file_path: str) -> "DocumentCache":
        from document_backend import extract_text_from_docx
        from utils.document_parser import extract_docx_paragraphs

        logger.debug("Creating document cache from: %s", file_path)

        raw_text = extract_text_from_docx(file_path)
        paras = extract_docx_paragraphs(file_path)

        text = _normalize_text(raw_text)
        total_words = len(text.split())

        logger.info("Document cache created: total_words=%s", total_words)

        return cls(
            text=text,
            paras=paras,
            word_count=total_words,
        )


from .config import *

__all__ = ["DocumentCache"]
