"""So title + keywords bản thảo với kho bài báo HỢP LỆ.

Luồng (mỗi mặt title/keywords độc lập):
1. Embed truy vấn thành 1 vector dense và 1 vector sparse.
2. Với từng bản ghi trong kho: Qdrant tìm top N theo dense và top N theo sparse.
3. Tính điểm trên các ứng viên trả về: semantic = cosine(vector truy vấn, vector bản ghi);
   lexical = dot_product(sparse_query, sparse_doc) đã normalize 0..1 theo điểm cao nhất.
4. Điểm retrieval mỗi bản ghi = semantic/lexical theo config.
5. Nếu bật reranker, trộn điểm retrieval và reranker theo config.
6. Lấy eval_top_n bản ghi điểm cao nhất rồi tính trung bình -> điểm của mặt đó.
overall_score = trung bình điểm title + điểm keywords (mặt nào có dữ liệu).
"""

import shutil
import uuid
from functools import lru_cache
from pathlib import Path

from config import ValidPaperConfig
from domain_ids import get_domain_store_path, swap_store_directories
from .embeddings import (
    CrossEncoderProvider,
    EmbeddingProvider,
    SparseEmbeddingProvider,
    cosine_similarity,
    get_embedding_provider,
    get_cross_encoder_provider,
)
from ..models.matching import ValidPaperMatch, ValidPaperResult, ValidPaperSideResult
from ..repositories.valid_paper_store import ValidPaperStore
from .preprocessing import normalize_keywords_text, normalize_keyword_tokens, normalize_title


def fuse_retrieval_and_reranker(
    retrieval_score: float,
    reranker_score: float,
    retrieval_weight: float,
    reranker_weight: float,
) -> float:
    """Combine normalized retrieval and reranker scores using configured weights."""
    total_weight = retrieval_weight + reranker_weight
    if total_weight <= 0:
        return 0.0
    return (
        retrieval_score * retrieval_weight + reranker_score * reranker_weight
    ) / total_weight


def join_keywords(keywords: list[str]) -> str:
    """Gộp list keywords thành một chuỗi (1 vector) để embed và chạy BM25."""
    return normalize_keywords_text(keywords)


