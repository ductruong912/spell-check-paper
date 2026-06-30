"""So title + keywords bản thảo với kho bài báo HỢP LỆ.

Luồng (mỗi mặt title/keywords độc lập):
1. Embed truy vấn thành 1 vector (title 1 vector, list keywords gộp thành 1 vector).
2. Với từng bản ghi trong kho: semantic = cosine(vector truy vấn, vector bản ghi);
   lexical = BM25(truy vấn, text bản ghi) đã normalize 0..1 theo điểm cao nhất.
3. Điểm tổng hợp mỗi bản ghi = 0.7*semantic + 0.3*lexical (theo config).
4. Lấy top_k bản ghi điểm cao nhất rồi tính trung bình -> điểm của mặt đó.
overall_score = trung bình điểm title + điểm keywords (mặt nào có dữ liệu).
"""

from functools import lru_cache

from .bm25 import BM25, bm25_tokens
from .embeddings import EmbeddingProvider, SbertEmbeddingProvider, cosine_similarity
from ..config import ValidPaperConfig
from ..models.matching import ValidPaperMatch, ValidPaperResult, ValidPaperSideResult


def join_keywords(keywords: list[str]) -> str:
    """Gộp list keywords thành một chuỗi (1 vector) để embed và chạy BM25."""
    return ", ".join(keyword.strip() for keyword in keywords if keyword and keyword.strip())


class ValidPaperMatcher:
    def __init__(
        self,
        title_texts: list[str],
        title_embeddings: list[list[float]],
        keyword_texts: list[str],
        keyword_embeddings: list[list[float]],
        embedding_provider: EmbeddingProvider,
        config: ValidPaperConfig,
    ):
        self.config = config
        self.embedding_provider = embedding_provider
        self.title_texts = title_texts
        self.title_embeddings = title_embeddings
        self.keyword_texts = keyword_texts
        self.keyword_embeddings = keyword_embeddings
        # BM25 dựng sẵn theo corpus của kho; truy vấn chỉ chấm điểm, không dựng lại.
        self._title_bm25 = BM25([bm25_tokens(text) for text in title_texts]) if title_texts else None
        self._keyword_bm25 = BM25([bm25_tokens(text) for text in keyword_texts]) if keyword_texts else None

    def match(
        self, title: str | None, keywords: list[str], *, explain: bool
    ) -> ValidPaperResult:
        title_result = None
        if title and title.strip() and self.title_texts:
            title_result = self._side_score(
                title.strip(), self.title_texts, self.title_embeddings, self._title_bm25, explain
            )

        keyword_result = None
        keywords_text = join_keywords(keywords)
        if keywords_text and self.keyword_texts:
            keyword_result = self._side_score(
                keywords_text, self.keyword_texts, self.keyword_embeddings, self._keyword_bm25, explain
            )

        side_scores = [
            result.score for result in (title_result, keyword_result) if result is not None
        ]
        overall = sum(side_scores) / len(side_scores) if side_scores else None
        suitable = overall >= self.config.suitable_threshold if overall is not None else None
        return ValidPaperResult(
            overall_score=overall, suitable=suitable, title=title_result, keywords=keyword_result
        )

    def _side_score(
        self,
        query_text: str,
        doc_texts: list[str],
        doc_embeddings: list[list[float]],
        bm25: BM25 | None,
        explain: bool,
    ) -> ValidPaperSideResult:
        query_embedding = self.embedding_provider.embed_texts([query_text])[0]
        semantic = [
            max(0.0, min(1.0, cosine_similarity(query_embedding, embedding)))
            for embedding in doc_embeddings
        ]

        raw_bm25 = bm25.scores(bm25_tokens(query_text)) if bm25 else [0.0] * len(doc_texts)
        max_bm25 = max(raw_bm25) if raw_bm25 else 0.0
        # Normalize BM25 về 0..1 theo điểm cao nhất của truy vấn để blend 70/30 có nghĩa.
        lexical = [(score / max_bm25 if max_bm25 > 0 else 0.0) for score in raw_bm25]

        combined = [
            self.config.semantic_weight * semantic[index]
            + self.config.lexical_weight * lexical[index]
            for index in range(len(doc_texts))
        ]

        order = sorted(range(len(combined)), key=lambda index: combined[index], reverse=True)
        top = order[: self.config.top_k]
        matches = [
            ValidPaperMatch(
                text=doc_texts[index],
                score=combined[index],
                semantic=semantic[index],
                lexical=lexical[index],
            )
            for index in top
        ]
        average = sum(match.score for match in matches) / len(matches) if matches else 0.0
        return ValidPaperSideResult(score=average, matches=matches if explain else [])


