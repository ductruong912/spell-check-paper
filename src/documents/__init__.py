"""Document parsing, preview, and temporary-file helpers."""

from .parser import (
    DocPara,
    DocumentView,
    build_document_view,
    build_document_view_from_paragraphs,
    extract_document_paragraphs,
    extract_docx_paragraphs,
    extract_pdf_paragraphs,
    normalize_whitespace,
    paragraphs_to_full_text,
    paragraphs_to_structured_docx_view,
    paragraphs_to_structured_document_view,
)
from .extract import extract_text, extract_text_from_bytes
from .preview import DocumentPreview, build_document_preview

__all__ = [
    "DocPara",
    "DocumentView",
    "DocumentPreview",
    "build_document_view",
    "build_document_view_from_paragraphs",
    "build_document_preview",
    "extract_document_paragraphs",
    "extract_docx_paragraphs",
    "extract_pdf_paragraphs",
    "extract_text",
    "extract_text_from_bytes",
    "normalize_whitespace",
    "paragraphs_to_full_text",
    "paragraphs_to_structured_docx_view",
    "paragraphs_to_structured_document_view",
]