class ValidPaperMatcher:
    def __init__(
        self,
        store: ValidPaperStore,
        embedding_provider: EmbeddingProvider,
        sparse_provider: SparseEmbeddingProvider,
        reranker_provider: CrossEncoderProvider | None,
        config: ValidPaperConfig,
    ):
        self.config = config
        self.store = store
        self.embedding_provider = embedding_provider
        self.sparse_provider = sparse_provider
        self.reranker_provider = reranker_provider

    def match(
        self, title: str | None, keywords: list[str], *, explain: bool
    ) -> ValidPaperResult:
        title = normalize_title(title) or None
        keywords = normalize_keyword_tokens(keywords)

        title_result = None
        if title and title.strip():
            title_result = self._side_score(
                title,
                self.store.title_collection,
                self.config.title_semantic_weight, self.config.title_lexical_weight,
                explain
            )

        keyword_result = None
        keywords_text = join_keywords(keywords)
        if keywords_text:
            keyword_result = self._side_score(
                keywords_text, self.store.keyword_collection,
                self.config.keyword_semantic_weight, self.config.keyword_lexical_weight,
                explain
            )

        total_weight = 0.0
        weighted_sum = 0.0

        if title_result is not None:
            weighted_sum += title_result.score * self.config.title_score_weight
            total_weight += self.config.title_score_weight
            
        if keyword_result is not None:
            weighted_sum += keyword_result.score * self.config.keyword_score_weight
            total_weight += self.config.keyword_score_weight

        overall = weighted_sum / total_weight if total_weight > 0 else None
        suitable = overall >= self.config.suitable_threshold if overall is not None else None
        return ValidPaperResult(
            overall_score=overall, suitable=suitable, title=title_result, keywords=keyword_result
        )

    def _side_score(
        self,
        query_text: str,
        collection_name: str,
        semantic_weight: float,
        lexical_weight: float,
        explain: bool,
    ) -> ValidPaperSideResult:
        if not self.store._client.collection_exists(collection_name) or self.store._client.count(collection_name).count == 0:
            return ValidPaperSideResult(score=0.0, matches=[])

        query_embedding = self.embedding_provider.embed_query([query_text])[0]
        sparse_se = self.sparse_provider.embed_texts([query_text])[0]
        
        from qdrant_client.models import SparseVector
        
        sparse_items = [
            (int(str(index)), float(str(value)))
            for index, value in zip(sparse_se.indices, sparse_se.values)
            if index is not None and value is not None
        ]
        indices = [index for index, _ in sparse_items]
        values = [value for _, value in sparse_items]
        sparse_vector = SparseVector(indices=indices, values=values)
        
        ideal_bm25 = sum(v * v for v in values)

        # Retrieve top candidates from both dense and sparse indexes
        candidate_pool_size = self.config.top_k * 5
        
        dense_results = self.store._client.query_points(
            collection_name=collection_name,
            query=query_embedding,
            using="dense",
            limit=candidate_pool_size,
            with_payload=True,
            with_vectors=True,
        ).points
        
        sparse_results = self.store._client.query_points(
            collection_name=collection_name,
            query=sparse_vector,
            using="sparse",
            limit=candidate_pool_size,
            with_payload=True,
            with_vectors=True,
        ).points
        
        # Combine unique points
        candidates = {}
        for r in dense_results + sparse_results:
            if r.id not in candidates:
                candidates[r.id] = r
                
        # Calculate exact combined scores
        matches_unsorted = []
        for r in candidates.values():
            vecs = r.vector
            if not vecs: continue
            
            # Semantic Score
            doc_dense = vecs.get("dense")
            if doc_dense is not None:
                semantic_score = max(0.0, min(1.0, cosine_similarity(query_embedding, doc_dense)))
            else:
                semantic_score = 0.0
                
            # Lexical Score (dot product)
            doc_sparse = vecs.get("sparse")
            lexical_score = 0.0
            if doc_sparse is not None and ideal_bm25 > 0:
                doc_indices = doc_sparse.indices
                doc_values = doc_sparse.values
                # compute dot product matching indices
                dot = 0.0
                query_dict = dict(zip(indices, values))
                for idx, val in zip(doc_indices, doc_values):
                    if idx in query_dict:
                        dot += query_dict[idx] * val
                lexical_score = min(1.0, dot / ideal_bm25)
                
            combined = semantic_weight * semantic_score + lexical_weight * lexical_score
            text = r.payload.get("text", "")
            
            matches_unsorted.append(
                ValidPaperMatch(
                    text=text,
                    score=combined,
                    semantic=semantic_score,
                    lexical=lexical_score,
                )
            )

        matches_unsorted.sort(key=lambda m: m.score, reverse=True)
        matches = matches_unsorted[: self.config.top_k]

        if self.reranker_provider and matches:
            pairs = [(query_text, match.text) for match in matches]
            rerank_scores = self.reranker_provider.predict(pairs)
            new_matches = []
            for i, match in enumerate(matches):
                final_score = fuse_retrieval_and_reranker(
                    match.score,
                    rerank_scores[i],
                    self.config.retrieval_score_weight,
                    self.config.reranker_score_weight,
                )
                new_matches.append(
                    ValidPaperMatch(
                        text=match.text,
                        score=final_score,
                        semantic=match.semantic,
                        lexical=match.lexical,
                    )
                )
            matches = new_matches
            matches.sort(key=lambda x: x.score, reverse=True)

        if not matches:
            average = 0.0
        else:
            top_n = matches[:self.config.eval_top_n]
            average = sum(m.score for m in top_n) / len(top_n)
        return ValidPaperSideResult(score=average, matches=matches if explain else [])


