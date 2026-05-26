"""Module kiểm tra cấu trúc bài báo (LLM-first)."""
from .checker import check_structure_docx
from utils.document_parser import extract_docx_paragraphs

__all__ = ["check_structure_docx", "extract_docx_paragraphs"]