@lru_cache(maxsize=4)
def _build_cached_matcher(config: ValidPaperConfig) -> ValidPaperMatcher | None:
    from ..repositories.valid_paper_store import ValidPaperStore

    store = ValidPaperStore(
        config.vector_store_path, config.title_collection, config.keyword_collection
    )
    title_texts, title_embeddings = store.load_titles()
    keyword_texts, keyword_embeddings = store.load_keywords()
    if not title_texts and not keyword_texts:
        return None

    stored_model = store.stored_model()
    if stored_model and stored_model != config.model_name:
        import logging

        logging.getLogger(__name__).warning(
            "Valid-paper store dựng bằng model '%s' nhưng config dùng '%s'; "
            "nạp lại kho để embed bằng model mới.",
            stored_model,
            config.model_name,
        )
        return None

    provider = SbertEmbeddingProvider(config.model_name, config.model_prefix)
    return ValidPaperMatcher(
        title_texts, title_embeddings, keyword_texts, keyword_embeddings, provider, config
    )


def get_valid_paper_matcher(config: ValidPaperConfig) -> ValidPaperMatcher | None:
    """Tạo matcher (nạp model + đọc kho một lần) và cache theo config."""
    return _build_cached_matcher(config)


def reset_valid_paper_matcher() -> None:
    """Xóa cache matcher để lần gọi sau nạp lại kho vừa cập nhật."""
    _build_cached_matcher.cache_clear()


def ingest_valid_titles(titles: list[str], config: ValidPaperConfig) -> tuple[int, int]:
    from ..repositories.valid_paper_store import ValidPaperStore

    store = ValidPaperStore(
        config.vector_store_path, config.title_collection, config.keyword_collection
    )

    ids: list[str] = []
    title_texts: list[str] = []
    seen: set[str] = set()
    for title in titles:
        title = title.strip()
        if not title:
            continue
        paper_id = ValidPaperStore.title_id(title)
        if paper_id in seen:
            continue
        seen.add(paper_id)
        ids.append(paper_id)
        title_texts.append(title)

    if not ids:
        return 0, store.count_titles()

    provider = SbertEmbeddingProvider(config.model_name, config.model_prefix)
    title_embeddings = provider.embed_texts(title_texts)
    store.add_titles(
        ids=ids,
        texts=title_texts,
        embeddings=title_embeddings,
        model_name=config.model_name,
    )
    reset_valid_paper_matcher()
    return len(ids), store.count_titles()

def ingest_valid_keywords(keywords_list: list[list[str]], config: ValidPaperConfig) -> tuple[int, int]:
    from ..repositories.valid_paper_store import ValidPaperStore

    store = ValidPaperStore(
        config.vector_store_path, config.title_collection, config.keyword_collection
    )

    ids: list[str] = []
    keyword_texts: list[str] = []
    seen: set[str] = set()
    for kw_list in keywords_list:
        keywords_text = join_keywords(kw_list)
        if not keywords_text:
            continue
        paper_id = ValidPaperStore.keyword_id(keywords_text)
        if paper_id in seen:
            continue
        seen.add(paper_id)
        ids.append(paper_id)
        keyword_texts.append(keywords_text)

    if not ids:
        return 0, store.count_keywords()

    provider = SbertEmbeddingProvider(config.model_name, config.model_prefix)
    keyword_embeddings = provider.embed_texts(keyword_texts)
    store.add_keywords(
        ids=ids,
        texts=keyword_texts,
        embeddings=keyword_embeddings,
        model_name=config.model_name,
    )
    reset_valid_paper_matcher()
    return len(ids), store.count_keywords()
