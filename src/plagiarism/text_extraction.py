"""Trích xuất phần thân và tài liệu tham khảo từ DOCX (phục vụ check đạo văn)."""

from __future__ import annotations
from typing import List
from docx import Document

from utils.text_utils import INTRO_HEADING, REF_HEADING


# ----------------------------
# Low-level helpers
# ----------------------------
def _docx_paragraph_texts(path: str) -> List[str]:
    """Lấy toàn bộ paragraph không rỗng từ DOCX (theo thứ tự gốc)."""
    doc = Document(path)
    out: List[str] = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            out.append(t)
    return out


# ----------------------------
# Body extraction
# ----------------------------
def extract_body_text_from_docx(path: str) -> str:
    """
    Trích xuất phần thân bài:
    - Ưu tiên lấy nội dung sau Introduction
    - Dừng tại References
    - Có fallback nếu không có Introduction
    """
    paras = _docx_paragraph_texts(path)
    if not paras:
        return ""

    body_buf: List[str] = []
    pre_ref_buf: List[str] = []

    started = False
    saw_ref = False

    for t in paras:
        # Gặp References → dừng
        if REF_HEADING.search(t):
            saw_ref = True
            break

        pre_ref_buf.append(t)

        if not started:
            # Bắt đầu thân bài khi gặp Introduction
            if INTRO_HEADING.search(t):
                started = True
                continue
        else:
            body_buf.append(t)

    body = "\n".join(body_buf).strip()

    # Fallback: không có Introduction
    if not body:
        if saw_ref and pre_ref_buf:
            return "\n".join(pre_ref_buf).strip()
        return "\n".join(paras).strip()

    return body


# ----------------------------
# References extraction
# ----------------------------
def extract_references_text_from_docx(path: str) -> str:
    """
    Trích xuất phần tài liệu tham khảo (sau heading References).
    Dùng cho check riêng hoặc loại trừ khi cần.
    """
    paras = _docx_paragraph_texts(path)
    if not paras:
        return ""

    ref_buf: List[str] = []
    in_refs = False

    for t in paras:
        if REF_HEADING.search(t):
            in_refs = True
            continue

        if in_refs and t.strip():
            ref_buf.append(t)

    return "\n".join(ref_buf).strip()
