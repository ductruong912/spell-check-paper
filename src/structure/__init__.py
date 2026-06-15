"""Module kiểm tra cấu trúc bài báo (LLM-first)."""
from .checker import check_structure_docx, check_structure_document
from .models import SectionHit, StructureReport

__all__ = [
    "SectionHit",
    "StructureReport",
    "check_structure_document",
    "check_structure_docx",
]
