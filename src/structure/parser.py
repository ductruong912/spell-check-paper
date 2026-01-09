"""Document parsing and structure extraction for DOCX files."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from docx import Document

# -----------------------------
# Models
# -----------------------------
@dataclass
class DocPara:
    text: str
    style: str
    heading_level: int


@dataclass
class DocSection:
    heading: str
    content: str


# -----------------------------
# Utilities
# -----------------------------
def _norm_ws(s: str) -> str:
    """Normalize whitespace in text."""
    s = (s or "").replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _collect_header_footer_text(doc: Document) -> set[str]:
    """Extract text from all headers and footers in the document."""
    hf_texts: set[str] = set()
    try:
        for sec in doc.sections:
            for p in sec.header.paragraphs:
                t = _norm_ws(p.text)
                if t:
                    hf_texts.add(t)
            for p in sec.footer.paragraphs:
                t = _norm_ws(p.text)
                if t:
                    hf_texts.add(t)
    except Exception:
        pass
    return hf_texts


# Match "Heading 1", "Tiêu đề 1", "Tieu de 1"
_HEADING_STYLE_RE = re.compile(r"^(heading|tiêu đề|tieu de)\s+(\d+)\s*$", re.I)


def _heading_level_from_style(style_name: str) -> int:
    """Extract heading level from style name."""
    s = (style_name or "").strip()
    m = _HEADING_STYLE_RE.match(s)
    if not m:
        return 0
    try:
        return int(m.group(2))
    except Exception:
        return 0


def extract_docx_paragraphs(path: str) -> List[DocPara]:
    """Extract all paragraphs from DOCX file with their styles and heading levels."""
    doc = Document(path)
    hf_texts = _collect_header_footer_text(doc)

    out: List[DocPara] = []
    for p in doc.paragraphs:
        t = _norm_ws(p.text)
        if not t:
            continue
        if t in hf_texts:
            continue

        try:
            style_name = (p.style.name or "")
        except Exception:
            style_name = ""

        lvl = _heading_level_from_style(style_name)
        out.append(DocPara(text=t, style=style_name, heading_level=lvl))

    return out


def split_by_heading1(paras: List[DocPara]) -> Tuple[str, List[DocSection]]:
    """Split document paragraphs into frontmatter and Heading 1 sections."""
    front_buf: List[str] = []
    sections: List[DocSection] = []

    cur_heading: Optional[str] = None
    cur_buf: List[str] = []
    seen_h1 = False

    def flush():
        nonlocal cur_heading, cur_buf
        if cur_heading is None:
            return
        content = _norm_ws("\n".join(cur_buf))
        sections.append(DocSection(heading=cur_heading, content=content))
        cur_heading = None
        cur_buf = []

    for p in paras:
        if p.heading_level == 1:
            seen_h1 = True
            flush()
            cur_heading = p.text
            cur_buf = []
            continue

        if not seen_h1:
            front_buf.append(p.text)
        else:
            if cur_heading is not None:
                if p.heading_level >= 2:
                    cur_buf.append(f"## {p.text}")  # embed H2/H3 into content
                else:
                    cur_buf.append(p.text)

    flush()
    return _norm_ws("\n".join(front_buf)), sections
