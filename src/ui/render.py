"""Progressive render helpers for the Streamlit UI."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import streamlit as st
import streamlit.components.v1 as components

from documents import DocumentPreview
from ui.layout import structure_section_html


PDF_PREVIEW_HEIGHT = 950


@dataclass(frozen=True)
class DocumentActionState:
    title: str
    subtitle: str
    show_structure_check: bool = False


_ACTION_STATES = {
    "idle": DocumentActionState(
        title="Chưa có tài liệu",
        subtitle="Chọn file DOCX hoặc PDF để tạo bản xem trước",
    ),
    "preparing": DocumentActionState(
        title="Đang chuẩn bị tài liệu",
        subtitle="Đang tạo bản xem trước và trích xuất nội dung",
    ),
    "ready": DocumentActionState(
        title="Preview đã sẵn sàng",
        subtitle="Xem lại tài liệu trước khi kiểm tra cấu trúc",
        show_structure_check=True,
    ),
    "running": DocumentActionState(
        title="Đang kiểm tra cấu trúc",
        subtitle="Vui lòng đợi trong giây lát",
    ),
    "timeout": DocumentActionState(
        title="Kiểm tra quá thời gian",
        subtitle="Preview vẫn được giữ để bạn xem lại",
    ),
    "error": DocumentActionState(
        title="Không thể hoàn tất",
        subtitle="Đổi tài liệu hoặc kiểm tra lại cấu hình backend",
    ),
}


def document_action_state(review_state: str) -> DocumentActionState:
    return _ACTION_STATES.get(review_state, _ACTION_STATES["idle"])

_IFRAME_CSS = """
<style>
html, body { margin:0; padding:0; }
body { background:#e5eaed; color:#111827; font-family:"Times New Roman",Times,serif; font-size:16px; line-height:1.55; }
.app-doc {
  box-sizing:border-box; width:min(100%,794px); min-height:1123px; margin:16px auto;
  padding:72px 76px; background:#fff; box-shadow:0 1px 8px rgba(0,0,0,.18);
}
.app-doc img { max-width:100%; height:auto; }
.app-doc table { width:100%; border-collapse:collapse; }
.app-doc td,.app-doc th { border:1px solid #9ca3af; padding:4px 6px; }
@media (max-width:700px) { .app-doc { margin:0; padding:24px; } }
</style>
"""


def _preview_source_label(preview: DocumentPreview, file_name: str) -> str:
    suffix = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    if preview.kind == "pdf_pages":
        return "PDF gốc" if suffix == "pdf" else "DOCX → PDF"
    if preview.kind == "html":
        return "DOCX → HTML"
    return "Không khả dụng"


def render_pdf_page_preview(pages: tuple[bytes, ...]) -> None:
    with st.container(height=PDF_PREVIEW_HEIGHT, key="document_page_preview"):
        for page in pages:
            st.image(page, width="stretch", output_format="PNG")


def _workspace_state_details(state: str) -> tuple[str, str, str]:
    if state == "preparing":
        return "", "Đang chuẩn bị", ""
    if state == "ready":
        return "", "Chờ kiểm tra", ""
    if state == "running":
        return "", "Đang xử lý", ""
    if state == "timeout":
        return "", "Quá thời gian", " app-chip--error"
    if state == "error":
        return "", "Có lỗi", " app-chip--error"
    return "", "Hoàn tất", " app-chip--success"


def render_workspace_header(
    placeholder,
    *,
    file_name: str,
    file_size: int,
    word_count: int,
    state: str,
) -> None:
    if not file_name:
        placeholder.empty()
        return

    title = html.escape(file_name)
    _, status_label, status_class = _workspace_state_details(state)
    suffix = Path(file_name).suffix.lower().lstrip(".").upper() or "Tài liệu"
    size_kb = file_size / 1024 if file_size else 0
    chips = (
        f'<span class="app-chip">{suffix} · {size_kb:,.1f} KB</span>'
        f'<span class="app-chip">{int(word_count or 0):,} từ</span>'
        f'<span class="app-chip{status_class}">{status_label}</span>'
    )

    placeholder.markdown(
        '<div class="app-context">'
        f'<div class="app-context__title">{title}</div>'
        f'<div class="app-context__chips">{chips}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_document(
    placeholder,
    *,
    file_name: str,
    preview: DocumentPreview | None,
    word_count: int,
) -> None:
    placeholder.empty()
    with placeholder.container():
        if preview is None:
            st.markdown(
                '<div class="app-panel-head">'
                '<span class="app-panel-head__title">Bản xem trước tài liệu</span>'
                '<span class="app-panel-head__meta">Chưa có tài liệu</span>'
                "</div>"
                '<div class="app-empty"><strong>Tải bài báo lên để bắt đầu</strong></div>',
                unsafe_allow_html=True,
            )
            return

        notice = f'<div class="app-preview-notice">{preview.warning}</div>' if preview.warning else ""
        if notice:
            st.markdown(notice, unsafe_allow_html=True)

        if preview.kind == "unavailable":
            st.warning(preview.warning or "Không thể hiển thị bản xem trước tài liệu.")
            return

        if preview.kind == "pdf_pages" and isinstance(preview.content, tuple):
            render_pdf_page_preview(preview.content)
            return

        if preview.kind == "html" and isinstance(preview.content, str):
            components.html(
                f"{_IFRAME_CSS}<div class='app-doc'>{preview.content}</div>",
                height=1100,
                scrolling=True,
            )


def _structure_busy_html(state: str) -> str:
    if state == "preparing":
        title = "Đang chuẩn bị tài liệu"
        summary = "Đang tạo bản xem trước và trích xuất nội dung..."
    else:
        title = "Đang kiểm tra cấu trúc"
        summary = "Đang phân tích các mục yêu cầu trong tài liệu..."

    return (
        '<div class="app-results"><div class="app-results__head">'
        '<div class="app-results__title-row">'
        '<span class="app-spinner" aria-hidden="true"></span>'
        f'<div class="app-results__title">{title}</div>'
        "</div>"
        f'<div class="app-results__summary">{summary}</div>'
        '<div class="app-progress"><div class="app-progress__bar app-progress__bar--indeterminate"></div></div>'
        "</div></div>"
    )


def _structure_error_html(message: str) -> str:
    return (
        '<div class="app-results app-results--error"><div class="app-results__head">'
        '<div class="app-results__title">Không thể kiểm tra cấu trúc</div>'
        f'<div class="app-results__summary">{html.escape(message)}</div>'
        "</div></div>"
    )


def _structure_idle_html() -> str:
    return (
        '<div class="app-results"><div class="app-results__head">'
        '<div class="app-results__title">Kết quả cấu trúc</div>'
        '<div class="app-results__summary">Chưa kiểm tra cấu trúc.</div>'
        "</div></div>"
    )


def render_structure(placeholder, *, data: Dict, state: str, error: str | None) -> None:
    """Render the structure result section by state."""
    if state in ("preparing", "running"):
        markup = _structure_busy_html(state)
    elif state in ("error", "timeout"):
        markup = _structure_error_html(
            error or (data or {}).get("error") or "Không lấy được kết quả cấu trúc."
        )
    elif state == "ok":
        markup = structure_section_html(data or {}) or _structure_idle_html()
    else:
        markup = _structure_idle_html()

    placeholder.markdown(markup, unsafe_allow_html=True)
