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


def env_str_raw(name: str, default: str = "") -> str:
    """Đọc biến môi trường, chỉ strip newline (\\r\\n) — giữ trailing space.
    Dùng cho prefix có trailing space như 'query: ' của e5 model."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.rstrip("\r\n")


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


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("true", "1", "t", "y", "yes")


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


class ValidPaperConfigurationError(ValueError):
    pass


class ReviewerConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidPaperConfig:
    """Configuration for matching manuscript title/keywords against accepted papers."""

    vector_store_path: str
    title_collection: str
    keyword_collection: str
    title_semantic_weight: float
    title_lexical_weight: float
    keyword_semantic_weight: float
    keyword_lexical_weight: float
    title_score_weight: float
    keyword_score_weight: float
    top_k: int
    eval_top_n: int
    retrieval_score_weight: float
    reranker_score_weight: float
    suitable_threshold: float
    model_name: str
    reranker_model_name: str


@dataclass(frozen=True)
class ReviewerConfig:
    """Configuration for reviewer recommendation from reviewer title history."""

    store_path: str
    collection: str
    top_matches: int
    model_name: str
    reranker_model_name: str
    rerank_candidates: int
    retrieval_score_weight: float
    reranker_score_weight: float


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
    )


def _validate_valid_paper_config(config: ValidPaperConfig) -> ValidPaperConfig:
    if config.title_semantic_weight < 0 or config.title_lexical_weight < 0:
        raise ValidPaperConfigurationError("Valid-paper title weights must not be negative.")
    if config.keyword_semantic_weight < 0 or config.keyword_lexical_weight < 0:
        raise ValidPaperConfigurationError("Valid-paper keyword weights must not be negative.")
    if config.title_score_weight < 0 or config.keyword_score_weight < 0:
        raise ValidPaperConfigurationError("Valid-paper side score weights must not be negative.")
    if config.title_semantic_weight + config.title_lexical_weight <= 0:
        raise ValidPaperConfigurationError(
            "At least one valid-paper title weight must be greater than zero."
        )
    if config.keyword_semantic_weight + config.keyword_lexical_weight <= 0:
        raise ValidPaperConfigurationError(
            "At least one valid-paper keyword weight must be greater than zero."
        )
    if config.title_score_weight + config.keyword_score_weight <= 0:
        raise ValidPaperConfigurationError(
            "At least one valid-paper side score weight must be greater than zero."
        )
    if config.retrieval_score_weight < 0 or config.reranker_score_weight < 0:
        raise ValidPaperConfigurationError("Valid-paper retrieval/reranker weights must not be negative.")
    if config.retrieval_score_weight + config.reranker_score_weight <= 0:
        raise ValidPaperConfigurationError(
            "At least one valid-paper retrieval/reranker weight must be greater than zero."
        )
    if config.top_k <= 0:
        raise ValidPaperConfigurationError("VALID_TOP_K must be greater than zero.")
    return config


def _validate_reviewer_config(config: ReviewerConfig) -> ReviewerConfig:
    if config.top_matches <= 0:
        raise ReviewerConfigurationError("REVIEWER_TOP_MATCHES must be greater than zero.")
    if config.rerank_candidates <= 0:
        raise ReviewerConfigurationError(
            "REVIEWER_RERANK_CANDIDATES must be greater than zero."
        )
    if config.retrieval_score_weight < 0 or config.reranker_score_weight < 0:
        raise ReviewerConfigurationError("Reviewer retrieval/reranker weights must not be negative.")
    if config.retrieval_score_weight + config.reranker_score_weight <= 0:
        raise ReviewerConfigurationError(
            "At least one reviewer retrieval/reranker weight must be greater than zero."
        )
    return config


def load_valid_paper_config() -> ValidPaperConfig:
    config = ValidPaperConfig(
        vector_store_path=env_str("VALID_PAPER_STORE_PATH", "data_valid_paper_store"),
        title_collection=env_str("VALID_TITLE_COLLECTION", "valid_titles"),
        keyword_collection=env_str("VALID_KEYWORD_COLLECTION", "valid_keywords"),
        title_semantic_weight=env_float("VALID_TITLE_SEMANTIC_WEIGHT", 0.7),
        title_lexical_weight=env_float("VALID_TITLE_LEXICAL_WEIGHT", 0.3),
        keyword_semantic_weight=env_float("VALID_KEYWORD_SEMANTIC_WEIGHT", 0.7),
        keyword_lexical_weight=env_float("VALID_KEYWORD_LEXICAL_WEIGHT", 0.3),
        title_score_weight=env_float("VALID_TITLE_SCORE_WEIGHT", 0.5),
        keyword_score_weight=env_float("VALID_KEYWORD_SCORE_WEIGHT", 0.5),
        top_k=env_int("VALID_TOP_K", 10),
        eval_top_n=env_int("VALID_EVAL_TOP_N", 3),
        retrieval_score_weight=env_float("VALID_RETRIEVAL_SCORE_WEIGHT", 0.4),
        reranker_score_weight=env_float("VALID_RERANKER_SCORE_WEIGHT", 0.6),
        suitable_threshold=env_float("VALID_SUITABLE_THRESHOLD", 0.50),
        model_name=env_str(
            "VALID_MODEL_NAME",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        reranker_model_name=env_str(
            "VALID_RERANKER_MODEL_NAME",
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
        ),
    )
    return _validate_valid_paper_config(config)


def load_reviewer_config() -> ReviewerConfig:
    config = ReviewerConfig(
        store_path=env_str("REVIEWER_STORE_PATH", "data_reviewer_store"),
        collection=env_str("REVIEWER_COLLECTION", "reviewer_profiles"),
        top_matches=env_int("REVIEWER_TOP_MATCHES", 3),
        model_name=env_str(
            "REVIEWER_MODEL_NAME",
            env_str(
                "VALID_MODEL_NAME",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
        ),
        reranker_model_name=env_str(
            "REVIEWER_RERANKER_MODEL_NAME",
            env_str(
                "VALID_RERANKER_MODEL_NAME",
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
            ),
        ),
        rerank_candidates=env_int("REVIEWER_RERANK_CANDIDATES", 10),
        retrieval_score_weight=env_float("REVIEWER_RETRIEVAL_SCORE_WEIGHT", 0.4),
        reranker_score_weight=env_float("REVIEWER_RERANKER_SCORE_WEIGHT", 0.6),
    )
    return _validate_reviewer_config(config)


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
