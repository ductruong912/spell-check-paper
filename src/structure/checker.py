"""Main structure checking logic for academic papers."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from utils.config import DEFAULT_LLM_MODEL, DEFAULT_MIN_CONFIDENCE

from .parser import DocPara, extract_docx_paragraphs, split_by_heading1
from .classifier import llm_classify_chunk, guess_references_style

# Logging
logger = logging.getLogger("structure_checker")

# Constants
MAX_FRONTMATTER_CHUNKS = 20

# -----------------------------
# Targets
# -----------------------------
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
    ("acknowledgements", "Lời cảm ơn đối với cơ quan tài trợ và/hoặc tổ chức, cá nhân liên quan"),
]

REQUIRED: Dict[str, bool] = {
    "title_vi": True,
    "title_en": True,
    "authors": True,
    "abstract_vi": True,
    "abstract_en": True,
    "keywords_vi": True,
    "keywords_en": True,
    "introduction": True,
    "methods": True,
    "results": True,
    "conclusion": True,
    "references": True,
    "appendix": False,
    "contributions": False,
    "conflict_of_interest": False,
    "acknowledgements": False,
}

FRONTMATTER_TARGETS = {
    "title_vi",
    "title_en",
    "authors",
    "abstract_vi",
    "abstract_en",
    "keywords_vi",
    "keywords_en",
}


# -----------------------------
# Models
# -----------------------------
@dataclass
class SectionHit:
    status: str  # "ok" | "missing"
    evidence: Optional[str] = None  # heading text or "frontmatter"
    llm_verified: Optional[bool] = None
    llm_confidence: float = 0.0
    llm_label: Optional[str] = None
    notes: Optional[str] = None
    references_style: Optional[str] = None  # APA/IEEE/Chicago/Vancouver/Unknown


@dataclass
class Report:
    file: str
    ok: bool
    sections: Dict[str, SectionHit]
    notes: List[str]


@dataclass
class SectionResult:
    """Result of section classification."""
    label_id: str
    confidence: float
    reason: str


# ─────────────────────────────────────────
# Main checker
# ─────────────────────────────────────────
def check_structure_docx(
    path: str,
    openai_model: str = DEFAULT_LLM_MODEL,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    parsed_paras: Optional[List[DocPara]] = None
) -> Report:
    """Check if a DOCX file contains all required academic paper sections."""
    # Input validation
    if not path or not isinstance(path, str):
        raise ValueError(f"Invalid path type: {type(path)}")
    
    p = Path(path)
    if not p.exists():
        logger.error(f"File not found: {path}")
        raise FileNotFoundError(f"File not found: {path}")
    
    if p.suffix.lower() != ".docx":
        raise ValueError(f"Only .docx files supported, got: {p.suffix}")
    
    if not (0.0 <= min_confidence <= 1.0):
        raise ValueError(f"min_confidence must be 0..1, got: {min_confidence}")
    
    logger.info(f"Starting structure check: {p.name}")

    # OPTIMIZATION: Use cached paragraphs if provided, else parse DOCX
    if parsed_paras is not None:
        logger.debug(f"Using cached paragraphs ({len(parsed_paras)} paras)")
        paras = parsed_paras
    else:
        logger.debug(f"Parsing DOCX from file: {p.name}")
        paras = extract_docx_paragraphs(str(p))
    
    if not paras:
        logger.warning(f"No paragraphs found in {p.name}")
        return Report(file=str(p), ok=False, sections={}, notes=["Tài liệu trống"])

    frontmatter_text, h1_sections = split_by_heading1(paras)

    notes: List[str] = [f"Đoạn văn={len(paras)}", f"Mục Heading1={len(h1_sections)}"]
    hits: Dict[str, SectionHit] = {tid: SectionHit(status="missing") for tid, _ in TARGETS}

    # 1) Frontmatter
    front_chunks: List[str] = []
    if frontmatter_text:
        front_chunks = [c.strip() for c in frontmatter_text.split("\n\n") if c.strip()][:MAX_FRONTMATTER_CHUNKS]

    if front_chunks:
        notes.append(f"Khối phần đầu={len(front_chunks)}")
        for idx, chunk in enumerate(front_chunks):
            label_id, conf, reason = llm_classify_chunk(
                heading=f"FRONTMATTER_CHUNK_{idx+1}",
                content=chunk,
                openai_model=openai_model,
            )
            if label_id in FRONTMATTER_TARGETS and conf >= min_confidence:
                prev = hits[label_id]
                if prev.status != "ok" or conf > prev.llm_confidence:
                    logger.debug(f"Frontmatter chunk #{idx+1}: classified as {label_id} (confidence={conf:.2f})")
                    hits[label_id] = SectionHit(
                        status="ok",
                        evidence="frontmatter",
                        llm_verified=True,
                        llm_confidence=conf,
                        llm_label=label_id,
                        notes=reason,
                    )

    # 2) Heading1 sections
    for s in h1_sections:
        label_id, conf, reason = llm_classify_chunk(s.heading, s.content, openai_model=openai_model)
        if label_id in hits and label_id != "NONE" and conf >= min_confidence:
            prev = hits[label_id]
            if prev.status != "ok" or conf > prev.llm_confidence:
                logger.debug(f"Section '{s.heading}': classified as {label_id} (confidence={conf:.2f})")
                hits[label_id] = SectionHit(
                    status="ok",
                    evidence=s.heading,
                    llm_verified=True,
                    llm_confidence=conf,
                    llm_label=label_id,
                    notes=reason,
                )
        if label_id == "references" and conf >= min_confidence:
            hits["references"].references_style = guess_references_style(s.content)
            logger.debug(f"References style detected: {hits['references'].references_style}")

    # 3) Heuristic fallback for references heading match
    if hits["references"].status != "ok":
        for s in h1_sections:
            hl = (s.heading or "").lower()
            if "tài liệu tham khảo" in hl or "tai lieu tham khao" in hl or "references" in hl or "bibliography" in hl:
                logger.debug(f"References section matched by heuristic fallback: '{s.heading}'")
                hits["references"] = SectionHit(
                    status="ok",
                    evidence=s.heading,
                    llm_verified=False,
                    llm_confidence=0.0,
                    llm_label="references",
                    notes="Khớp heading; LLM không được dùng hoặc dưới ngưỡng",
                    references_style=guess_references_style(s.content),
                )
                break

    # 4) Final OK check
    ok = True
    for tid, _ in TARGETS:
        if REQUIRED.get(tid, False) and hits[tid].status != "ok":
            ok = False
            logger.warning(f"Missing required section: {tid}")
            notes.append(f"Thiếu bắt buộc: {tid}")

    if hits["references"].status == "ok":
        rs = hits["references"].references_style or "Unknown"
        if rs not in {"APA", "IEEE", "Chicago", "Vancouver"}:
            logger.warning(f"References format not identified: {rs}")
            notes.append("Định dạng tài liệu tham khảo không xác định được (APA/IEEE/Chicago/Vancouver)")

    logger.info(f"Structure check completed: ok={ok}, found {sum(1 for h in hits.values() if h.status == 'ok')} sections")
    return Report(file=str(p), ok=ok, sections=hits, notes=notes)
