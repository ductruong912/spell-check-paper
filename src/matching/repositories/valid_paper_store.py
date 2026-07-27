import hashlib
import logging
from pathlib import Path
import uuid
from typing import Any

from ..services.preprocessing import normalize_keywords_text, normalize_title

class ValidPaperStore:
    """Lưu title + list keywords của các bài báo HỢP LỆ dưới dạng vector (Qdrant).

    Mỗi bài góp một bản ghi title (text tiêu đề) và một bản ghi keywords (list từ
    khóa nối thành một chuỗi) vào hai collection riêng. Cả hai bản ghi của cùng
    một bài dùng chung id sinh từ hash(title + '\\n' + keywords) nên nạp lại cùng một
    bài sẽ ghi đè thay vì nhân bản. Mỗi bản ghi lưu kèm dense vector (cosine) và 
    sparse vector (dot product / BM25) cùng với chính text gốc.
    """

    def __init__(self, path: str | Path, title_collection: str, keyword_collection: str):
        from qdrant_client import QdrantClient

        store_path = Path(path)
        store_path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(store_path))
        self.title_collection = title_collection
        self.keyword_collection = keyword_collection

    def _ensure_collection(self, collection_name: str, dense_size: int):
        from qdrant_client.models import VectorParams, Distance, SparseVectorParams
        if not self._client.collection_exists(collection_name):
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": VectorParams(size=dense_size, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(),
                }
            )

    @staticmethod
    def title_id(title: str) -> str:
        """Id ổn định của một title."""
        raw = normalize_title(title)
        hashed = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return str(uuid.UUID(hex=hashed))

    @staticmethod
    def keyword_id(keywords_text: str) -> str:
        """Id ổn định của một chuỗi keywords."""
        raw = normalize_keywords_text(keywords_text)
        hashed = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return str(uuid.UUID(hex=hashed))

    def _add_points(
        self,
        collection_name: str,
        ids: list[str],
        texts: list[str],
        dense_embeddings: list[list[float]],
        sparse_embeddings: list[Any] | None,
    ) -> None:
        if not ids:
            return
            
        dense_size = len(dense_embeddings[0]) if dense_embeddings else 0
        if dense_size > 0:
            self._ensure_collection(collection_name, dense_size)

        from qdrant_client.models import PointStruct, SparseVector

        points = []
        for i in range(len(ids)):
            vectors = {}
            if dense_embeddings and i < len(dense_embeddings):
                vectors["dense"] = dense_embeddings[i]
            if sparse_embeddings and i < len(sparse_embeddings):
                se = sparse_embeddings[i]
                sparse_items = [
                    (int(str(index)), float(str(value)))
                    for index, value in zip(se.indices, se.values)
                    if index is not None and value is not None
                ]
                indices = [index for index, _ in sparse_items]
                values = [value for _, value in sparse_items]
                vectors["sparse"] = SparseVector(indices=indices, values=values)

            point = PointStruct(
                id=ids[i],
                vector=vectors,
                payload={"text": texts[i]},
            )
            points.append(point)

        self._client.upsert(
            collection_name=collection_name,
            points=points,
        )

    def add_titles(
        self,
        *,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        sparse_embeddings: list[Any] | None = None,
        model_name: str = "",
    ) -> None:
        self._add_points(self.title_collection, ids, texts, embeddings, sparse_embeddings)

    def add_keywords(
        self,
        *,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        sparse_embeddings: list[Any] | None = None,
        model_name: str = "",
    ) -> None:
        self._add_points(self.keyword_collection, ids, texts, embeddings, sparse_embeddings)

    def count_titles(self) -> int:
        if not self._client.collection_exists(self.title_collection):
            return 0
        return self._client.count(self.title_collection).count

    def count_keywords(self) -> int:
        if not self._client.collection_exists(self.keyword_collection):
            return 0
        return self._client.count(self.keyword_collection).count

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()
