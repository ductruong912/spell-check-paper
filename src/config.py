"""Centralized runtime configuration and environment helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


@dataclass(frozen=True)
class Settings:
    project_root: Path
    app_title: str
    brand_label: str
    supported_extensions: tuple[str, ...]
    openai_api_key: Optional[str]
    default_llm_model: str
    default_min_confidence: float
    openai_max_tokens: int
    openai_temperature: float
    structure_timeout_seconds: int
    max_workers: int
    libreoffice_path: Optional[str]
    docx_preview_timeout_seconds: int
    pdf_preview_scale: float
    temp_cleanup_ttl_seconds: int
    structure_template_path: Optional[str]
    log_level: str
    api_base_url: str


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load application settings from environment and an optional dotenv file."""
    dotenv_path = Path(env_file) if env_file is not None else PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path, override=True)

    return Settings(
        project_root=PROJECT_ROOT,
        app_title=env_str("APP_TITLE", "TNT Check AI"),
        brand_label=env_str("BRAND_LABEL", "TNT Paper Review"),
        supported_extensions=env_csv("SUPPORTED_EXTENSIONS", ("docx", "pdf")),
        openai_api_key=env_optional_str("OPENAI_API_KEY"),
        default_llm_model=env_str("DEFAULT_LLM_MODEL", "gpt-4.1-mini"),
        default_min_confidence=env_float("DEFAULT_MIN_CONFIDENCE", 0.70),
        openai_max_tokens=env_int("OPENAI_MAX_TOKENS", 3000),
        openai_temperature=env_float("OPENAI_TEMPERATURE", 0.0),
        structure_timeout_seconds=env_int("STRUCTURE_TIMEOUT_SECONDS", 120),
        max_workers=env_int("MAX_WORKERS", 3),
        libreoffice_path=env_optional_str("LIBREOFFICE_PATH"),
        docx_preview_timeout_seconds=env_int("DOCX_PREVIEW_TIMEOUT_SECONDS", 60),
        pdf_preview_scale=env_float("PDF_PREVIEW_SCALE", 2.5),
        temp_cleanup_ttl_seconds=env_int("TEMP_CLEANUP_TTL_SECONDS", 7200),
        structure_template_path=env_optional_str("STRUCTURE_TEMPLATE_PATH"),
        log_level=env_str("LOG_LEVEL", "INFO").upper(),
        api_base_url=env_str("API_BASE_URL", "http://0.0.0.0:8501"),
    )


settings = load_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

APP_TITLE = settings.app_title
BRAND_LABEL = settings.brand_label
SUPPORTED_EXTENSIONS = settings.supported_extensions

OPENAI_API_KEY = settings.openai_api_key
LIBREOFFICE_PATH = settings.libreoffice_path
STRUCTURE_TEMPLATE_PATH = settings.structure_template_path

DEFAULT_LLM_MODEL = settings.default_llm_model
DEFAULT_MIN_CONFIDENCE = settings.default_min_confidence
OPENAI_MAX_TOKENS = settings.openai_max_tokens
OPENAI_TEMPERATURE = settings.openai_temperature

MAX_WORKERS = settings.max_workers
STRUCTURE_TIMEOUT_SECONDS = settings.structure_timeout_seconds
DOCX_PREVIEW_TIMEOUT_SECONDS = settings.docx_preview_timeout_seconds
PDF_PREVIEW_SCALE = settings.pdf_preview_scale
TEMP_CLEANUP_TTL_SECONDS = settings.temp_cleanup_ttl_seconds
