from typing import Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class FakeEmbeddingProvider:
    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


class SbertEmbeddingProvider:
    def __init__(self, model_name: str, prefix: str = ""):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        # Một số model (vd e5) yêu cầu tiền tố như "query: " trước mỗi câu;
        # áp dụng đồng nhất cho cả từ khóa lĩnh vực lẫn term của bài.
        self.prefix = prefix

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        inputs = [self.prefix + text for text in texts] if self.prefix else texts
        embeddings = self.model.encode(
            inputs, normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.tolist()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_array = np.array(left, dtype=float)
    right_array = np.array(right, dtype=float)
    denominator = np.linalg.norm(left_array) * np.linalg.norm(right_array)
    if denominator == 0:
        return 0.0
    return float(np.dot(left_array, right_array) / denominator)