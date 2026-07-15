from __future__ import annotations

import re
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from config import ReviewerConfig
from domain_ids import get_domain_store_path, normalize_domain_id, swap_store_directories
from documents import normalize_whitespace
from matching.services.embeddings import (
    CrossEncoderProvider,
    SbertEmbeddingProvider,
    SparseEmbeddingProvider,
    cosine_similarity,
    get_cross_encoder_provider,
)
from matching.services.preprocessing import normalize_title
from reviewers.models import ReviewerProfile, ReviewerSuggestion, ReviewerTitlePoint
from reviewers.repositories.reviewer_store import ReviewerStore


_TITLE_SPLIT_RE = re.compile(r"[,;]")
_AUTHORED_SOURCE = "authored"
_REVIEWED_SOURCE = "reviewed"
_SEMANTIC_WEIGHT = 0.7
_LEXICAL_WEIGHT = 0.3


def parse_reviewer_titles(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        raw_items: Iterable[Any] = _TITLE_SPLIT_RE.split(value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]

    titles: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        title = _clean_reviewer_title(str(item))
        if not title:
            continue
        key = normalize_title(title)
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def _clean_reviewer_title(title: str) -> str:
    return normalize_whitespace(title).strip()


@dataclass(frozen=True)
class _TitleScore:
    title: str
    retrieval_score: float
    score: float


def _fuse_retrieval_and_reranker(
    retrieval_score: float,
    reranker_score: float,
    retrieval_weight: float,
    reranker_weight: float,
) -> float:
    total_weight = retrieval_weight + reranker_weight
    if total_weight <= 0:
        return 0.0
    return (
        retrieval_score * retrieval_weight + reranker_score * reranker_weight
    ) / total_weight


def _sparse_items(sparse_vector: Any | None) -> tuple[list[int], list[float]]:
    if sparse_vector is None:
        return [], []
    indices = getattr(sparse_vector, "indices", [])
    values = getattr(sparse_vector, "values", [])
    if not isinstance(indices, list) and hasattr(indices, "tolist"):
        indices = indices.tolist()
    if not isinstance(values, list) and hasattr(values, "tolist"):
        values = values.tolist()
    return list(indices or []), [float(value) for value in (values or [])]


def _lexical_similarity(query_sparse: Any | None, doc_sparse: Any | None) -> float:
    query_indices, query_values = _sparse_items(query_sparse)
    doc_indices, doc_values = _sparse_items(doc_sparse)
    ideal = sum(value * value for value in query_values)
    if ideal <= 0:
        return 0.0

    query_by_index = dict(zip(query_indices, query_values))
    dot = 0.0
    for index, value in zip(doc_indices, doc_values):
        if index in query_by_index:
            dot += query_by_index[index] * value
    return max(0.0, min(1.0, dot / ideal))


class ReviewerMatcher:
    def __init__(
        self,
        *,
        store,
        embedding_provider,
        sparse_provider,
        reranker_provider: CrossEncoderProvider | None = None,
        config: ReviewerConfig,
    ):
        self.store = store
        self.embedding_provider = embedding_provider
        self.sparse_provider = sparse_provider
        self.reranker_provider = reranker_provider
        self.config = config

    def ingest(self, profiles: list[ReviewerProfile], *, store=None) -> tuple[int, int]:
        title_points: list[ReviewerTitlePoint] = []
        for profile in profiles:
            articles = parse_reviewer_titles(profile.articles)
            reviewed_articles = parse_reviewer_titles(profile.reviewed_articles)
            if not articles and not reviewed_articles:
                continue

            for title in articles:
                title_points.append(
                    ReviewerTitlePoint(
                        user_id=profile.user_id,
                        user=profile.user,
                        source=_AUTHORED_SOURCE,
                        title=title,
                        articles=articles,
                        reviewed_articles=reviewed_articles,
                    )
                )
            for title in reviewed_articles:
                title_points.append(
                    ReviewerTitlePoint(
                        user_id=profile.user_id,
                        user=profile.user,
                        source=_REVIEWED_SOURCE,
                        title=title,
                        articles=articles,
                        reviewed_articles=reviewed_articles,
                    )
                )

        texts = [point.title for point in title_points]
        dense_embeddings = self.embedding_provider.embed_passages(texts) if texts else []
        sparse_embeddings = self.sparse_provider.embed_texts(texts) if texts else []
        target_store = store or self.store
        target_store.replace_title_points(title_points, dense_embeddings, sparse_embeddings)
        return target_store.count_users(), len(title_points)

    def suggest(
        self,
        title: str,
        *,
        explain: bool = False,
    ) -> list[ReviewerSuggestion]:
        query_text = _clean_reviewer_title(title)
        if not query_text:
            return []

        query_dense = self.embedding_provider.embed_query([query_text])[0]
        query_sparse = self.sparse_provider.embed_texts([query_text])[0]

        user_info: dict[int, tuple[str, list[str], list[str]]] = {}
        authored_scores: dict[int, list[_TitleScore]] = defaultdict(list)
        reviewed_scores: dict[int, list[_TitleScore]] = defaultdict(list)

        for point in self.store.list_title_points():
            user_info[point.user_id] = (point.user, point.articles, point.reviewed_articles)
            semantic = max(0.0, min(1.0, cosine_similarity(query_dense, point.dense_vector)))
            lexical = _lexical_similarity(query_sparse, point.sparse_vector)
            score = _SEMANTIC_WEIGHT * semantic + _LEXICAL_WEIGHT * lexical
            title_score = _TitleScore(point.title, score, score)

            if point.source == _AUTHORED_SOURCE:
                authored_scores[point.user_id].append(title_score)
            elif point.source == _REVIEWED_SOURCE:
                reviewed_scores[point.user_id].append(title_score)

        suggestions: list[ReviewerSuggestion] = []
        top_authored_by_user = _select_top_scores_by_user(
            query_text,
            authored_scores,
            self.config.top_matches,
            self.config.rerank_candidates,
            self.reranker_provider,
            self.config.retrieval_score_weight,
            self.config.reranker_score_weight,
        )
        top_reviewed_by_user = _select_top_scores_by_user(
            query_text,
            reviewed_scores,
            self.config.top_matches,
            self.config.rerank_candidates,
            self.reranker_provider,
            self.config.retrieval_score_weight,
            self.config.reranker_score_weight,
        )

        for user_id, (user, _articles, _reviewed_articles) in user_info.items():
            top_authored = top_authored_by_user.get(user_id, [])
            top_reviewed = top_reviewed_by_user.get(user_id, [])
            authored_score = _average_score(top_authored)
            reviewed_score = _average_score(top_reviewed)
            score = _select_reviewer_score(authored_score, reviewed_score)

            suggestion = ReviewerSuggestion(
                user_id=user_id,
                user=user,
                score=score,
                authored_score=authored_score,
                reviewed_score=reviewed_score,
                matched_articles=[item.title for item in top_authored] if explain else [],
                matched_reviewed_articles=[item.title for item in top_reviewed] if explain else [],
            )
            suggestions.append(suggestion)

        suggestions.sort(key=lambda item: (-item.score, item.user_id))
        return suggestions


def _top_scores(scores: list[_TitleScore], limit: int) -> list[_TitleScore]:
    if limit <= 0:
        return []
    return sorted(scores, key=lambda item: item.score, reverse=True)[:limit]


def _select_top_scores_by_user(
    query_text: str,
    scores_by_user: dict[int, list[_TitleScore]],
    top_matches: int,
    rerank_candidates: int,
    reranker_provider: CrossEncoderProvider | None,
    retrieval_score_weight: float,
    reranker_score_weight: float,
) -> dict[int, list[_TitleScore]]:
    if reranker_provider is None:
        return {
            user_id: _top_scores(scores, top_matches)
            for user_id, scores in scores_by_user.items()
        }

    candidate_limit = max(top_matches, rerank_candidates)
    candidates_by_user = {
        user_id: _top_scores(scores, candidate_limit)
        for user_id, scores in scores_by_user.items()
    }
    pairs: list[tuple[str, str]] = []
    keys: list[tuple[int, int]] = []
    for user_id, candidates in candidates_by_user.items():
        for index, candidate in enumerate(candidates):
            keys.append((user_id, index))
            pairs.append((query_text, candidate.title))

    if not pairs:
        return {user_id: [] for user_id in scores_by_user}

    rerank_scores = reranker_provider.predict(pairs)
    if len(rerank_scores) != len(keys):
        return {
            user_id: _top_scores(candidates, top_matches)
            for user_id, candidates in candidates_by_user.items()
        }

    reranked_by_user: dict[int, list[_TitleScore]] = defaultdict(list)
    for (user_id, index), score in zip(keys, rerank_scores):
        candidate = candidates_by_user[user_id][index]
        fused_score = _fuse_retrieval_and_reranker(
            candidate.retrieval_score,
            float(score),
            retrieval_score_weight,
            reranker_score_weight,
        )
        reranked_by_user[user_id].append(
            _TitleScore(candidate.title, candidate.retrieval_score, fused_score)
        )

    return {
        user_id: _top_scores(reranked_by_user.get(user_id, []), top_matches)
        for user_id in candidates_by_user
    }


def _average_score(scores: list[_TitleScore]) -> float:
    if not scores:
        return 0.0
    return sum(item.score for item in scores) / len(scores)


def _select_reviewer_score(authored_score: float, reviewed_score: float) -> float:
    """Use the stronger of a reviewer's authored or reviewed-title matches."""
    return max(authored_score, reviewed_score)


@lru_cache(maxsize=4)
def _build_cached_reviewer_matcher(domain_id: str, config: ReviewerConfig) -> ReviewerMatcher:
    store_path = get_domain_store_path(config.store_path, domain_id)
    reranker = get_cross_encoder_provider(config.reranker_model_name)

    return ReviewerMatcher(
        store=ReviewerStore(store_path, config.collection),
        embedding_provider=SbertEmbeddingProvider(config.model_name),
        sparse_provider=SparseEmbeddingProvider(),
        reranker_provider=reranker,
        config=config,
    )


def get_reviewer_matcher(domain_id: str, config: ReviewerConfig) -> ReviewerMatcher:
    return _build_cached_reviewer_matcher(domain_id, config)


def reset_reviewer_matcher() -> None:
    _build_cached_reviewer_matcher.cache_clear()


def ingest_reviewers(
    domain_id: str,
    profiles: list[ReviewerProfile],
    config: ReviewerConfig,
) -> tuple[int, int]:
    domain_id = normalize_domain_id(domain_id)
    target_path = get_domain_store_path(config.store_path, domain_id)
    staging_path = target_path.parent / f".{target_path.name}.staging-{uuid.uuid4().hex}"
    staging_store = None
    try:
        matcher = get_reviewer_matcher(domain_id, config)
        staging_store = ReviewerStore(staging_path, config.collection)
        result = matcher.ingest(profiles, store=staging_store)
        staging_store.close()
        staging_store = None

        reset_reviewer_matcher()
        swap_store_directories(staging_path, target_path)
        return result
    except Exception:
        if staging_store is not None:
            staging_store.close()
        if staging_path.exists():
            shutil.rmtree(staging_path)
        raise


def suggest_reviewers(
    domain_id: str,
    title: str,
    config: ReviewerConfig,
    *,
    explain: bool = False,
) -> list[ReviewerSuggestion]:
    matcher = get_reviewer_matcher(domain_id, config)
    return matcher.suggest(title, explain=explain)
