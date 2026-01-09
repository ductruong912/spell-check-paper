"""Configuration constants and environment setup."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
root_dir = Path(__file__).parent.parent.parent
load_dotenv(root_dir / ".env", override=True)

# Logging configuration
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# API Credentials
API_USER = os.getenv("PLAGIARISMSEARCH_API_USER")
API_KEY = os.getenv("PLAGIARISMSEARCH_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Plagiarism API
BASE_URL = "https://plagiarismsearch.com/api/v3"
CREATE_URL = f"{BASE_URL}/reports/create"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_RETRY_DELAY = 2
MAX_RETRIES = 5
REPORT_POLL_INTERVAL = 2

# Chunking configuration
DEFAULT_CHUNK_WORDS = 900
DEFAULT_OVERLAP_WORDS = 120
DEFAULT_TOPK = 10

# Dynamic chunking thresholds (Phase 2 optimization)
DYNAMIC_CHUNK_SMALL_THRESHOLD = 2000      # Words
DYNAMIC_CHUNK_SMALL_SIZE = 1000           # Use 1000-word chunks for small docs
DYNAMIC_CHUNK_SMALL_OVERLAP = 100         # Reduced overlap

DYNAMIC_CHUNK_MEDIUM_THRESHOLD = 5000     # Words
DYNAMIC_CHUNK_MEDIUM_SIZE = 1200          # Use 1200-word chunks for medium docs
DYNAMIC_CHUNK_MEDIUM_OVERLAP = 110

DYNAMIC_CHUNK_LARGE_THRESHOLD = 20000     # Words
DYNAMIC_CHUNK_LARGE_SIZE = 1500           # Use 1500-word chunks for large docs
DYNAMIC_CHUNK_LARGE_OVERLAP = 120

DYNAMIC_CHUNK_XLARGE_SIZE = 2000          # Use 2000-word chunks for XL docs
DYNAMIC_CHUNK_XLARGE_OVERLAP = 150

# API submission limits
MAX_WORDS_PER_SUBMISSION = 5000           # PlagiarismSearch API limit
MAX_PARALLEL_CHECKS = 3                   # Max concurrent plagiarism checks

# Plagiarism API payload defaults
DEFAULT_CREATE_PAYLOAD = {
    "search_web": 1,
    "search_ai": 0,
    "search_storage": 0,
    "neural": 0,
    "filter_references": 1,
    "filter_quotes": 1,
}

# UI Constants
MAX_WORKERS = 3
PLAGIARISM_TOPK = 10
MAX_PLAGIARISM_FINDINGS_DISPLAY = 20
PLAGIARISM_PREVIEW_LENGTH = 300
HIGHLIGHT_COLOR = "#ffeb3b"  # Yellow for Vietnamese heuristic issues
HIGHLIGHT_TEXT_COLOR = "#000"
HIGHLIGHT_ERROR_COLOR = "#ff5252"  # Red for English spelling errors from Word COM
HIGHLIGHT_ERROR_TEXT_COLOR = "#fff"

# Structure checking
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_MIN_CONFIDENCE = 0.70

# Spell checking
REF_TAIL_WINDOW = 0.30                    # 30% of document for reference detection
MAX_SUGGESTIONS = 5                        # Maximum spelling suggestions per word
MIN_WORD_LENGTH = 3                        # Minimum word length for spell check
WORD_CACHE_SIZE = 10000                    # Word cache size
SPELL_CHECK_BATCH_SIZE = 50                # Batch size for spell checking
REF_SCORE_THRESHOLD = 4                    # Reference detection score threshold
REF_MIN_RUN_LENGTH = 6                     # Minimum run length for references
SKIP_TITLECASE_PROPER_NOUNS = True         # Skip titlecase proper nouns
SKIP_ALL_CAPS_WORDS = True                 # Skip all caps words
SKIP_STOPWORDS = True                      # Skip stopwords
