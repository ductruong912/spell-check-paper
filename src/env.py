"""Shared environment-variable helpers and one-time .env loading.

Both the Streamlit app config (``config``) and the journal-matching config
(``matching.config``) read environment variables through this module so the
project has a single place that loads ``.env`` and a single set of parsing
helpers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load the project .env once, on first import, so every config module sees the
# same values regardless of which entry point (Streamlit app, FastAPI app, or a
# standalone script) imported it first.
load_dotenv(PROJECT_ROOT / ".env")


def env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def env_optional_str(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


__all__ = [
    "PROJECT_ROOT",
    "env_str",
    "env_optional_str",
    "env_int",
    "env_float",
    "env_csv",
]
