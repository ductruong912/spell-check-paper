from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, List

from docx import Document
from dotenv import load_dotenv

# ----------------------------
# Env + logging
# ----------------------------
root_dir = Path(__file__).parent.parent
load_dotenv(root_dir / ".env", override=True)

logger = logging.getLogger("document_backend")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ----------------------------
# Plagiarism imports (optional)
# ----------------------------
PLAGIARISM_API_AVAILABLE = True
try:
    from plagiarism.checker import check_plagiarism_body_only
    from plagiarism.api_client import _require_creds
except Exception as e:
    logger.warning("Could not import plagiarism checker: %s", e)
    PLAGIARISM_API_AVAILABLE = False


# ----------------------------
# Helpers
# ----------------------------
def extract_text_from_docx(path: str) -> str:
    """Extract text đơn giản (phục vụ UI spell/word count)."""
    try:
        if not path or not isinstance(path, str):
            logger.error("Invalid path: %s", path)
            return ""

        p = Path(path)
        if not p.exists():
            logger.error("File not found: %s", path)
            return ""

        logger.debug("Extracting text from: %s", path)
        doc = Document(path)
        parts: List[str] = []
        for para in doc.paragraphs:
            t = (para.text or "").strip()
            if t:
                parts.append(t)

        result = "\n".join(parts)
        logger.debug("Successfully extracted %d chars from %s", len(result), p.name)
        return result

    except FileNotFoundError as e:
        logger.error("File not found: %s: %s", path, e)
        return ""
    except Exception as e:
        logger.error("Error extracting text from %s: %s", path, e, exc_info=True)
        return ""


def _empty_plagiarism_result(*, total_words: int, note: str) -> Dict[str, Any]:
    """Schema rỗng để UI hiển thị note thay vì crash."""
    return {
        "success": True,          # UI: show note, không coi là lỗi
        "overall_score": 0.0,     # 0..1
        "findings": [],
        "total_chunks": 0,
        "total_words": int(total_words or 0),
        "note": note,
    }


# ----------------------------
# Public API
# ----------------------------
def check_plagiarism_in_file(
    file_path: str,
    parsed_paras: Optional[List] = None,
) -> Dict[str, Any]:
    """Wrapper cho UI: gọi Turnitin/iThenticate (giữ signature tương thích)."""
    try:
        if not file_path or not isinstance(file_path, str):
            logger.error("Invalid file_path: %s", file_path)
            return {"success": False, "overall_score": 0.0, "findings": [], "error": "Invalid file path"}

        p = Path(file_path)
        if not p.exists():
            logger.error("Plagiarism check: file not found: %s", file_path)
            return {"success": False, "overall_score": 0.0, "findings": [], "error": "File not found"}

        logger.info("Starting plagiarism check: %s", p.name)

        # Ưu tiên parsed_paras để lấy text nhanh và nhất quán
        if parsed_paras is not None:
            logger.debug("Using cached paragraphs (%d paras) for plagiarism word_count", len(parsed_paras))
            full_text = "\n".join((pp.text for pp in parsed_paras if getattr(pp, "text", None)))
        else:
            logger.debug("Parsing DOCX for plagiarism word_count: %s", file_path)
            full_text = extract_text_from_docx(file_path)

        if not full_text:
            logger.warning("No text extracted from %s", file_path)
            return {"success": False, "overall_score": 0.0, "findings": [], "error": "Failed to extract text from file"}

        total_words = len(full_text.split())
        logger.debug("Extracted %d words from %s", total_words, p.name)

        # 1) Module không sẵn
        if not PLAGIARISM_API_AVAILABLE:
            logger.warning("Turnitin module not available")
            return _empty_plagiarism_result(
                total_words=total_words,
                note="Module Turnitin/iThenticate không khả dụng (import thất bại).",
            )

        # 2) Creds chưa ok
        try:
            api_key_used, _ = _require_creds()
            logger.info("Turnitin API configured: %s...", api_key_used[:5])
        except Exception as e:
            logger.warning("Turnitin API not configured/invalid: %s", str(e)[:200])
            return _empty_plagiarism_result(
                total_words=total_words,
                note="Turnitin API chưa được cấu hình hoặc không hợp lệ",
            )

        # 3) Call checker
        logger.debug("Submitting file for plagiarism check (timeout=900s)")
        result = check_plagiarism_body_only(
            docx_path=file_path,
            timeout_s=900,
        ) or {}

        # 4) Normalize schema cho UI
        out: Dict[str, Any] = dict(result)
        out["success"] = bool(out.get("success", True))
        out["overall_score"] = float(out.get("overall_score") or 0.0)
        out["findings"] = out.get("findings") or []
        out["total_chunks"] = int(out.get("total_chunks") or len(out["findings"]) or 0)
        out["total_words"] = int(total_words or 0)

        logger.info("Plagiarism check completed. overall_score=%.4f", out["overall_score"])
        return out

    except Exception as e:
        logger.error("Plagiarism check error: %s", e, exc_info=True)
        return {"success": False, "overall_score": 0.0, "findings": [], "error": str(e)}
