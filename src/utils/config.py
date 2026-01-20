"""Hằng số cấu hình và setup môi trường chung."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# ----------------------------
# Environment
# ----------------------------
root_dir = Path(__file__).parent.parent.parent
load_dotenv(root_dir / ".env", override=True)

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ----------------------------
# API credentials
# ----------------------------
API_USER = os.getenv("PLAGIARISMSEARCH_API_USER")
API_KEY = os.getenv("PLAGIARISMSEARCH_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ----------------------------
# Plagiarism API
# ----------------------------
BASE_URL = "https://plagiarismsearch.com/api/v3"
CREATE_URL = f"{BASE_URL}/reports/create"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_RETRY_DELAY = 2
MAX_RETRIES = 5
REPORT_POLL_INTERVAL = 10

# ----------------------------
# Chunking (plagiarism)
# ----------------------------
DEFAULT_CHUNK_WORDS = 900
DEFAULT_OVERLAP_WORDS = 120
DEFAULT_TOPK = 10

# Dynamic chunking (theo độ dài tài liệu)
DYNAMIC_CHUNK_SMALL_THRESHOLD = 2000
DYNAMIC_CHUNK_SMALL_SIZE = 1000
DYNAMIC_CHUNK_SMALL_OVERLAP = 100

DYNAMIC_CHUNK_MEDIUM_THRESHOLD = 5000
DYNAMIC_CHUNK_MEDIUM_SIZE = 1200
DYNAMIC_CHUNK_MEDIUM_OVERLAP = 110

DYNAMIC_CHUNK_LARGE_THRESHOLD = 20000
DYNAMIC_CHUNK_LARGE_SIZE = 1500
DYNAMIC_CHUNK_LARGE_OVERLAP = 120

DYNAMIC_CHUNK_XLARGE_SIZE = 2000
DYNAMIC_CHUNK_XLARGE_OVERLAP = 150

# ----------------------------
# Plagiarism submission limits
# ----------------------------
MAX_WORDS_PER_SUBMISSION = 5000
MAX_PARALLEL_CHECKS = 2

# ----------------------------
# Plagiarism payload defaults
# ----------------------------
DEFAULT_CREATE_PAYLOAD = {
    "search_web": 1,
    "search_ai": 0,
    "search_storage": 0,
    "neural": 0,
    "filter_references": 1,
    "filter_quotes": 1,
}

# ----------------------------
# UI
# ----------------------------
MAX_WORKERS = 3
PLAGIARISM_TOPK = 10
MAX_PLAGIARISM_FINDINGS_DISPLAY = 20
PLAGIARISM_PREVIEW_LENGTH = 300

HIGHLIGHT_COLOR = "#ffeb3b"          # VN heuristic
HIGHLIGHT_TEXT_COLOR = "#000"
HIGHLIGHT_ERROR_COLOR = "#ff5252"    # EN spelling (Word)
HIGHLIGHT_ERROR_TEXT_COLOR = "#fff"

# ----------------------------
# Structure checking
# ----------------------------
DEFAULT_LLM_MODEL = "gpt-4.1-mini"
DEFAULT_MIN_CONFIDENCE = 0.70

# ----------------------------
# Spell checking
# ----------------------------
REF_TAIL_WINDOW = 0.30
MAX_SUGGESTIONS = 5
MIN_WORD_LENGTH = 3
WORD_CACHE_SIZE = 10000
SPELL_CHECK_BATCH_SIZE = 50

REF_SCORE_THRESHOLD = 4
REF_MIN_RUN_LENGTH = 6

SKIP_TITLECASE_PROPER_NOUNS = True
SKIP_ALL_CAPS_WORDS = True
SKIP_STOPWORDS = True

# ----------------------------
# LLM view sizing
# ----------------------------
LLM_VIEW_MAX_SECTIONS = 40
LLM_VIEW_MAX_SECTION_CHARS = 1800
LLM_VIEW_MAX_FRONT_PARAS = 160
LLM_VIEW_MAX_TAIL_PARAS = 260
