from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from utils.config import DEFAULT_LLM_MODEL, DEFAULT_MIN_CONFIDENCE
from utils.document_parser import (
    DocPara,
    extract_docx_paragraphs,
    paragraphs_to_full_text,
    paragraphs_to_structured_docx_view,
)

from .classifier import TARGETS, llm_detect_structure

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


REQUIRED_IDS = {
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
}

REQUIRED: Dict[str, bool] = {key: key in REQUIRED_IDS for key, _label in TARGETS}


def _init_hits() -> Dict[str, SectionHit]:
    return {key: SectionHit(status="missing") for key, _label in TARGETS}


def check_structure_docx(
    path: str,
    openai_model: str = DEFAULT_LLM_MODEL,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    parsed_paras: Optional[List[DocPara]] = None,
) -> Report:
    """Check paper structure by sending a structured DOCX view to the LLM."""
    if not path or not isinstance(path, str):
        raise ValueError(f"Invalid path type: {type(path)}")

    p = Path(path)
    if not p.exists():
        logger.error("File not found: %s", path)
        raise FileNotFoundError(f"File not found: {path}")

    if p.suffix.lower() != ".docx":
        raise ValueError(f"Only .docx is supported, got: {p.suffix}")

    notes: List[str] = [
        f"llm_model={openai_model}",
        f"min_confidence={min_confidence}",
    ]

    paras = parsed_paras if parsed_paras is not None else extract_docx_paragraphs(str(p))
    full_text = paragraphs_to_full_text(paras)
    if not full_text:
        return Report(file=str(p), ok=False, sections=_init_hits(), notes=["Empty DOCX"])
    docx_view = paragraphs_to_structured_docx_view(paras)

    notes.append(f"full_text_chars={len(full_text)}")
    notes.append(f"full_text_paragraphs={len(paras)}")
    notes.append(f"docx_view_chars={len(docx_view)}")

    hits = _init_hits()

    try:
        llm_out = llm_detect_structure(view_text=docx_view, openai_model=openai_model)
    except Exception as e:
        logger.exception("LLM detect_structure failed")
        notes.append(f"LLM error: {e}")
        required_ids = [key for key, required in REQUIRED.items() if required]
        return Report(file=str(p), ok=False, sections=hits, notes=notes + [f"Required: {required_ids}"])

    sections = (llm_out or {}).get("sections") or {}
    references_style = str((llm_out or {}).get("references_style") or "Unknown").strip() or "Unknown"

    for key, _label in TARGETS:
        item = sections.get(key) or {}
        present = bool(item.get("present", False))
        try:
            confidence = float(item.get("confidence", 0.0))
        except Exception:
            confidence = 0.0

        evidence = str(item.get("evidence") or "")
        reason = str(item.get("reason") or "")

        if present and confidence >= min_confidence:
            hits[key] = SectionHit(
                status="ok",
                evidence=evidence,
                llm_confidence=confidence,
                notes=reason,
            )
        else:
            hits[key] = SectionHit(
                status="missing",
                evidence=evidence if present else "",
                llm_confidence=confidence,
                notes=reason,
            )

    if hits.get("references") and hits["references"].status == "ok":
        hits["references"].references_style = references_style

    required_ids = [key for key, required in REQUIRED.items() if required]
    ok = all(hits.get(key, SectionHit(status="missing")).status == "ok" for key in required_ids)

    return Report(file=str(p), ok=ok, sections=hits, notes=notes)
