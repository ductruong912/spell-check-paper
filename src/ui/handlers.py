"""Run document structure checks for the UI."""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).parent.parent.parent.resolve()
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from structure.checker import check_structure_docx
from utils import DocumentCache
from utils.validation import APIValidationError, get_user_friendly_error

logger = logging.getLogger(__name__)


def check_structure(file_path: str, doc_cache: DocumentCache) -> Dict[str, Any]:
    """Check paper structure with cached paragraphs."""
    try:
        report = check_structure_docx(file_path, parsed_paras=doc_cache.paras)
        return {
            "ok": report.ok,
            "sections": {key: asdict(value) for key, value in report.sections.items()},
            "notes": report.notes,
        }
    except APIValidationError as exc:
        logger.error("API validation failed (structure): %s", exc.message_en)
        return {"ok": False, "sections": {}, "notes": [], "error": exc.message_vi}
    except Exception as exc:
        error_vi = get_user_friendly_error(exc)
        logger.warning("Structure check failed: %s", str(exc)[:200])
        return {"ok": False, "sections": {}, "notes": [], "error": error_vi}
