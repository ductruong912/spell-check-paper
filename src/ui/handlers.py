"""Chạy song song: cấu trúc, chính tả, đạo văn."""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ----------------------------
# Bootstrap import (add src to sys.path)
# ----------------------------
BASE_DIR = Path(__file__).parent.parent.parent.resolve()
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from document_backend import check_plagiarism_in_file
from spell.checker import spellcheck_auto
from structure.checker import check_structure_docx
from utils.cache import DocumentCache
from utils.config import PLAGIARISM_TOPK
from utils.validation import get_user_friendly_error, APIValidationError

logger = logging.getLogger(__name__)

# ----------------------------
# Paths
# ----------------------------
PLAG_INDEX_DIR = str(SRC_DIR / "plag_index")


# ----------------------------
# Helpers
# ----------------------------
def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _top_sources_from_sources_list(sources: List[dict], k: int = 3) -> List[Dict[str, Any]]:
    """Rank sources theo score, trả schema {title,url,score}."""
    if not sources:
        return []

    def score(s: dict) -> float:
        return _safe_float(s.get("plagiat") or s.get("plagiarism") or s.get("score") or 0.0, 0.0)

    ranked = sorted([s for s in sources if isinstance(s, dict)], key=score, reverse=True)
    out: List[Dict[str, Any]] = []
    for s in ranked[:k]:
        title = (s.get("title") or "").strip() or "(Không có tiêu đề)"
        url = (s.get("url") or "").strip()
        sc = score(s)
        if title or url:
            out.append({"title": title, "url": url, "score": sc, "type_label": s.get("type_label")})
    return out


def _normalize_finding(fd: Dict[str, Any], k: int = 3) -> Dict[str, Any]:
    """Chuẩn hoá 1 finding để UI luôn có top_sources."""
    out = dict(fd or {})

    # 1) top_sources chuẩn
    if isinstance(out.get("top_sources"), list) and out["top_sources"]:
        norm: List[Dict[str, Any]] = []
        for s in out["top_sources"][:k]:
            if not isinstance(s, dict):
                continue
            norm.append(
                {
                    "title": (s.get("title") or "").strip() or "(Không có tiêu đề)",
                    "url": (s.get("url") or "").strip(),
                    "score": _safe_float(s.get("score") or s.get("plagiat") or s.get("plagiarism") or 0.0, 0.0),
                    "type_label": s.get("type_label"),
                }
            )
        out["top_sources"] = norm
        return out

    # 2) backend trả sources list đầy đủ
    sources = out.get("sources")
    if isinstance(sources, list) and sources:
        out["top_sources"] = _top_sources_from_sources_list(sources, k=k)
        return out

    # 3) fallback: top_source_* fields
    url = (out.get("top_source_url") or "").strip()
    title = (out.get("top_source_title") or "").strip() or "Nguồn hàng đầu"
    score = _safe_float(out.get("top_source_score") or 0.0, 0.0)
    if url or title:
        out["top_sources"] = [{"title": title, "url": url, "score": score}]
        return out

    # 4) fallback: top_source dict
    top = out.get("top_source")
    if isinstance(top, dict):
        out["top_sources"] = [
            {
                "title": (top.get("title") or "").strip() or "Nguồn hàng đầu",
                "url": (top.get("url") or "").strip(),
                "score": _safe_float(top.get("plagiat") or top.get("plagiarism") or 0.0, 0.0),
            }
        ]
        return out

    out["top_sources"] = []
    return out


def _normalize_plagiarism_result(result: Dict[str, Any], k: int = 3) -> Dict[str, Any]:
    """Chuẩn hoá output đạo văn để UI render ổn định."""
    if not isinstance(result, dict):
        return {"success": False, "overall_score": 0.0, "findings": [], "error": "Invalid plagiarism result"}

    out = dict(result)

    findings = out.get("findings")
    if not isinstance(findings, list):
        findings = []
    out["findings"] = [_normalize_finding(fd, k=k) for fd in findings if isinstance(fd, dict)]

    # overall_score backend đang dùng 0..1
    out["overall_score"] = _safe_float(out.get("overall_score") or 0.0, 0.0)

    return out


