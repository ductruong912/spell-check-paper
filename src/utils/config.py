"""Hằng số cấu hình và setup môi trường chung."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ----------------------------
# .env file
# ----------------------------
root_dir = Path(__file__).parent.parent.parent
load_dotenv(root_dir / ".env", override=True)


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_optional_str(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=_env_str("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ----------------------------
# API credentials
# ----------------------------
API_USER = _env_optional_str("TURNITIN_API_KEY")
API_KEY = _env_optional_str("TURNITIN_API_SECRET")
OPENAI_API_KEY = _env_optional_str("OPENAI_API_KEY")

# ----------------------------
# Plagiarism API (Turnitin / iThenticate)
# ----------------------------
BASE_URL = _env_str("TURNITIN_BASE_URL", "https://api.turnitin.com/api/v1").rstrip("/")
CREATE_URL = f"{BASE_URL}/submissions"
DEFAULT_TIMEOUT_SECONDS = _env_int("TURNITIN_DEFAULT_TIMEOUT_SECONDS", 900)
DEFAULT_RETRY_DELAY = _env_int("DEFAULT_RETRY_DELAY", 2)
MAX_RETRIES = _env_int("MAX_RETRIES", 5)
REPORT_POLL_INTERVAL = _env_int("TURNITIN_REPORT_POLL_INTERVAL", 10)

# ----------------------------
# Plagiarism submission limits
# ----------------------------
MAX_WORDS_PER_SUBMISSION = _env_int("MAX_WORDS_PER_SUBMISSION", 100000)  # Turnitin supports up to ~100k words
MAX_PARALLEL_CHECKS = _env_int("MAX_PARALLEL_CHECKS", 2)

# ----------------------------
# Plagiarism payload defaults (Turnitin mock)
# ----------------------------
DEFAULT_CREATE_PAYLOAD = {
    "search_internet": _env_bool("TURNITIN_SEARCH_INTERNET", True),
    "search_publications": _env_bool("TURNITIN_SEARCH_PUBLICATIONS", True),
    "exclude_quotes": _env_bool("TURNITIN_EXCLUDE_QUOTES", True),
    "exclude_bibliography": _env_bool("TURNITIN_EXCLUDE_BIBLIOGRAPHY", True),
}

# ----------------------------
# UI
# ----------------------------
MAX_WORKERS = _env_int("MAX_WORKERS", 3)
PLAGIARISM_TOPK = _env_int("PLAGIARISM_TOPK", 10)
MAX_PLAGIARISM_FINDINGS_DISPLAY = _env_int("MAX_PLAGIARISM_FINDINGS_DISPLAY", 20)
PLAGIARISM_PREVIEW_LENGTH = _env_int("PLAGIARISM_PREVIEW_LENGTH", 300)

HIGHLIGHT_COLOR = _env_str("HIGHLIGHT_COLOR", "#ffeb3b")          # Vietnamese spelling
HIGHLIGHT_TEXT_COLOR = _env_str("HIGHLIGHT_TEXT_COLOR", "#000")
HIGHLIGHT_ERROR_COLOR = _env_str("HIGHLIGHT_ERROR_COLOR", "#ff5252")    # EN spelling
HIGHLIGHT_ERROR_TEXT_COLOR = _env_str("HIGHLIGHT_ERROR_TEXT_COLOR", "#fff")

# ----------------------------
# Structure checking
# ----------------------------
DEFAULT_LLM_MODEL = _env_str("DEFAULT_LLM_MODEL", "gpt-4.1-mini")
DEFAULT_MIN_CONFIDENCE = _env_float("DEFAULT_MIN_CONFIDENCE", 0.70)

# ----------------------------
# Spell checking
# ----------------------------
REF_TAIL_WINDOW = _env_float("REF_TAIL_WINDOW", 0.30)
MAX_SUGGESTIONS = _env_int("MAX_SUGGESTIONS", 5)
WORD_CACHE_SIZE = _env_int("WORD_CACHE_SIZE", 10000)
SPELL_CHECK_BATCH_SIZE = _env_int("SPELL_CHECK_BATCH_SIZE", 50)
