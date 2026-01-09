"""Document structure analysis module."""
from .checker import check_structure_docx
from .parser import extract_docx_paragraphs

__all__ = ["check_structure_docx", "extract_docx_paragraphs"]
