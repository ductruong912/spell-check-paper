from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from utils.config import DEFAULT_LLM_MODEL, DEFAULT_MIN_CONFIDENCE

from .parser import DocPara, build_llm_view, extract_docx_paragraphs
from .classifier import guess_references_style, llm_detect_structure

logger = logging.getLogger("structure_checker")


# ─────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────
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


# ─────────────────────────────────────────
# Targets / Required
# ─────────────────────────────────────────
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


def _init_hits() -> Dict[str, SectionHit]:
    return {k: SectionHit(status="missing") for k, _ in TARGETS}


def check_structure_docx(
    path: str,
    openai_model: str = DEFAULT_LLM_MODEL,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    parsed_paras: Optional[List[DocPara]] = None,
) -> Report:
    """Kiểm tra cấu trúc bài báo (presence) bằng LLM.

    Trả về Report với sections[*].status = ok/missing.
    """

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

    # Build compact view for LLM
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
        # Fail-safe: do not crash the whole app; return missing with notes
        logger.exception("LLM detect_structure failed")
        notes.append(f"LLM error: {e}")
        required_ids = [k for k, v in REQUIRED.items() if v]
        return Report(file=str(p), ok=False, sections=hits, notes=notes + [f"Required: {required_ids}"])

    sections = (llm_out or {}).get("sections") or {}
    references_style_llm = str((llm_out or {}).get("references_style") or "Unknown")

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
            # Keep missing but preserve low-confidence hints for debugging/UI
            hits[key] = SectionHit(
                status="missing",
                evidence=evidence if present else "",
                llm_confidence=conf,
                notes=reason,
            )

    # References style (optional): keep it cheap and deterministic
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
