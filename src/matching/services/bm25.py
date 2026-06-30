"""BM25 Okapi gọn nhẹ cho khớp từ khóa (lexical) giữa truy vấn và kho text.

Tự cài để khỏi thêm dependency (rank_bm25). Dùng cho điểm lexical 30% khi so
title/keywords bản thảo với kho bài báo hợp lệ. Luồng so khớp dùng `metadata`
ưu tiên EN nên chỉ lọc stopword TIẾNG ANH; tokenize (casefold, \\w+) tự chứa ở
đây để không phụ thuộc field_relevance (tập stopword EN+VI riêng của nó).
"""

from __future__ import annotations

import math
import re


# Stopword tiếng Anh (function words) — bị loại trước khi tính BM25 để tránh
# trùng "oan" trên các từ vô nghĩa như "the", "of", "and" mà mọi title đều có.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
        "from", "has", "have", "in", "into", "is", "it", "its", "of", "on", "or",
        "that", "the", "their", "this", "to", "was", "were", "with", "which",
        "these", "those", "also", "using", "used", "via", "between", "through",
        "toward", "towards", "over", "under", "about",
    }
)


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def bm25_tokens(text: str) -> list[str]:
    """Token đã casefold, bỏ stopword EN — giữ thứ tự/tần suất cho BM25."""
    return [token for token in tokenize(text) if token not in STOPWORDS]


class BM25:
    """BM25 Okapi trên một corpus token đã chuẩn hoá sẵn."""

    def __init__(self, corpus_tokens: list[list[str]], *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_tokens = corpus_tokens
        self.doc_count = len(corpus_tokens)
        self.doc_len = [len(doc) for doc in corpus_tokens]
        self.avgdl = (sum(self.doc_len) / self.doc_count) if self.doc_count else 0.0

        self.term_freqs: list[dict[str, int]] = []
        doc_freq: dict[str, int] = {}
        for doc in corpus_tokens:
            counts: dict[str, int] = {}
            for token in doc:
                counts[token] = counts.get(token, 0) + 1
            self.term_freqs.append(counts)
            for token in counts:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        # IDF Okapi với +1 trong log để luôn không âm (tránh điểm âm khi term phổ biến).
        self.idf: dict[str, float] = {}
        for token, freq in doc_freq.items():
            self.idf[token] = math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))

    def scores(self, query_tokens: list[str]) -> list[float]:
        """Điểm BM25 của truy vấn với từng document trong corpus (cùng thứ tự)."""
        if not self.doc_count or self.avgdl == 0.0:
            return [0.0] * self.doc_count
        unique_query = set(query_tokens)
        scores = [0.0] * self.doc_count
        for index in range(self.doc_count):
            counts = self.term_freqs[index]
            length = self.doc_len[index]
            total = 0.0
            for token in unique_query:
                freq = counts.get(token)
                if not freq:
                    continue
                idf = self.idf.get(token, 0.0)
                denominator = freq + self.k1 * (1 - self.b + self.b * length / self.avgdl)
                total += idf * (freq * (self.k1 + 1)) / denominator
            scores[index] = total
        return scores
