"""Phân tích DOCX và trích xuất cấu trúc bài báo.
"""
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


@dataclass
class LLMDocView:

    view_text: str
    tail_text: str
    section_count: int


# -----------------------------
# Utilities
# -----------------------------
def _norm_ws(s: str) -> str:
    """Chuẩn hóa khoảng trắng trong văn bản."""
    s = (s or "").replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _collect_header_footer_text(doc: Document) -> set[str]:
    """Lấy tất cả văn bản trong header và footer (nỗ lực tốt nhất)."""
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
        # Lấy header/footer là nỗ lực tốt nhất, không gây lỗi nếu thất bại
        pass
    return hf_texts


# Match "Heading 1", "Tiêu đề 1", "Tieu de 1"
_HEADING_STYLE_RE = re.compile(r"^(heading|tiêu đề|tieu de)\s+(\d+)\s*$", re.I)


def _heading_level_from_style(style_name: str) -> int:
    """Lấy mức heading từ tên style (vd. 'Heading 1' -> 1)."""
    s = (style_name or "").strip()
    m = _HEADING_STYLE_RE.match(s)
    if not m:
        return 0
    try:
        return int(m.group(2))
    except Exception:
        return 0


def extract_docx_paragraphs(path: str) -> List[DocPara]:
    """Trích xuất đoạn văn từ DOCX kèm style và mức heading."""
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
# -----------------------------
# Hybrid splitting (recommended for product)
# -----------------------------
# Phát hiện heading đánh số như: "1. Introduction", "I. METHODS", "CHƯƠNG 1 ..."
_HEADING_LIKE_RE = re.compile(
    r"^\s*((\d+(\.\d+)*)|[IVXLC]+)\s*[\).\:-]\s+.+$|^(chương|chapter)\s+\d+",
    re.IGNORECASE,
)

# Phát hiện anchor phổ biến (VI + EN) dùng làm heading
_ANCHOR_RE = re.compile(
    r"^(tóm tắt|abstract|từ khóa|tu khoa|keywords|giới thiệu|introduction|"

    r"phương pháp|methods|materials and methods|kết quả|results|thảo luận|discussion|"

    r"kết luận|conclusion|tài liệu tham khảo|tai lieu tham khao|references|bibliography|"

    r"phụ lục|appendix|lời cảm ơn|acknowledgements|contribution|contributions|"

    r"conflict of interest|mâu thuẫn lợi ích)\b",
    re.IGNORECASE,
)


def _looks_like_heading(text: str, *, allow_weak: bool = True) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    # Too long -> unlikely a heading
    if len(t) > 140:
        return False

    # Strong signals
    if _ANCHOR_RE.match(t) or _HEADING_LIKE_RE.match(t):
        return True

    if not allow_weak:
        return False

    # Weak signals: short line, low punctuation, high uppercase ratio
    words = t.split()
    if 1 <= len(words) <= 12:
        punct = sum(1 for ch in t if ch in ".,;:!?")
        if punct <= 1:
            letters = [ch for ch in t if ch.isalpha()]
            if letters:
                upper_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
                if upper_ratio >= 0.6:
                    return True

    return False


def split_by_structure(paras: List[DocPara]) -> Tuple[str, List[DocSection]]:
    front_buf: List[str] = []
    sections: List[DocSection] = []

    cur_heading: Optional[str] = None
    cur_buf: List[str] = []
    seen_boundary = False

    def flush():
        nonlocal cur_heading, cur_buf
        if cur_heading is None:
            return
        content = _norm_ws("\n".join(cur_buf))
        sections.append(DocSection(heading=cur_heading, content=content))
        cur_heading = None
        cur_buf = []

    for p in paras:
        # (Heading 1 / anchor / đánh số). Tránh cắt nhầm tiêu đề IN HOA.
        is_boundary = (p.heading_level == 1) or _looks_like_heading(p.text, allow_weak=seen_boundary)

        if is_boundary:
            seen_boundary = True
            flush()
            cur_heading = p.text
            cur_buf = []
            continue

        if not seen_boundary:
            front_buf.append(p.text)
        else:
            if cur_heading is not None:
                # Keep existing behavior: embed H2/H3 into content
                if p.heading_level >= 2:
                    cur_buf.append(f"## {p.text}")
                else:
                    cur_buf.append(p.text)

    flush()
    return _norm_ws("\n".join(front_buf)), sections


# -----------------------------
# LLM view builder (new)
# -----------------------------
def build_llm_view(
    paras: List[DocPara],
    *,
    max_front_paras: int = 140,
    max_tail_paras: int = 220,
    max_sections: int = 28,
    max_section_chars: int = 1200,
) -> LLMDocView:
    if not paras:
        return LLMDocView(view_text="", tail_text="", section_count=0)

    # FRONT/TAIL by paragraph windows.
    n = len(paras)
    if n <= (max_front_paras + max_tail_paras):
        front_end = min(max_front_paras, max(1, n // 2))
    else:
        front_end = min(n, max_front_paras)

    # Tail luôn ưu tiên lấy phần cuối. Nếu tài liệu ngắn, tail_start=front_end (không trùng).
    tail_start = max(front_end, n - max(1, max_tail_paras))

    front_text = _norm_ws("\n".join(p.text for p in paras[:front_end]))
    tail_text = _norm_ws("\n".join(p.text for p in paras[tail_start:]))

    # OUTLINE by hybrid split (helps the model infer missing headings)
    _front_unused, sections = split_by_structure(paras)
    outline_lines: List[str] = []
    for i, sec in enumerate(sections[: max(1, max_sections)]):
        heading = _norm_ws(sec.heading)
        content = _norm_ws(sec.content)[: max(1, max_section_chars)]
        if not heading and not content:
            continue
        outline_lines.append(f"[S{i:02d}] {heading}")
        if content:
            outline_lines.append(content)
        outline_lines.append("")

    outline_text = _norm_ws("\n".join(outline_lines))

    view_text = _norm_ws(
        "\n\n".join(
            [
                "[FRONT]",
                front_text,
                "[OUTLINE]",
                outline_text,
                "[TAIL]",
                tail_text,
            ]
        )
    )

    return LLMDocView(view_text=view_text, tail_text=tail_text, section_count=min(len(sections), max_sections))