"""Text extraction utilities for DOCX documents."""

from __future__ import annotations
from typing import List
from docx import Document

from utils.text_utils import INTRO_HEADING, REF_HEADING


def _docx_paragraph_texts(path: str) -> List[str]:
    """Extract all non-empty paragraph texts from a DOCX file."""
    doc = Document(path)
    out: List[str] = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            out.append(t)
    return out


def extract_body_text_from_docx(path: str) -> str:
    """Extract main body text from DOCX, between introduction and references."""
    paras = _docx_paragraph_texts(path)
    if not paras:
        return ""

    body_buf: List[str] = []
    pre_ref_buf: List[str] = []

    started = False
    saw_ref = False

    for t in paras:
        if REF_HEADING.search(t):
            saw_ref = True
            break

        pre_ref_buf.append(t)

        if not started:
            if INTRO_HEADING.search(t):
                started = True
                continue
        else:
            body_buf.append(t)

    body = "\n".join(body_buf).strip()

    # fallback: nếu không có introduction -> lấy hết trước references (hoặc full nếu không có ref)
    if not body:
        if saw_ref and pre_ref_buf:
            return "\n".join(pre_ref_buf).strip()
        return "\n".join(paras).strip()

    return body


def extract_references_text_from_docx(path: str) -> str:
    """Extract references/bibliography section from DOCX."""
    paras = _docx_paragraph_texts(path)
    if not paras:
        return ""

    ref_buf: List[str] = []
    in_refs = False

    for t in paras:
        if REF_HEADING.search(t):
            in_refs = True
            continue

        if in_refs:
            # Only collect non-empty reference lines
            if t.strip():
                ref_buf.append(t)

    return "\n".join(ref_buf).strip()
