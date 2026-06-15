"""Local document preview generation independent from backend text parsing."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Tuple, Union

from config import settings

logger = logging.getLogger("documents.preview")

PreviewKind = Literal["pdf_pages", "html", "unavailable"]
PreviewContent = Optional[Union[Tuple[bytes, ...], str]]
PDF_PREVIEW_SCALE = settings.pdf_preview_scale

_WINDOWS_LIBREOFFICE_PATHS = (
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
)
_HTML_TAGS = {
    "a",
    "blockquote",
    "br",
    "caption",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
_HTML_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["alt", "src", "title"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}


@dataclass(frozen=True)
class DocumentPreview:
    kind: PreviewKind
    content: PreviewContent
    warning: str = ""


def find_libreoffice() -> Optional[str]:
    """Find a local LibreOffice executable without invoking external services."""
    configured = os.getenv("LIBREOFFICE_PATH") or settings.libreoffice_path
    if configured and Path(configured).is_file():
        return configured

    executable = shutil.which("soffice.exe") or shutil.which("soffice")
    if executable:
        return executable

    for candidate in _WINDOWS_LIBREOFFICE_PATHS:
        if candidate.is_file():
            return str(candidate)
    return None


def _convert_docx_to_pdf(
    path: str,
    libreoffice_path: str,
    *,
    timeout_seconds: int = settings.docx_preview_timeout_seconds,
) -> bytes:
    source_path = Path(path)
    with tempfile.TemporaryDirectory(prefix="document-preview-") as output_dir:
        subprocess.run(
            [
                libreoffice_path,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir,
                str(source_path),
            ],
            check=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        pdf_path = Path(output_dir) / f"{source_path.stem}.pdf"
        if not pdf_path.is_file():
            raise RuntimeError("LibreOffice did not produce a PDF preview")
        return pdf_path.read_bytes()


def _convert_docx_to_html(path: str) -> str:
    import mammoth

    with open(path, "rb") as document:
        result = mammoth.convert_to_html(document)
    return str(result.value or "")


def _render_pdf_pages(
    pdf_bytes: bytes,
    *,
    scale: float = PDF_PREVIEW_SCALE,
) -> Tuple[bytes, ...]:
    """Rasterize PDF pages once for a sharp, control-free local preview."""
    import fitz

    pages = []
    matrix = fitz.Matrix(scale, scale)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        for page in document:
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pages.append(pixmap.tobytes("png"))

    if not pages:
        raise RuntimeError("PDF preview has no pages")
    return tuple(pages)


def _build_pdf_preview(pdf_bytes: bytes) -> DocumentPreview:
    return DocumentPreview(
        kind="pdf_pages",
        content=_render_pdf_pages(pdf_bytes),
    )


def _sanitize_html(html_text: str) -> str:
    import bleach

    return bleach.clean(
        html_text or "",
        tags=_HTML_TAGS,
        attributes=_HTML_ATTRIBUTES,
        protocols={"data", "http", "https", "mailto"},
        strip=True,
    )


def build_document_preview(path: str, original_bytes: bytes) -> DocumentPreview:
    """Build an in-memory local preview while leaving backend text untouched."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return _build_pdf_preview(original_bytes)

    if suffix != ".docx":
        return DocumentPreview(
            kind="unavailable",
            content=None,
            warning="Không hỗ trợ xem trước định dạng tài liệu này.",
        )

    libreoffice_path = find_libreoffice()
    if libreoffice_path:
        try:
            return _build_pdf_preview(_convert_docx_to_pdf(path, libreoffice_path))
        except Exception as exc:
            logger.warning("LibreOffice DOCX preview failed: %s", exc)

    try:
        html_content = _sanitize_html(_convert_docx_to_html(path))
        if html_content.strip():
            return DocumentPreview(
                kind="html",
                content=html_content,
                warning="Đang dùng bản xem trước HTML vì không thể tạo PDF bằng LibreOffice.",
            )
    except Exception as exc:
        logger.warning("HTML DOCX preview failed: %s", exc)

    return DocumentPreview(
        kind="unavailable",
        content=None,
        warning="Không thể tạo bản xem trước DOCX trên máy hiện tại.",
    )
