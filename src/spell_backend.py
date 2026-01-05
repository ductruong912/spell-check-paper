from __future__ import annotations

import os
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from docx import Document
from dotenv import load_dotenv

# Load env from root with override
root_dir = Path(__file__).parent.parent
load_dotenv(root_dir / ".env", override=True)

logger = logging.getLogger("spell_backend")

# ----------------------------
# PlagiarismSearch API config
# ----------------------------
API_USER = os.getenv("PLAGIARISMSEARCH_API_USER")
API_KEY = os.getenv("PLAGIARISMSEARCH_API_KEY")
PLAGIARISM_API_AVAILABLE = bool(API_USER and API_KEY)

if PLAGIARISM_API_AVAILABLE:
    logger.info("PlagiarismSearch API configured: %s", API_USER)
else:
    logger.warning("PlagiarismSearch API NOT configured in .env")

# Import plagiarism checker (API)
try:
    from plagiarismsearch_checker import (
        extract_sections_from_docx,
        _require_creds,
        PlagiarismSearchClient,
    )
except ImportError as e:
    logger.warning("Could not import plagiarismsearch_checker: %s", e)
    PLAGIARISM_API_AVAILABLE = False


# ----------------------------
# Helpers
# ----------------------------
def extract_text_from_docx(path: str) -> str:
    try:
        doc = Document(path)
        text_parts: List[str] = []
        for para in doc.paragraphs:
            text = (para.text or "").strip()
            if text:
                text_parts.append(text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error("Error extracting text from %s: %s", path, e)
        return ""


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _top_source_by_plagiat(sources: List[dict]) -> Optional[dict]:
    if not sources:
        return None
    return max(sources, key=lambda s: _safe_float(s.get("plagiat"), 0.0))


def _count_web_sources(sources: List[dict]) -> int:
    # PlagiarismSearch source object có type_label (log của bạn: 'web')
    c = 0
    for s in sources or []:
        if str(s.get("type_label") or "").lower() == "web":
            c += 1
    return c


# ----------------------------
# Main API plagiarism check
# ----------------------------
def check_plagiarism_in_file(
    file_path: str,
    index_dir: str = "",          # kept for compatibility (unused)
    topk: int = 10,               # kept for compatibility (unused)
    make_report: bool = False,    # kept for compatibility (unused)
    use_lsh_filter: bool = True,  # kept for compatibility (unused)
    use_fuzzy_match: bool = False,# kept for compatibility (unused)
    use_llm_verify: bool = False, # kept for compatibility (unused)
    *,
    min_words_per_section: int = 80,
    timeout_s: int = 600,
    poll_s: float = 5.0,
) -> Dict[str, Any]:
    try:
        # Extract full text for total word count (UI metric)
        full_text = extract_text_from_docx(file_path)
        if not full_text:
            return {"success": False, "error": "Failed to extract text from file"}

        total_words = len(full_text.split())

        # No API creds => return safe fallback
        if not PLAGIARISM_API_AVAILABLE:
            return {
                "success": True,
                "overall_score": 0.0,
                "findings": [],
                "total_chunks": 0,
                "total_words": total_words,
                "note": "PlagiarismSearch API not configured (missing API keys in .env)",
            }

        _require_creds()
        client = PlagiarismSearchClient(API_USER, API_KEY)

        sections = extract_sections_from_docx(file_path)
        if not sections:
            return {
                "success": True,
                "overall_score": 0.0,
                "findings": [],
                "total_chunks": 0,
                "total_words": total_words,
                "note": "No sections detected by heading patterns",
            }

        findings: List[Dict[str, Any]] = []

        # Weighted overall = sum(similarity% * checked_words) / sum(checked_words)
        total_checked_words = 0
        weighted_sum = 0.0

        checked_sections = 0

        for name, text in sections.items():
            # Skip references bucket
            if name in {"references", "tài liệu tham khảo"}:
                continue

            section_words_local = len((text or "").split())
            if section_words_local < min_words_per_section:
                continue

            remote_id = f"{os.path.basename(file_path)}#{name}"
            logger.info("Checking section: %s (%s words)", name, section_words_local)

            try:
                created = client.create_report(text=text, remote_id=remote_id)

                # IMPORTANT: show_relations=-2 in plagiarismsearch_checker.py (you already patched there)
                data = client.wait_checked(created.report_id, timeout_s=timeout_s, poll_s=poll_s)

                similarity = _safe_float(data.get("similarity"), 0.0)  # % 0..100
                originality = _safe_float(data.get("originality"), 0.0)

                checked_words = _safe_int(data.get("checked_words"), default=0)
                if checked_words <= 0:
                    # fallback nếu API không set checked_words
                    checked_words = section_words_local

                sources = data.get("sources") or []
                web_sources_count = _count_web_sources(sources)
                top_source = _top_source_by_plagiat(sources)

                # Weighted aggregation
                total_checked_words += checked_words
                weighted_sum += similarity * checked_words

                checked_sections += 1

                # Keep finding ALWAYS if similarity > 0 (không skip nữa)
                finding: Dict[str, Any] = {
                    "chunk_index": checked_sections,
                    "label": name,
                    "similarity": similarity,  # % for THIS section
                    "originality": originality,
                    "checked_words": checked_words,
                    "sources_count": len(sources),
                    "sources_web_count": web_sources_count,
                    "report_link": data.get("link"),
                    "text": (text[:500] + "...") if len(text) > 500 else text,
                }

                if top_source:
                    finding["top_source"] = {
                        "title": top_source.get("title"),
                        "url": top_source.get("url"),
                        "type_label": top_source.get("type_label"),
                        "plagiat": _safe_float(top_source.get("plagiat"), 0.0),
                        "matches": _safe_int(top_source.get("matches"), 0),
                        "matched_words": _safe_int(top_source.get("matched_words"), 0),
                        "view_url": top_source.get("view_url"),
                    }

                findings.append(finding)

                logger.info(
                    "Section=%s similarity=%.2f%% checked_words=%s sources=%s web_sources=%s",
                    name, similarity, checked_words, len(sources), web_sources_count
                )

            except Exception as e:
                logger.warning("Error checking section %s: %s", name, e)
                continue

        overall_similarity = (weighted_sum / total_checked_words) if total_checked_words > 0 else 0.0
        overall_score = overall_similarity / 100.0

        return {
            "success": True,
            "overall_score": overall_score,
            "overall_similarity": overall_similarity,
            "findings": findings,
            "total_chunks": checked_sections,
            "total_words": total_words,
        }

    except Exception as e:
        logger.error("Plagiarism check error: %s", e)
        return {"success": False, "error": str(e)}
