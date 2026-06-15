from dataclasses import dataclass

from env import env_float, env_int, env_str


@dataclass(frozen=True)
class MatchingConfig:
    top_k: int
    semantic_weight: float
    lexical_weight: float
    suitable_threshold: float
    review_threshold: float
    suitable_average_threshold: float
    review_average_threshold: float
    refresh_interval_days: int
    model_name: str
    index_dir: str


class MatchingConfigurationError(ValueError):
    pass


def _validate_config(config: MatchingConfig) -> MatchingConfig:
    if config.top_k <= 0:
        raise MatchingConfigurationError("MATCH_TOP_K must be greater than zero.")
    if config.refresh_interval_days <= 0:
        raise MatchingConfigurationError("MATCH_REFRESH_INTERVAL_DAYS must be greater than zero.")
    if config.semantic_weight < 0 or config.lexical_weight < 0:
        raise MatchingConfigurationError("Matching weights must not be negative.")
    if config.semantic_weight + config.lexical_weight <= 0:
        raise MatchingConfigurationError("At least one matching weight must be greater than zero.")
    return config


def load_matching_config() -> MatchingConfig:
    config = MatchingConfig(
        top_k=env_int("MATCH_TOP_K", 5),
        semantic_weight=env_float("MATCH_SEMANTIC_WEIGHT", 0.8),
        lexical_weight=env_float("MATCH_LEXICAL_WEIGHT", 0.2),
        suitable_threshold=env_float("MATCH_SUITABLE_THRESHOLD", 0.7),
        review_threshold=env_float("MATCH_REVIEW_THRESHOLD", 0.55),
        suitable_average_threshold=env_float("MATCH_SUITABLE_AVERAGE_THRESHOLD", 0.62),
        review_average_threshold=env_float("MATCH_REVIEW_AVERAGE_THRESHOLD", 0.48),
        refresh_interval_days=env_int("MATCH_REFRESH_INTERVAL_DAYS", 90),
        model_name=env_str(
            "MATCH_MODEL_NAME",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        index_dir=env_str("MATCH_INDEX_DIR", "data/index"),
    )
    return _validate_config(config)
