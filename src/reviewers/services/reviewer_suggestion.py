from __future__ import annotations

import re
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from config import ReviewerConfig
from domain_ids import get_domain_store_path, normalize_domain_id, swap_store_directories
from documents import normalize_whitespace
from matching.services.embeddings import (
    CrossEncoderProvider,
    SparseEmbeddingProvider,
    cosine_similarity,
    get_embedding_provider,
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

        top_authored_by_user = _select_best_score_by_user(authored_scores)
        top_reviewed_by_user = _select_best_score_by_user(reviewed_scores)
        if self.reranker_provider is None:
            raise RuntimeError("Reviewer reranker is unavailable.")
        rerank_scores = _rerank_representative_titles_by_group(
            query_text,
            user_info,
            top_authored_by_user,
            top_reviewed_by_user,
            self.reranker_provider,
        )
        ranked_suggestions: list[tuple[int, float, ReviewerSuggestion]] = []

        for user_id, (user, articles, reviewed_articles) in user_info.items():
            top_authored = top_authored_by_user.get(user_id)
            top_reviewed = top_reviewed_by_user.get(user_id)
            authored_score = rerank_scores.get((user_id, _AUTHORED_SOURCE), 0.0)
            reviewed_score = rerank_scores.get((user_id, _REVIEWED_SOURCE), 0.0)
            group = _reviewer_group(articles, reviewed_articles)
            score = _calculate_reviewer_score(group, authored_score, reviewed_score)

            suggestion = ReviewerSuggestion(
                user_id=user_id,
                user=user,
                group=group,
                score=score,
                authored_score=authored_score,
                reviewed_score=reviewed_score,
                matched_articles=[top_authored.title] if explain and top_authored else [],
                matched_reviewed_articles=[top_reviewed.title] if explain and top_reviewed else [],
            )
            ranked_suggestions.append((group, score, suggestion))

        ranked_suggestions.sort(key=_reviewer_sort_key)
        return [suggestion for _, _, suggestion in ranked_suggestions]


def _select_best_score_by_user(
    scores_by_user: dict[int, list[_TitleScore]],
) -> dict[int, _TitleScore]:
    return {
        user_id: max(scores, key=lambda item: item.retrieval_score)
        for user_id, scores in scores_by_user.items()
        if scores
    }


def _rerank_representative_titles_by_group(
    query_text: str,
    user_info: dict[int, tuple[str, list[str], list[str]]],
    authored_by_user: dict[int, _TitleScore],
    reviewed_by_user: dict[int, _TitleScore],
    reranker_provider: CrossEncoderProvider | None,
) -> dict[tuple[int, str], float]:
    if reranker_provider is None:
        raise RuntimeError("Reviewer reranker is unavailable.")

    title_rerank_scores: dict[tuple[int, str], float] = {}
    for group in (1, 2, 3):
        pairs: list[tuple[str, str]] = []
        keys: list[tuple[int, str]] = []
        for user_id, (_, articles, reviewed_articles) in user_info.items():
            if _reviewer_group(articles, reviewed_articles) != group:
                continue
            if group in (1, 3) and (authored := authored_by_user.get(user_id)):
                pairs.append((query_text, authored.title))
                keys.append((user_id, _AUTHORED_SOURCE))
            if group in (1, 2) and (reviewed := reviewed_by_user.get(user_id)):
                pairs.append((query_text, reviewed.title))
                keys.append((user_id, _REVIEWED_SOURCE))

        if not pairs:
            continue
        scores = reranker_provider.predict(pairs)
        if len(scores) != len(keys):
            raise RuntimeError("Reviewer reranker returned an invalid score count.")
        title_rerank_scores.update(
            (key, max(0.0, min(1.0, float(score))))
            for key, score in zip(keys, scores)
        )

    return title_rerank_scores


def _reviewer_group(articles: list[str], reviewed_articles: list[str]) -> int:
    if articles and reviewed_articles:
        return 1
    if reviewed_articles:
        return 2
    return 3


def _calculate_reviewer_score(
    group: int,
    authored_score: float,
    reviewed_score: float,
) -> float:
    if group == 1:
        return 0.7 * reviewed_score + 0.3 * authored_score
    if group == 2:
        return reviewed_score
    return authored_score


def _reviewer_sort_key(
    item: tuple[int, float, ReviewerSuggestion],
) -> tuple[int, float, float, int]:
    group, rank_score, suggestion = item
    return (group, -rank_score, -suggestion.score, suggestion.user_id)


_REVIEWER_MATCHER_CACHE: dict[tuple[str, ReviewerConfig], ReviewerMatcher] = {}


def _build_reviewer_matcher(domain_id: str, config: ReviewerConfig) -> ReviewerMatcher:
    store_path = get_domain_store_path(config.store_path, domain_id)
    reranker = get_cross_encoder_provider(config.reranker_model_name)

    return ReviewerMatcher(
        store=ReviewerStore(store_path, config.collection),
        embedding_provider=get_embedding_provider(
            config.model_name, config.embedding_batch_size, config.torch_num_threads
        ),
        sparse_provider=SparseEmbeddingProvider(),
        reranker_provider=reranker,
        config=config,
    )


def get_reviewer_matcher(domain_id: str, config: ReviewerConfig) -> ReviewerMatcher:
    key = (domain_id, config)
    matcher = _REVIEWER_MATCHER_CACHE.get(key)
    if matcher is None:
        matcher = _build_reviewer_matcher(domain_id, config)
        _REVIEWER_MATCHER_CACHE[key] = matcher
    return matcher


def reset_reviewer_matcher() -> None:
    for matcher in _REVIEWER_MATCHER_CACHE.values():
        matcher.store.close()
    _REVIEWER_MATCHER_CACHE.clear()


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
        staging_store = ReviewerStore(staging_path, config.collection)
        matcher = ReviewerMatcher(
            store=staging_store,
            embedding_provider=get_embedding_provider(
                config.model_name, config.embedding_batch_size, config.torch_num_threads
            ),
            sparse_provider=SparseEmbeddingProvider(),
            reranker_provider=get_cross_encoder_provider(config.reranker_model_name),
            config=config,
        )
        result = matcher.ingest(profiles)
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
