from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, List

from docx import Document
from dotenv import load_dotenv

from utils.disk_cache import get_file_hash, save_to_cache, load_from_cache

# Load env from root with override
root_dir = Path(__file__).parent.parent
load_dotenv(root_dir / ".env", override=True)

logger = logging.getLogger("document_backend")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

API_USER = os.getenv("PLAGIARISMSEARCH_API_USER")
API_KEY = os.getenv("PLAGIARISMSEARCH_API_KEY")
PLAGIARISM_API_AVAILABLE = bool(API_USER and API_KEY)

if PLAGIARISM_API_AVAILABLE:
    logger.info("PlagiarismSearch API configured: %s", API_USER)
else:
    logger.warning("PlagiarismSearch API NOT configured in .env")


# Import plagiarism checker
try:
    from plagiarism.checker import check_plagiarism_body_only
    from plagiarism.api_client import _require_creds
except Exception as e:
    logger.warning("Could not import plagiarism checker: %s", e)
    PLAGIARISM_API_AVAILABLE = False


def extract_text_from_docx(path: str) -> str:
    """Simple text extraction for spell UI + word count."""
    try:
        if not path or not isinstance(path, str):
            logger.error(f"Invalid path: {path}")
            return ""
        
        from pathlib import Path
        if not Path(path).exists():
            logger.error(f"File not found: {path}")
            return ""
        
        logger.debug(f"Extracting text from: {path}")
        doc = Document(path)
        parts = []
        for para in doc.paragraphs:
            t = (para.text or "").strip()
            if t:
                parts.append(t)
        
        result = "\n".join(parts)
        logger.debug(f"Successfully extracted {len(result)} characters from {Path(path).name}")
        return result
    except FileNotFoundError as e:
        logger.error(f"File not found: {path}: {e}")
        return ""
    except Exception as e:
        logger.error(f"Error extracting text from {path}: {e}", exc_info=True)
        return ""


def check_plagiarism_in_file(
    file_path: str,
    index_dir: str = "",
    topk: int = 10,
    make_report: bool = False,
    use_lsh_filter: bool = True,
    use_fuzzy_match: bool = False,
    use_llm_verify: bool = False,
    parsed_paras: Optional[List] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    try:
        from pathlib import Path
        if not file_path or not isinstance(file_path, str):
            logger.error(f"Invalid file_path: {file_path}")
            return {"success": False, "error": "Invalid file path"}
        
        if not Path(file_path).exists():
            logger.error(f"Plagiarism check: file not found: {file_path}")
            return {"success": False, "error": "File not found"}
        
        # Check disk cache first
        if use_cache:
            file_hash = get_file_hash(file_path)
            cached_result = load_from_cache(file_hash, namespace="plagiarism")
            if cached_result is not None:
                logger.debug(f"Sử dụng plagiarism cache cho {Path(file_path).name}")
                return cached_result
        
        logger.info(f"Starting plagiarism check: {Path(file_path).name}")
        
        # OPTIMIZATION: Use cached paragraphs if provided
        if parsed_paras is not None:
            logger.debug(f"Using cached paragraphs ({len(parsed_paras)} paras) for plagiarism check")
            full_text = "\n".join(p.text for p in parsed_paras if p.text)
        else:
            logger.debug(f"Parsing DOCX for plagiarism check: {file_path}")
            full_text = extract_text_from_docx(file_path)
        
        if not full_text:
            logger.warning(f"No text extracted from {file_path}")
            return {"success": False, "error": "Failed to extract text from file"}

        word_count = len(full_text.split())
        logger.debug(f"Extracted {word_count} words from {file_path}")

        if not PLAGIARISM_API_AVAILABLE:
            logger.warning("PlagiarismSearch API not available")
            result = {
                "success": True,
                "overall_score": 0.0,
                "report": {},
                "total_words": word_count,
                "note": "PlagiarismSearch API not configured (missing API keys in .env)",
            }
            # Cache the "API not available" result for 1 hour
            if use_cache:
                save_to_cache(file_hash, result, namespace="plagiarism", ttl=3600)
            return result

        _require_creds()

        # Upload whole file using Phase 2 optimization (with dynamic chunking)
        logger.debug(f"Submitting file for plagiarism check (timeout=900s)")
        result = check_plagiarism_body_only(
            docx_path=file_path,
            timeout_s=900,
            use_dynamic_chunks=True,
        )
        
        logger.info(f"Plagiarism check completed. Score: {result.get('overall_score', 0)}")

        # Ensure total_words uses full document word count
        result["total_words"] = word_count
        
        # Save to disk cache
        if use_cache and result.get("success"):
            save_to_cache(file_hash, result, namespace="plagiarism", ttl=7*24*3600)  # 7 days
        
        return result

    except Exception as e:
        logger.error(f"Plagiarism check error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
