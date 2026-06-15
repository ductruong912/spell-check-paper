from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from config import DEFAULT_LLM_MODEL, DEFAULT_MIN_CONFIDENCE
from documents import (
    DocPara,
    extract_document_paragraphs,
    paragraphs_to_full_text,
    paragraphs_to_structured_document_view,
)

from .classifier import llm_detect_structure
from .models import SectionHit, StructureReport
from .template import REQUIRED, REQUIRED_IDS, STRUCTURE_TEMPLATE, TARGETS

logger = logging.getLogger("structure_checker")


def _init_hits() -> Dict[str, SectionHit]:
    return {key: SectionHit(status="missing") for key, _label in TARGETS}


def _build_report(
    *,
    file: str,
    ok: bool,
    sections: Dict[str, SectionHit],
    notes: List[str],
    error: Optional[str] = None,
) -> StructureReport:
    return StructureReport(
        file=file,
        ok=ok,
        sections=sections,
        template_name=STRUCTURE_TEMPLATE.name,
        template_version=STRUCTURE_TEMPLATE.version,
        required_ids=set(REQUIRED_IDS),
        debug_info={"notes": notes},
        error=error,
        section_labels=dict(TARGETS),
    )


def check_structure_document(
    path: str,
    openai_model: str = DEFAULT_LLM_MODEL,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    parsed_paras: Optional[List[DocPara]] = None,
    source_type: Optional[str] = None,
) -> StructureReport:
    """Check paper structure by sending a structured document view to the LLM."""
    if not path or not isinstance(path, str):
        raise ValueError(f"Invalid path type: {type(path)}")

    p = Path(path)
    if not p.exists():
        logger.error("File not found: %s", path)
        raise FileNotFoundError(f"File not found: {path}")

    notes: List[str] = [
        f"llm_model={openai_model}",
        f"min_confidence={min_confidence}",
    ]

    detected_source_type = source_type or p.suffix.lower().lstrip(".") or "document"
    paras = parsed_paras if parsed_paras is not None else extract_document_paragraphs(str(p))
    full_text = paragraphs_to_full_text(paras)
    if not full_text:
        return _build_report(
            file=str(p),
            ok=False,
            sections=_init_hits(),
            notes=["Empty document"],
        )
    document_view = paragraphs_to_structured_document_view(paras, source_type=detected_source_type)

    notes.append(f"full_text_chars={len(full_text)}")
    notes.append(f"full_text_paragraphs={len(paras)}")
    notes.append(f"document_view_chars={len(document_view)}")

    hits = _init_hits()

    try:
        llm_out = llm_detect_structure(view_text=document_view, openai_model=openai_model)
    except Exception as e:
        logger.exception("LLM detect_structure failed")
        notes.append(f"LLM error: {e}")
        required_ids = [key for key, required in REQUIRED.items() if required]
        return _build_report(
            file=str(p),
            ok=False,
            sections=hits,
            notes=notes + [f"Required: {required_ids}"],
            error=str(e),
        )

    sections = (llm_out or {}).get("sections") or {}

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

    required_ids = [key for key, required in REQUIRED.items() if required]
    ok = all(hits.get(key, SectionHit(status="missing")).status == "ok" for key in required_ids)

    return _build_report(file=str(p), ok=ok, sections=hits, notes=notes)


def check_structure_docx(
    path: str,
    openai_model: str = DEFAULT_LLM_MODEL,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    parsed_paras: Optional[List[DocPara]] = None,
) -> StructureReport:
    """Check DOCX paper structure. Kept for backwards-compatible imports."""
    return check_structure_document(
        path,
        openai_model=openai_model,
        min_confidence=min_confidence,
        parsed_paras=parsed_paras,
        source_type="docx",
    )
