# src/plagiarism/normalize.py
from __future__ import annotations
import re
import unicodedata

_CITATION_RE = re.compile(
    r"(\[\s*\d+(?:\s*[-,]\s*\d+)*\s*\])|"
    r"(\(\s*[A-ZÀ-Ỵ][A-Za-zÀ-Ỵà-ỹ\.\- ]+,\s*\d{4}[a-z]?\s*\))"
)
_NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

_REF_HEADINGS = ["tài liệu tham khảo", "references", "reference", "bibliography"]

# Headings thường đánh dấu bắt đầu nội dung
_BODY_START = [
    "tóm tắt", "abstract",
    "đặt vấn đề", "mở đầu", "introduction",
    "tổng quan", "cơ sở lý thuyết", "literature review",
]

# Các từ khóa rác hay xuất hiện ở đầu PDF tạp chí
_FRONT_NOISE = [
    "mục lục", "issn", "e-issn", "khoa học", "thương mại",
    "ruot so", "page", "pm page"
]

def strip_references(text: str) -> str:
    lower = text.lower()
    cut_pos = None
    for h in _REF_HEADINGS:
        idx = lower.find(h)
        if idx != -1:
            cut_pos = idx if cut_pos is None else min(cut_pos, idx)
    if cut_pos is not None and cut_pos > 0:
        return text[:cut_pos].strip()
    return text.strip()

def strip_front_matter(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text

    head = " ".join(lines[:80]).lower()
    # nếu có dấu hiệu tạp chí/mục lục
    if not any(k in head for k in ["mục lục", "issn", "e-issn", "khoa học", "thương mại"]):
        return text.strip()

    for i, ln in enumerate(lines[:400]):
        low = ln.lower()
        if ("tóm tắt" in low) or ("abstract" in low) or ("đặt vấn đề" in low) or ("introduction" in low):
            return "\n".join(lines[i:]).strip()

    # fallback
    return "\n".join(lines[60:]).strip() if len(lines) > 60 else "\n".join(lines).strip()

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")

    # dọn spacing
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)

    # cắt phần rác đầu + references
    text = strip_front_matter(text)
    text = strip_references(text)

    # citation token
    text = _CITATION_RE.sub(" <CIT> ", text)

    # số -> <NUM> (giữ lại để tránh nhiễu số liệu, nhưng sẽ bỏ khi embed)
    text = _NUM_RE.sub(" <NUM> ", text)

    text = re.sub(r"\s+", " ", text).strip()
    return text

def has_citation(text: str) -> bool:
    return "<CIT>" in (text or "")

def text_for_embedding(text: str) -> str:
    if not text:
        return ""
    # bỏ token kỹ thuật để giảm match giả ở header
    return (
        text.replace("<CIT>", "")
            .replace("<NUM>", "")
            .replace("  ", " ")
            .strip()
    )
