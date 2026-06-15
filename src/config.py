"""Centralized runtime configuration for the structure-review app."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from env import PROJECT_ROOT
from env import env_csv as _env_csv
from env import env_float as _env_float
from env import env_int as _env_int
from env import env_optional_str as _env_optional_str
from env import env_str as _env_str


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


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load application settings from environment and an optional dotenv file."""
    dotenv_path = Path(env_file) if env_file is not None else PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path, override=True)

    return Settings(
        project_root=PROJECT_ROOT,
        app_title=_env_str("APP_TITLE", "TNT Check AI"),
        brand_label=_env_str("BRAND_LABEL", "TNT Paper Review"),
        supported_extensions=_env_csv("SUPPORTED_EXTENSIONS", ("docx", "pdf")),
        openai_api_key=_env_optional_str("OPENAI_API_KEY"),
        default_llm_model=_env_str("DEFAULT_LLM_MODEL", "gpt-4.1-mini"),
        default_min_confidence=_env_float("DEFAULT_MIN_CONFIDENCE", 0.70),
        openai_max_tokens=_env_int("OPENAI_MAX_TOKENS", 3000),
        openai_temperature=_env_float("OPENAI_TEMPERATURE", 0.0),
        structure_timeout_seconds=_env_int("STRUCTURE_TIMEOUT_SECONDS", 120),
        max_workers=_env_int("MAX_WORKERS", 3),
        libreoffice_path=_env_optional_str("LIBREOFFICE_PATH"),
        docx_preview_timeout_seconds=_env_int("DOCX_PREVIEW_TIMEOUT_SECONDS", 60),
        pdf_preview_scale=_env_float("PDF_PREVIEW_SCALE", 2.5),
        temp_cleanup_ttl_seconds=_env_int("TEMP_CLEANUP_TTL_SECONDS", 7200),
        structure_template_path=_env_optional_str("STRUCTURE_TEMPLATE_PATH"),
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
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

__all__ = [
    "Settings",
    "settings",
    "load_settings",
    "APP_TITLE",
    "BRAND_LABEL",
    "SUPPORTED_EXTENSIONS",
    "OPENAI_API_KEY",
    "LIBREOFFICE_PATH",
    "STRUCTURE_TEMPLATE_PATH",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_MIN_CONFIDENCE",
    "OPENAI_MAX_TOKENS",
    "OPENAI_TEMPERATURE",
    "MAX_WORKERS",
    "STRUCTURE_TIMEOUT_SECONDS",
    "DOCX_PREVIEW_TIMEOUT_SECONDS",
    "PDF_PREVIEW_SCALE",
    "TEMP_CLEANUP_TTL_SECONDS",
]
