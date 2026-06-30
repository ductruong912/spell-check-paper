from dataclasses import dataclass

from config import env_float, env_int, env_str


class FieldRelevanceConfigurationError(ValueError):
    pass


class ValidPaperConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class FieldRelevanceConfig:
    vector_store_path: str
    collection_name: str
    semantic_weight: float
    lexical_weight: float
    suitable_threshold: float
    review_threshold: float
    model_name: str
    model_prefix: str


def _validate_field_config(config: FieldRelevanceConfig) -> FieldRelevanceConfig:
    if config.semantic_weight < 0 or config.lexical_weight < 0:
        raise FieldRelevanceConfigurationError("Field relevance weights must not be negative.")
    if config.semantic_weight + config.lexical_weight <= 0:
        raise FieldRelevanceConfigurationError("At least one field relevance weight must be greater than zero.")
    if config.review_threshold > config.suitable_threshold:
        raise FieldRelevanceConfigurationError(
            "FIELD_REVIEW_THRESHOLD must not exceed FIELD_SUITABLE_THRESHOLD."
        )
    return config


def load_field_relevance_config() -> FieldRelevanceConfig:
    config = FieldRelevanceConfig(
        # Danh mục từ khóa lĩnh vực được nạp qua API upload, embed rồi lưu vào
        # vector store (Chroma) tại đường dẫn này — không còn đọc trực tiếp file .txt.
        vector_store_path=env_str("FIELD_VECTOR_STORE_PATH", "data/field_vector_store"),
        collection_name=env_str("FIELD_COLLECTION_NAME", "field_keywords"),
        # Mặc định chỉ dùng semantic per-keyword: với từ vựng lĩnh vực nhỏ (~300 từ),
        # lexical overlap luôn thấp và phạt oan bài đúng ngành. Đặt FIELD_LEXICAL_WEIGHT > 0
        # để bật lại nếu cần (nhớ cộng FIELD_SEMANTIC_WEIGHT lại cho hợp lý).
        semantic_weight=env_float("FIELD_SEMANTIC_WEIGHT", 1.0),
        lexical_weight=env_float("FIELD_LEXICAL_WEIGHT", 0.0),
        # Hiệu chỉnh trên ~370 bài in-field đã đăng (p5≈0.53, off-field max≈0.46):
        # 0.50 giữ ~97% bài thật mà vẫn cao hơn rõ nhóm off-field.
        # Đã thử bge-base/SPECTER/e5: các model "mạnh hơn" đều nén cosine vào dải
        # cao -> tách in-field/off-field KÉM HƠN MiniLM (Cohen's d: MiniLM 3.4 >
        # bge 3.1 > SPECTER 2.8 > e5 2.5). Vì vậy giữ MiniLM. Đổi model thì PHẢI
        # upload lại danh mục và chạy lại matching/scripts/calibrate_field_thresholds.py.
        suitable_threshold=env_float("FIELD_SUITABLE_THRESHOLD", 0.50),
        review_threshold=env_float("FIELD_REVIEW_THRESHOLD", 0.45),
        model_name=env_str(
            "FIELD_MODEL_NAME",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        # Tiền tố bắt buộc của một số model (vd e5 cần "query: "). Để trống với
        # các model thông thường (MiniLM, bge, SPECTER).
        model_prefix=env_str("FIELD_MODEL_PREFIX", ""),
    )
    return _validate_field_config(config)


@dataclass(frozen=True)
class ValidPaperConfig:
    """Cấu hình so khớp title/keywords bản thảo với kho bài báo hợp lệ.

    Điểm mỗi mặt (title, keywords) = semantic_weight * cosine + lexical_weight * BM25
    (BM25 đã normalize 0..1 theo điểm cao nhất của truy vấn), rồi lấy trung bình
    top_k bản ghi điểm cao nhất trong kho.
    """

    vector_store_path: str
    title_collection: str
    keyword_collection: str
    semantic_weight: float
    lexical_weight: float
    top_k: int
    suitable_threshold: float
    model_name: str
    model_prefix: str


def _validate_valid_paper_config(config: ValidPaperConfig) -> ValidPaperConfig:
    if config.semantic_weight < 0 or config.lexical_weight < 0:
        raise ValidPaperConfigurationError("Valid-paper weights must not be negative.")
    if config.semantic_weight + config.lexical_weight <= 0:
        raise ValidPaperConfigurationError("At least one valid-paper weight must be greater than zero.")
    if config.top_k <= 0:
        raise ValidPaperConfigurationError("VALID_TOP_K must be greater than zero.")
    return config


def load_valid_paper_config() -> ValidPaperConfig:
    config = ValidPaperConfig(
        # Kho bài báo hợp lệ được nạp qua API: POST /valid-papers/ingest, embed
        # title và list keywords rồi lưu vào hai collection của vector store này.
        vector_store_path=env_str("VALID_PAPER_STORE_PATH", "data/valid_paper_store"),
        title_collection=env_str("VALID_TITLE_COLLECTION", "valid_titles"),
        keyword_collection=env_str("VALID_KEYWORD_COLLECTION", "valid_keywords"),
        # Theo yêu cầu: 70% semantic (cosine) + 30% khớp từ khóa (BM25).
        semantic_weight=env_float("VALID_SEMANTIC_WEIGHT", 0.7),
        lexical_weight=env_float("VALID_LEXICAL_WEIGHT", 0.3),
        top_k=env_int("VALID_TOP_K", 10),
        suitable_threshold=env_float("VALID_SUITABLE_THRESHOLD", 0.50),
        # Dùng chung model với field relevance để cùng không gian vector; đổi model
        # thì phải nạp lại cả hai kho.
        model_name=env_str(
            "FIELD_MODEL_NAME",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        model_prefix=env_str("FIELD_MODEL_PREFIX", ""),
    )
    return _validate_valid_paper_config(config)
