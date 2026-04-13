from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from utils.config import DEFAULT_LLM_MODEL, DEFAULT_MIN_CONFIDENCE

from .parser import DocPara, build_llm_view, extract_docx_paragraphs
from .classifier import guess_references_style, llm_detect_structure

logger = logging.getLogger("structure_checker")


# ----------------------------
# Data structures
# ----------------------------
@dataclass
class SectionHit:
    status: str  # "ok" | "missing"
    evidence: str = ""
    llm_confidence: float = 0.0
    notes: str = ""
    references_style: str = ""


@dataclass
class Report:
    file: str
    ok: bool
    sections: Dict[str, SectionHit]
    notes: List[str]


# ----------------------------
# Targets / Required
# ----------------------------
TARGETS = [
    ("title_vi", "Tiêu đề tiếng Việt"),
    ("title_en", "Tiêu đề tiếng Anh"),
    ("authors", "Tác giả / Nhóm tác giả và thông tin liên hệ"),
    ("abstract_vi", "Tóm tắt tiếng Việt"),
    ("abstract_en", "Tóm tắt tiếng Anh"),
    ("keywords_vi", "Từ khóa tiếng Việt"),
    ("keywords_en", "Từ khóa tiếng Anh"),
    ("introduction", "Giới thiệu / Đặt vấn đề"),
    ("methods", "Vật liệu và/hoặc phương pháp nghiên cứu"),
    ("results", "Kết quả và thảo luận"),
    ("conclusion", "Kết luận"),
    ("references", "Tài liệu tham khảo: APA, IEEE, Chicago, Vancouver"),
    ("appendix", "Phụ lục"),
    ("contributions", "Tuyên bố về đóng góp khoa học"),
    ("conflict_of_interest", "Cam kết về mâu thuẫn lợi ích"),
    ("acknowledgements", "Lời cảm ơn"),
]

REQUIRED: Dict[str, bool] = {k: False for k, _ in TARGETS}
for _k in [
    "title_vi",
    "title_en",
    "authors",
    "abstract_vi",
    "abstract_en",
    "keywords_vi",
    "keywords_en",
    "introduction",
    "methods",
    "results",
    "conclusion",
    "references",
]:
    REQUIRED[_k] = True


_EMAIL_RE = re.compile(r"\b\S+@\S+\.\S+\b")
_CONTACT_CUE_RE = re.compile(
    r"\b(email|e-mail|corresponding\s+author|tác\s+giả\s+liên\s+hệ|liên\s+hệ)\b",
    re.IGNORECASE,
)
_NAME_TOKEN_RE = re.compile(r"[A-ZÀ-Ỵ][a-zà-ỹ]{1,}")

_NON_NAME_TOKENS = {
    "abstract",
    "summary",
    "keywords",
    "keyword",
    "introduction",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "references",
    "appendix",
    "email",
    "mail",
    "address",
    "corresponding",
    "author",
    "tác",
    "giả",
    "liên",
    "hệ",
    "khoa",
    "viện",
    "trường",
    "department",
    "faculty",
    "institute",
    "university",
}


def _extract_front_block(view_text: str) -> str:
    """Lấy phần [FRONT] từ llm_view để hậu kiểm các field front-only."""
    text = view_text or ""
    front_tag = "[FRONT]"
    outline_tag = "[OUTLINE]"

    a = text.find(front_tag)
    if a == -1:
        return ""
    a += len(front_tag)

    b = text.find(outline_tag, a)
    if b == -1:
        b = len(text)

    return text[a:b].strip()


def _line_has_author_name(line: str) -> bool:
    """Ước lượng một dòng có chứa tên người (2-6 token dạng tên)."""
    if not line:
        return False

    scrub = _EMAIL_RE.sub(" ", line)
    scrub = _CONTACT_CUE_RE.sub(" ", scrub)

    tokens = [t for t in _NAME_TOKEN_RE.findall(scrub) if t.lower() not in _NON_NAME_TOKENS]
    return 2 <= len(tokens) <= 6


def _front_has_author_name_near_contact(front_text: str, window: int = 2) -> bool:
    """True nếu quanh dòng contact/email trong FRONT có dòng tên tác giả."""
    lines = [ln.strip() for ln in (front_text or "").splitlines() if ln.strip()]
    if not lines:
        return False

    contact_idxs = [
        i for i, line in enumerate(lines) if (_EMAIL_RE.search(line) or _CONTACT_CUE_RE.search(line))
    ]
    if not contact_idxs:
        return False

    for i in contact_idxs:
        lo = max(0, i - window)
        hi = min(len(lines), i + window + 1)
        for j in range(lo, hi):
            if _line_has_author_name(lines[j]):
                return True
    return False


