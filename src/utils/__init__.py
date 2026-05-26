"""Các hàm tiện ích và lớp chung của dự án.

DocumentCache được expose tại đây để tiện import `from utils import DocumentCache`.
"""
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
	paras: List  # List of DocPara from the shared document parser
	word_count: int  # Total words in document (normalized text)
	checked_words: int  # Words checked by spell checker
	ref_span: Optional[Tuple[int, int]] = None  # (start, end) of references section

	@classmethod
	def from_docx(cls, file_path: str) -> "DocumentCache":
		"""Parse DOCX một lần, trả cache dùng chung cho các bước check."""
		# Absolute imports to avoid relative import issues
		from utils.document_parser import extract_docx_paragraphs
		from document_backend import extract_text_from_docx
		from spell.reference_finder import find_references_span

		logger.debug(f"Creating document cache from: {file_path}")

		raw_text = extract_text_from_docx(file_path)
		paras = extract_docx_paragraphs(file_path)

		text = _normalize_text(raw_text)
		total_words = len(text.split())
		ref_span = find_references_span(text)
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


from .config import *

__all__ = ["DocumentCache"]
