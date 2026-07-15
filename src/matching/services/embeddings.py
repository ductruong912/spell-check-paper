from functools import lru_cache
from typing import Protocol, cast

import numpy as np


class EmbeddingProvider(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed các đoạn văn lưu vào kho (passage)."""
        ...

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        """Embed truy vấn khi so khớp (query)."""
        ...


class FakeEmbeddingProvider:
    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


class SbertEmbeddingProvider:
    """Wrapper quanh SentenceTransformer."""

    def __init__(
        self,
        model_name: str,
        batch_size: int = 32,
        torch_num_threads: int = 0,
    ):
        from sentence_transformers import SentenceTransformer

        if batch_size <= 0:
            raise ValueError("Embedding batch size must be greater than zero.")
        if torch_num_threads < 0:
            raise ValueError("Torch thread count must not be negative.")
        if torch_num_threads:
            import torch

            torch.set_num_threads(torch_num_threads)

        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        em_tolist = getattr(embeddings, "tolist", None)
        if callable(em_tolist):
            return cast(list[list[float]], em_tolist())
        return cast(
            list[list[float]],
            [e.tolist() if hasattr(e, "tolist") else list(e) for e in embeddings],
        )

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    # Backward compat — dùng passage prefix
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed_passages(texts)


@lru_cache(maxsize=4)
def get_embedding_provider(
    model_name: str,
    batch_size: int = 32,
    torch_num_threads: int = 0,
) -> SbertEmbeddingProvider:
    """Return one shared embedding provider per model within this process."""
    return SbertEmbeddingProvider(model_name, batch_size, torch_num_threads)


class SparseEmbeddingProvider:
    """Wrapper quanh FastEmbed để sinh Sparse Vectors cho BM25."""
    def __init__(self, model_name: str = "Qdrant/bm25"):
        from fastembed import SparseTextEmbedding
        self.model = SparseTextEmbedding(model_name=model_name)

    def embed_texts(self, texts: list[str]):
        if not texts:
            return []
        # Return list of SparseEmbedding objects (each has .indices and .values properties)
        return list(self.model.embed(texts))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_array = np.array(left, dtype=float)
    right_array = np.array(right, dtype=float)
    denominator = np.linalg.norm(left_array) * np.linalg.norm(right_array)
    if denominator == 0:
        return 0.0
    return float(np.dot(left_array, right_array) / denominator)


class CrossEncoderProvider:
    """Wrapper quanh CrossEncoder để chạy Reranker."""
    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)
        self.is_stsb = "stsb" in model_name.lower()

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        import math
        if not pairs:
            return []
        scores = self.model.predict(pairs, show_progress_bar=False)
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        else:
            scores = list(scores)
        
        # Apply sigmoid to normalize to 0..1 range for logit models (like BGE)
        # STSb models natively output 0..1, so applying sigmoid squashes them
        if self.is_stsb:
            return [max(0.0, min(1.0, float(score))) for score in scores]
        return [1 / (1 + math.exp(-score)) for score in scores]


@lru_cache(maxsize=4)
def get_cross_encoder_provider(model_name: str) -> CrossEncoderProvider:
    return CrossEncoderProvider(model_name)