# ----------------------------
# Public handlers
# ----------------------------
def check_structure(file_path: str, doc_cache: DocumentCache) -> Dict[str, Any]:
    """Check cấu trúc bằng paras đã cache."""
    try:
        report = check_structure_docx(file_path, parsed_paras=doc_cache.paras)
        return {
            "ok": report.ok,
            "sections": {k: asdict(v) for k, v in report.sections.items()},
            "notes": report.notes,
        }
    except APIValidationError as e:
        logger.error("API validation failed (structure): %s", e.message_en)
        return {"ok": False, "sections": {}, "notes": [], "error": e.message_vi}
    except Exception as e:
        error_vi = get_user_friendly_error(e)
        logger.warning("Kiểm tra cấu trúc thất bại: %s", str(e)[:200])
        return {"ok": False, "sections": {}, "notes": [], "error": error_vi}


def check_spell(doc_cache: DocumentCache) -> Dict[str, Any]:
    """Check chính tả bằng text/ref_span đã cache."""
    try:
        result = spellcheck_auto(doc_cache.text, ref_span=doc_cache.ref_span)

        issues = result.get("issues", []) if isinstance(result, dict) else []
        total_words = result.get("total_words", doc_cache.word_count) if isinstance(result, dict) else doc_cache.word_count
        checked_words = result.get("checked_words", total_words) if isinstance(result, dict) else total_words
        meta = result.get("meta", {}) if isinstance(result, dict) else {}

        if "ref_span" not in meta and getattr(doc_cache, "ref_span", None):
            meta["ref_span"] = doc_cache.ref_span

        return {
            "issues": issues,
            "total_words": int(total_words or 0),
            "checked_words": int(checked_words or 0),
            "meta": meta,
            "success": True,
        }

    except APIValidationError as e:
        logger.error("API validation failed (spell): %s", e.message_en)
        return {
            "issues": [],
            "total_words": int(getattr(doc_cache, "word_count", 0) or 0),
            "checked_words": 0,
            "meta": {"ref_span": getattr(doc_cache, "ref_span", None)},
            "success": False,
            "error": e.message_vi,
        }
    except Exception as e:
        error_vi = get_user_friendly_error(e)
        logger.error("Kiểm tra chính tả thất bại: %s", str(e)[:200])
        return {
            "issues": [],
            "total_words": int(getattr(doc_cache, "word_count", 0) or 0),
            "checked_words": 0,
            "meta": {"ref_span": getattr(doc_cache, "ref_span", None)},
            "success": False,
            "error": error_vi,
        }


def check_plagiarism(file_path: str, doc_cache: DocumentCache) -> Dict[str, Any]:
    """Check đạo văn và chuẩn hoá output để UI mở đúng URL nguồn."""
    try:
        result = check_plagiarism_in_file(
            file_path,
            index_dir=PLAG_INDEX_DIR,
            topk=PLAGIARISM_TOPK,
            make_report=False,
            use_lsh_filter=True,
            use_fuzzy_match=False,
            use_llm_verify=False,
            parsed_paras=doc_cache.paras,
        )

        normalized = _normalize_plagiarism_result(result or {}, k=3)
        normalized["success"] = True
        return normalized

    except APIValidationError as e:
        logger.error("API validation failed (plagiarism): %s", e.message_en)
        return {"success": False, "overall_score": 0.0, "findings": [], "error": e.message_vi}
    except Exception as e:
        error_vi = get_user_friendly_error(e)
        logger.error("Kiểm tra đạo văn thất bại: %s", str(e)[:200])
        return {"success": False, "overall_score": 0.0, "findings": [], "error": error_vi}
