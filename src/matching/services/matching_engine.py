import re

from .embeddings import EmbeddingProvider, cosine_similarity
from ..config import MatchingConfig
from ..models.matching import JournalArticle, MatchingResult, MatchScore


VALID_DECISIONS = {"suitable", "needs_review", "not_suitable"}

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


class MatchingEngine:
    def __init__(
        self,
        articles: list[JournalArticle],
        embedding_provider: EmbeddingProvider,
        config: MatchingConfig,
    ):
        self.articles = articles
        self.embedding_provider = embedding_provider
        self.config = config
        self.documents = [build_document_text(article.title, article.keywords) for article in articles]
        self.document_token_sets = [content_tokens(document) for document in self.documents]
        self.article_embeddings = embedding_provider.embed_texts(self.documents) if self.documents else []

    def match(self, title: str | None, keywords: list[str], *, explain: bool) -> MatchingResult | None:
        query = build_document_text(title, keywords)
        if not query or not self.articles:
            return None

        semantic_scores = self._semantic_scores(query)
        lexical_scores = self._lexical_scores(query)
        match_scores = self._combined_scores(semantic_scores, lexical_scores)
        top_matches = sorted(match_scores, key=lambda item: item.score, reverse=True)[: self.config.top_k]
        if not top_matches:
            return None

        best_match = top_matches[0]
        average_score = sum(item.score for item in top_matches) / len(top_matches)

        return MatchingResult(
            decision=self._decision(best_match.score, average_score),
            score=best_match.score,
            semantic_score=best_match.semantic_score,
            lexical_score=best_match.lexical_score,
            top_matches=top_matches if explain else [],
        )

    def _semantic_scores(self, query: str) -> list[float]:
        query_embedding = self.embedding_provider.embed_texts([query])[0]
        scores: list[float] = []
        for article_embedding in self.article_embeddings:
            cosine = cosine_similarity(query_embedding, article_embedding)
            # Clamp âm về 0 (không liên quan ~ 0 điểm) thay vì map (cos+1)/2 vốn
            # đẩy bài không liên quan lên 0.5. Nhờ vậy ngưỡng 0.7 ~ cosine thật 0.7.
            scores.append(max(0.0, min(1.0, cosine)))
        return scores

    def _lexical_scores(self, query: str) -> list[float]:
        # Tỉ lệ phủ keyword: phần token bản thảo (đã lọc stopword) xuất hiện trong
        # bài / tổng token bản thảo. Tuyệt đối trong [0,1], không phụ thuộc các bài
        # khác nên không trôi khi cập nhật kho định kỳ. Trùng 1/10 từ -> 0.1.
        query_tokens = content_tokens(query)
        if not query_tokens:
            return [0.0 for _ in self.document_token_sets]
        return [
            len(query_tokens & doc_tokens) / len(query_tokens)
            for doc_tokens in self.document_token_sets
        ]

    def _combined_scores(self, semantic_scores: list[float], lexical_scores: list[float]) -> list[MatchScore]:
        scores: list[MatchScore] = []
        for index, article in enumerate(self.articles):
            semantic_score = semantic_scores[index]
            lexical_score = lexical_scores[index]
            score = (
                self.config.semantic_weight * semantic_score
                + self.config.lexical_weight * lexical_score
            )
            scores.append(
                MatchScore(
                    article_id=article.article_id,
                    title=article.title,
                    keywords=article.keywords,
                    score=score,
                    semantic_score=semantic_score,
                    lexical_score=lexical_score,
                )
            )
        return scores

    def _decision(self, best_score: float, average_score: float) -> str:
        if (
            best_score >= self.config.suitable_threshold
            or average_score >= self.config.suitable_average_threshold
        ):
            return "suitable"
        if (
            best_score >= self.config.review_threshold
            or average_score >= self.config.review_average_threshold
        ):
            return "needs_review"
        return "not_suitable"