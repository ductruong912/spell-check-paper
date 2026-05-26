"""Turnitin plagiarism check orchestration.

This module keeps the UI-facing result schema stable while the exact
customer-provided Turnitin API shape is still subject to change.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.config import DEFAULT_CREATE_PAYLOAD, REPORT_POLL_INTERVAL
from utils.document_parser import extract_docx_paragraphs

from .api_client import CreateResult, TurnitinClient, _require_creds

logger = logging.getLogger("plagiarism_checker")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _document_word_count(docx_path: str) -> int:
    try:
        paras = extract_docx_paragraphs(docx_path)
    except Exception:
        logger.debug("Could not parse DOCX for word count: %s", docx_path, exc_info=True)
        return 0
    return sum(len((para.text or "").split()) for para in paras)


def _first_present(data: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _similarity_percent(report: Dict[str, Any]) -> float:
    raw = _first_present(
        report,
        [
            "similarity",
            "similarity_score",
            "overall_similarity",
            "overall_match_percentage",
            "score",
        ],
    )
    value = _safe_float(raw, 0.0)
    return value * 100.0 if 0.0 < value <= 1.0 else value


def _report_link(report: Dict[str, Any]) -> str:
    direct = _first_present(report, ["link", "report_link", "viewer_url", "url", "pdf_url"])
    if direct:
        return str(direct).strip()

    links = report.get("links")
    if isinstance(links, dict):
        nested = _first_present(links, ["viewer", "report", "pdf", "self"])
        if nested:
            return str(nested).strip()

    return ""


def _source_score(source: Dict[str, Any]) -> float:
    return _safe_float(
        _first_present(source, ["score", "plagiat", "plagiarism", "similarity", "match_percentage"]),
        0.0,
    )


def _top_sources(sources: List[dict], k: int = 3) -> List[Dict[str, Any]]:
    ranked = sorted((source for source in sources if isinstance(source, dict)), key=_source_score, reverse=True)
    out: List[Dict[str, Any]] = []
    for source in ranked[:k]:
        out.append(
            {
                "title": (source.get("title") or source.get("name") or "").strip() or "(Khong co tieu de)",
                "url": (source.get("url") or source.get("link") or "").strip(),
                "score": _source_score(source),
                "type_label": (source.get("type_label") or source.get("type") or "").strip(),
            }
        )
    return out


def _report_sources(report: Dict[str, Any]) -> List[dict]:
    for key in ("sources", "matches", "top_sources"):
        value = report.get(key)
        if isinstance(value, list):
            return value
    return []


def _finding_from_report(report: Dict[str, Any], *, total_words: int) -> Dict[str, Any]:
    similarity = _similarity_percent(report)
    sources = _report_sources(report)
    try:
        checked_words = int(report.get("checked_words") or total_words)
    except Exception:
        checked_words = total_words

    return {
        "chunk_index": 1,
        "label": "Full document",
        "similarity": similarity,
        "checked_words": checked_words,
        "sources_count": len(sources),
        "top_sources": _top_sources(sources, k=3),
        "report_link": _report_link(report),
    }


def check_plagiarism_body_only(docx_path: str, timeout_s: int = 600) -> Dict[str, Any]:
    """Upload one DOCX to Turnitin and return the UI-facing plagiarism schema."""
    path = Path(docx_path)
    if not path.exists():
        return {"success": False, "overall_score": 0.0, "findings": [], "error": "File not found"}

    total_words = _document_word_count(str(path))
    api_key, api_secret = _require_creds()
    client = TurnitinClient(api_key, api_secret)

    remote_id = f"{os.path.basename(str(path))}#FULL"
    created = client.create_report(
        file_path=str(path),
        remote_id=remote_id,
        payload_extra=dict(DEFAULT_CREATE_PAYLOAD),
    )
    report = client.wait_checked(
        created.report_id,
        timeout_s=timeout_s,
        poll_s=REPORT_POLL_INTERVAL,
    )

    finding = _finding_from_report(report, total_words=total_words)
    overall_score = finding["similarity"] / 100.0

    return {
        "success": True,
        "overall_score": overall_score,
        "findings": [finding],
        "total_chunks": 1,
        "total_words": total_words,
        "turnitin_submission_id": created.report_id,
    }


def check_plagiarism_full(
    docx_path: str,
    check_body: bool = True,
    check_references: bool = True,
    timeout_s: int = 600,
) -> Dict[str, Any]:
    """Compatibility wrapper; Turnitin receives the full DOCX as one submission."""
    del check_body, check_references
    return check_plagiarism_body_only(docx_path, timeout_s=timeout_s)