def _is_email_only_authors_claim(auth_item: Dict[str, object], front_text: str) -> bool:
    """Demote authors=true khi evidence chỉ là contact/email và FRONT không thấy tên tác giả gần đó."""
    if not bool(auth_item.get("present", False)):
        return False

    evidence = str(auth_item.get("evidence") or "")
    reason = str(auth_item.get("reason") or "")
    probe = f"{evidence}\n{reason}".strip()

    has_contact_cue = bool(_EMAIL_RE.search(probe) or _CONTACT_CUE_RE.search(probe))
    if not has_contact_cue:
        return False

    # Nếu chính evidence đã có tên tác giả thì giữ nguyên.
    if _line_has_author_name(evidence):
        return False

    return not _front_has_author_name_near_contact(front_text)


def _init_hits() -> Dict[str, SectionHit]:
    return {k: SectionHit(status="missing") for k, _ in TARGETS}


def check_structure_docx(
    path: str,
    openai_model: str = DEFAULT_LLM_MODEL,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    parsed_paras: Optional[List[DocPara]] = None,
) -> Report:
    """Check presence các mục trong bài báo bằng LLM, trả về Report."""
    if not path or not isinstance(path, str):
        raise ValueError(f"Invalid path type: {type(path)}")

    p = Path(path)
    if not p.exists():
        logger.error("File not found: %s", path)
        raise FileNotFoundError(f"File not found: {path}")

    if p.suffix.lower() != ".docx":
        raise ValueError(f"Only .docx is supported, got: {p.suffix}")

    notes: List[str] = []
    notes.append(f"llm_model={openai_model}")
    notes.append(f"min_confidence={min_confidence}")

    # Parse DOCX
    paras = parsed_paras if parsed_paras is not None else extract_docx_paragraphs(str(p))
    if not paras:
        return Report(file=str(p), ok=False, sections=_init_hits(), notes=["Empty DOCX"])

    # Build view gọn để gửi LLM
    from utils.config import (
        LLM_VIEW_MAX_SECTIONS,
        LLM_VIEW_MAX_SECTION_CHARS,
        LLM_VIEW_MAX_FRONT_PARAS,
        LLM_VIEW_MAX_TAIL_PARAS,
    )

    view = build_llm_view(
        paras,
        max_sections=LLM_VIEW_MAX_SECTIONS,
        max_section_chars=LLM_VIEW_MAX_SECTION_CHARS,
        max_front_paras=LLM_VIEW_MAX_FRONT_PARAS,
        max_tail_paras=LLM_VIEW_MAX_TAIL_PARAS,
    )

    notes.append(f"llm_view_chars={len(view.view_text)}")
    notes.append(f"llm_view_sections={view.section_count}")

    hits = _init_hits()

    try:
        llm_out = llm_detect_structure(view_text=view.view_text, openai_model=openai_model)
    except Exception as e:
        # Fail-safe: không làm sập app, trả missing + notes
        logger.exception("LLM detect_structure failed")
        notes.append(f"LLM error: {e}")
        required_ids = [k for k, v in REQUIRED.items() if v]
        return Report(file=str(p), ok=False, sections=hits, notes=notes + [f"Required: {required_ids}"])

    sections = (llm_out or {}).get("sections") or {}
    references_style_llm = str((llm_out or {}).get("references_style") or "Unknown")

    # Guard deterministic: tránh false-positive authors khi chỉ có email/corresponding line.
    front_text = _extract_front_block(view.view_text)
    raw_authors = sections.get("authors") or {}
    if isinstance(raw_authors, dict) and _is_email_only_authors_claim(raw_authors, front_text):
        patched = dict(raw_authors)
        patched["present"] = False
        patched["confidence"] = 0.0
        patched["evidence"] = ""
        patched["reason"] = "Rejected: email/contact-only evidence without nearby author-name in FRONT."
        sections = dict(sections)
        sections["authors"] = patched
        notes.append("authors_guard=email_only_demoted")

    for key, _label in TARGETS:
        item = sections.get(key) or {}
        present = bool(item.get("present", False))
        try:
            conf = float(item.get("confidence", 0.0))
        except Exception:
            conf = 0.0
        evidence = str(item.get("evidence") or "")
        reason = str(item.get("reason") or "")

        if present and conf >= min_confidence:
            hits[key] = SectionHit(
                status="ok",
                evidence=evidence,
                llm_confidence=conf,
                notes=reason,
            )
        else:
            # Missing nhưng vẫn giữ hint để debug/UI
            hits[key] = SectionHit(
                status="missing",
                evidence=evidence if present else "",
                llm_confidence=conf,
                notes=reason,
            )

    # References style: ưu tiên LLM, fallback rule-based
    if hits.get("references") and hits["references"].status == "ok":
        style = references_style_llm.strip() or "Unknown"
        if style == "Unknown":
            try:
                style = guess_references_style(view.tail_text)
            except Exception:
                style = "Unknown"
        hits["references"].references_style = style

    required_ids = [k for k, v in REQUIRED.items() if v]
    ok = all(hits.get(k, SectionHit(status="missing")).status == "ok" for k in required_ids)

    return Report(file=str(p), ok=ok, sections=hits, notes=notes)