@lru_cache(maxsize=4)
def _build_cached_matcher(domain_id: str, config: ValidPaperConfig) -> ValidPaperMatcher | None:
    store_path = get_domain_store_path(config.vector_store_path, domain_id)
    store = ValidPaperStore(
        str(store_path), config.title_collection, config.keyword_collection
    )

    provider = get_embedding_provider(
        config.model_name, config.embedding_batch_size, config.torch_num_threads
    )
    sparse_provider = SparseEmbeddingProvider()
    
    reranker = get_cross_encoder_provider(config.reranker_model_name)
        
    return ValidPaperMatcher(
        store, provider, sparse_provider, reranker, config
    )


def get_valid_paper_matcher(domain_id: str, config: ValidPaperConfig) -> ValidPaperMatcher | None:
    """Tạo matcher (nạp model) và cache theo config."""
    return _build_cached_matcher(domain_id, config)


def reset_valid_paper_matcher() -> None:
    """Xóa cache matcher để lần gọi sau nạp lại kho vừa cập nhật."""
    _build_cached_matcher.cache_clear()


def replace_valid_paper_batch(
    domain_id: str,
    papers: list[tuple[str | None, list[str]]],
    config: ValidPaperConfig,
) -> tuple[int, int]:
    """Build a complete valid-paper store and swap it in after success."""
    target_path = get_domain_store_path(config.vector_store_path, domain_id)
    staging_path = target_path.parent / f".{target_path.name}.staging-{uuid.uuid4().hex}"
    staging_store = None
    try:
        title_texts: list[str] = []
        title_ids: list[str] = []
        seen_titles: set[str] = set()
        keyword_texts: list[str] = []
        keyword_ids: list[str] = []
        seen_keywords: set[str] = set()

        for title, keywords in papers:
            normalized_title = normalize_title(title) if title else ""
            if normalized_title:
                title_id = ValidPaperStore.title_id(normalized_title)
                if title_id not in seen_titles:
                    seen_titles.add(title_id)
                    title_ids.append(title_id)
                    title_texts.append(normalized_title)

            normalized_keywords = normalize_keywords_text(keywords)
            if normalized_keywords:
                keyword_id = ValidPaperStore.keyword_id(normalized_keywords)
                if keyword_id not in seen_keywords:
                    seen_keywords.add(keyword_id)
                    keyword_ids.append(keyword_id)
                    keyword_texts.append(normalized_keywords)

        if not title_texts and not keyword_texts:
            raise ValueError("No valid titles or keywords found in the batch.")

        provider = get_embedding_provider(
            config.model_name, config.embedding_batch_size, config.torch_num_threads
        )
        sparse_provider = SparseEmbeddingProvider()
        staging_store = ValidPaperStore(
            str(staging_path), config.title_collection, config.keyword_collection
        )

        all_texts = title_texts + keyword_texts
        all_embeddings = provider.embed_passages(all_texts) if all_texts else []
        all_sparse_embeddings = sparse_provider.embed_texts(all_texts) if all_texts else []
        title_count = len(title_texts)

        if title_texts:
            staging_store.add_titles(
                ids=title_ids,
                texts=title_texts,
                embeddings=all_embeddings[:title_count],
                sparse_embeddings=all_sparse_embeddings[:title_count],
                model_name=config.model_name,
            )
        if keyword_texts:
            staging_store.add_keywords(
                ids=keyword_ids,
                texts=keyword_texts,
                embeddings=all_embeddings[title_count:],
                sparse_embeddings=all_sparse_embeddings[title_count:],
                model_name=config.model_name,
            )
        staging_store.close()
        staging_store = None

        reset_valid_paper_matcher()
        swap_store_directories(staging_path, target_path)
        return len(title_texts), len(keyword_texts)
    except Exception:
        if staging_store is not None:
            staging_store.close()
        if staging_path.exists():
            shutil.rmtree(staging_path)
        raise
