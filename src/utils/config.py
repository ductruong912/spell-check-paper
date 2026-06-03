"""Shared configuration and environment setup."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

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


def _env_optional_str(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


logging.basicConfig(
    level=_env_str("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

OPENAI_API_KEY = _env_optional_str("OPENAI_API_KEY")

MAX_WORKERS = _env_int("MAX_WORKERS", 3)

DEFAULT_LLM_MODEL = _env_str("DEFAULT_LLM_MODEL", "gpt-4.1-mini")
DEFAULT_MIN_CONFIDENCE = _env_float("DEFAULT_MIN_CONFIDENCE", 0.70)
