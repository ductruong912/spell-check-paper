import re
from functools import lru_cache

from .embeddings import EmbeddingProvider, SbertEmbeddingProvider, cosine_similarity
from ..config import FieldRelevanceConfig
from ..models.matching import FieldKeywordMatch, FieldRelevanceResult


# Từ chức năng (function words) EN + VI — bị loại trước khi tính tỉ lệ phủ keyword
# để tránh trùng "oan" trên các từ vô nghĩa như "and", "the", "của", "và".
STOPWORDS = frozenset(
    {
        # English
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
        "from", "has", "have", "in", "into", "is", "it", "its", "of", "on", "or",
        "that", "the", "their", "this", "to", "was", "were", "with", "which",
        "these", "those", "also", "using", "used", "via", "between", "through",
        "toward", "towards", "over", "under", "about",
        # Vietnamese
        "và", "của", "các", "những", "cho", "trong", "là", "một", "với", "để",
        "có", "được", "theo", "khi", "đã", "từ", "về", "ở", "bằng", "hay",
        "hoặc", "như", "này", "đó", "trên", "dưới", "ra", "vào", "người", "thì",
    }
)


def build_document_text(title: str | None, keywords: list[str]) -> str:
    parts: list[str] = []
    if title:
        parts.append(title)
    parts.extend(keyword for keyword in keywords if keyword)
    return " ".join(parts).strip()


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def content_tokens(text: str) -> set[str]:
    """Token đã casefold, bỏ stopword — dùng cho tỉ lệ phủ keyword."""
    return {token for token in tokenize(text) if token not in STOPWORDS}


class FieldRelevanceChecker:
    """So title + keywords bản thảo với danh mục từ khóa chuẩn của lĩnh vực.

    Điểm phù hợp = semantic_weight * semantic_score + lexical_weight * lexical_score:
    - semantic_score: với mỗi "term" của bài (title + từng keyword), tìm từ khóa
      lĩnh vực gần nghĩa nhất (cosine cao nhất), rồi lấy trung bình các điểm đó.
      So term-với-keyword (cùng độ dài) cho điểm trực quan hơn so cả cục văn bản.
    - lexical_score: tỉ lệ token nội dung của bản thảo nằm trong từ vựng lĩnh vực.
    """

    def __init__(
        self,
        keywords: list[str],
        keyword_embeddings: list[list[float]],
        embedding_provider: EmbeddingProvider,
        config: FieldRelevanceConfig,
    ):
        self.keywords = keywords
        self.embedding_provider = embedding_provider
        self.config = config
        # Vector từ khóa lĩnh vực được embed + normalize sẵn và lưu trong vector
        # store; checker chỉ nạp lại, không embed mỗi lần khởi tạo.
        self.keyword_embeddings = keyword_embeddings
        # Từ vựng lĩnh vực (đã casefold, bỏ stopword) dùng cho điểm lexical.
        self.field_tokens: set[str] = set()
        for keyword in keywords:
            self.field_tokens |= content_tokens(keyword)

    def check(self, title: str | None, keywords: list[str], *, explain: bool) -> FieldRelevanceResult | None:
        terms: list[str] = []
        if title:
            terms.append(title)
        terms.extend(keyword for keyword in keywords if keyword)
        if not terms or not self.keywords:
            return None

        matches = self._best_matches(terms)
        semantic_score = sum(match.score for match in matches) / len(matches)
        lexical_score = self._lexical_score(build_document_text(title, keywords))
        score = (
            self.config.semantic_weight * semantic_score
            + self.config.lexical_weight * lexical_score
        )

        ranked = sorted(matches, key=lambda match: match.score, reverse=True)
        return FieldRelevanceResult(
            decision=self._decision(score),
            score=score,
            semantic_score=semantic_score,
            lexical_score=lexical_score,
            matched_keywords=ranked if explain else [],
        )

    def _best_matches(self, terms: list[str]) -> list[FieldKeywordMatch]:
        """Với mỗi term, trả từ khóa lĩnh vực có cosine cao nhất."""
        term_embeddings = self.embedding_provider.embed_texts(terms)
        matches: list[FieldKeywordMatch] = []
        for term, term_embedding in zip(terms, term_embeddings):
            best_index = 0
            best_cosine = -1.0
            for index, keyword_embedding in enumerate(self.keyword_embeddings):
                cosine = cosine_similarity(term_embedding, keyword_embedding)
                if cosine > best_cosine:
                    best_cosine = cosine
                    best_index = index
            matches.append(
                FieldKeywordMatch(
                    term=term,
                    keyword=self.keywords[best_index],
                    score=max(0.0, min(1.0, best_cosine)),
                )
            )
        return matches

    def _lexical_score(self, query: str) -> float:
        query_tokens = content_tokens(query)
        if not query_tokens or not self.field_tokens:
            return 0.0
        return len(query_tokens & self.field_tokens) / len(query_tokens)

    def _decision(self, score: float) -> str:
        if score >= self.config.suitable_threshold:
            return "suitable"
        if score >= self.config.review_threshold:
            return "needs_review"
        return "not_suitable"


@lru_cache(maxsize=4)
def _build_cached_checker(config: FieldRelevanceConfig) -> FieldRelevanceChecker | None:
    from ..repositories.field_vector_store import FieldVectorStore

    store = FieldVectorStore(config.vector_store_path, config.collection_name)
    keywords, keyword_embeddings = store.load_all()
    if not keywords:
        return None
    stored_model = store.stored_model()
    if stored_model != config.model_name:
        import logging

        logging.getLogger(__name__).warning(
            "Vector store dựng bằng model '%s' nhưng config dùng '%s'; "
            "upload lại danh mục để embed bằng model mới.",
            stored_model or "(không rõ)",
            config.model_name,
        )
        return None
    provider = SbertEmbeddingProvider(config.model_name, config.model_prefix)
    return FieldRelevanceChecker(keywords, keyword_embeddings, provider, config)


def get_field_relevance_checker(config: FieldRelevanceConfig) -> FieldRelevanceChecker | None:
    """Tạo checker (nạp model + đọc vector store một lần) và cache theo config.

    Nạp model embedding và đọc danh mục vector là việc nặng; cache theo config
    (frozen dataclass hashable) để mỗi request không phải nạp lại từ đầu. Gọi
    reset_field_relevance_checker() sau khi upload danh mục mới để làm mới cache.
    """
    return _build_cached_checker(config)


def reset_field_relevance_checker() -> None:
    """Xóa cache checker để lần gọi sau nạp lại vector store vừa cập nhật."""
    _build_cached_checker.cache_clear()


def ingest_field_keywords(text: str, config: FieldRelevanceConfig) -> tuple[int, int]:
    """Parse danh mục từ text, embed + normalize, lưu (append) vào vector store.

    Trả về (số_từ_khóa_trong_file, tổng_từ_khóa_trong_store_sau_khi_lưu).
    """
    from ..repositories.field_keywords import parse_field_keywords
    from ..repositories.field_vector_store import FieldVectorStore

    keywords = parse_field_keywords(text)
    if not keywords:
        store = FieldVectorStore(config.vector_store_path, config.collection_name)
        return 0, store.count()

    provider = SbertEmbeddingProvider(config.model_name, config.model_prefix)
    embeddings = provider.embed_texts(keywords)
    store = FieldVectorStore(config.vector_store_path, config.collection_name)
    store.add_keywords(keywords, embeddings, config.model_name)
    reset_field_relevance_checker()
    return len(keywords), store.count()
