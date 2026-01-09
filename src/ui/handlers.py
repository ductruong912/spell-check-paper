"""Parallel task handlers for structure, spell, and plagiarism checks."""
import logging
from typing import Dict, Any
from dataclasses import asdict
from pathlib import Path
import sys

# Add src to path for backend imports
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

# Plagiarism index directory
PLAG_INDEX_DIR = str(SRC_DIR / "plag_index")


def check_structure(file_path: str, doc_cache: DocumentCache) -> Dict[str, Any]:
    """Check document structure using cached paragraphs."""
    try:
        report = check_structure_docx(file_path, parsed_paras=doc_cache.paras)
        return {
            "ok": report.ok,
            "sections": {k: asdict(v) for k, v in report.sections.items()},
            "notes": report.notes,
        }
    except APIValidationError as e:
        logger.error(f"API validation failed: {e.message_en}")
        return {
            "ok": False,
            "sections": {},
            "notes": [],
            "error": e.message_vi,
        }
    except Exception as e:
        error_vi = get_user_friendly_error(e)
        logger.warning(f"Kiểm tra cấu trúc thất bại: {str(e)[:100]}")
        return {
            "ok": False,
            "sections": {},
            "notes": [],
            "error": error_vi,
        }


def check_spell(doc_cache: DocumentCache) -> Dict[str, Any]:
    """Check spelling using cached text."""
    try:
        # Spellcheck on cached text; pass cached reference span to skip references
        result = spellcheck_auto(doc_cache.text, ref_span=doc_cache.ref_span)

        # Be robust to different return shapes
        issues = result.get("issues", []) if isinstance(result, dict) else []
        total_words = result.get("total_words", doc_cache.word_count) if isinstance(result, dict) else doc_cache.word_count
        checked_words = result.get("checked_words", total_words) if isinstance(result, dict) else total_words
        meta = result.get("meta", {}) if isinstance(result, dict) else {}

        # If spellchecker already computed ref_span, keep it for UI/debug
        if "ref_span" not in meta and getattr(doc_cache, "ref_span", None):
            meta["ref_span"] = doc_cache.ref_span

        return {
            "issues": issues,
            "total_words": total_words,
            "checked_words": checked_words,
            "meta": meta,
            "success": True,
        }

    except APIValidationError as e:
        logger.error(f"API validation failed: {e.message_en}")
        return {
            "issues": [],
            "total_words": doc_cache.word_count,
            "checked_words": 0,
            "meta": {"ref_span": getattr(doc_cache, "ref_span", None)},
            "success": False,
            "error": e.message_vi,
        }
    except Exception as e:
        error_vi = get_user_friendly_error(e)
        logger.error(f"Kiểm tra chính tả thất bại: {str(e)[:100]}")
        return {
            "issues": [],
            "total_words": doc_cache.word_count,
            "checked_words": 0,
            "meta": {"ref_span": getattr(doc_cache, "ref_span", None)},
            "success": False,
            "error": error_vi,
        }


def check_plagiarism(file_path: str, doc_cache: DocumentCache) -> Dict[str, Any]:
    """Check plagiarism using cached paragraphs."""
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
        result["success"] = True
        return result
    except APIValidationError as e:
        logger.error(f"API validation failed: {e.message_en}")
        return {
            "success": False,
            "overall_score": 0.0,
            "findings": [],
            "error": e.message_vi,
        }
    except Exception as e:
        error_vi = get_user_friendly_error(e)
        logger.error(f"Kiểm tra đạo văn thất bại: {str(e)[:100]}")
        return {
            "success": False,
            "overall_score": 0.0,
            "findings": [],
            "error": error_vi,
        }
