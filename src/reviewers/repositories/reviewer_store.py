from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
import uuid

from reviewers.models import ReviewerStoredTitle, ReviewerTitlePoint


class ReviewerStore:
    def __init__(self, path: str | Path, collection: str):
        from qdrant_client import QdrantClient

        store_path = Path(path)
        store_path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(store_path))
        self.collection = collection

    def _ensure_collection(self, dense_size: int) -> None:
        from qdrant_client.models import Distance, SparseVectorParams, VectorParams

        if self._client.collection_exists(self.collection):
            return
        self._client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "dense": VectorParams(size=dense_size, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(),
            },
        )

    @staticmethod
    def point_id(user_id: int, source: str, title: str) -> str:
        raw = f"{user_id}\n{source}\n{title.strip().casefold()}"
        hashed = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return str(uuid.UUID(hex=hashed))

    def replace_title_points(
        self,
        title_points: list[ReviewerTitlePoint],
        dense_embeddings: list[list[float]],
        sparse_embeddings: list[Any] | None,
    ) -> None:
        if self._client.collection_exists(self.collection):
            self._client.delete_collection(self.collection)
        if not title_points:
            return

        dense_size = len(dense_embeddings[0]) if dense_embeddings else 0
        if dense_size <= 0:
            return
        self._ensure_collection(dense_size)

        from qdrant_client.models import PointStruct, SparseVector

        points = []
        for index, title_point in enumerate(title_points):
            vectors: dict[str, Any] = {"dense": dense_embeddings[index]}
            if sparse_embeddings and index < len(sparse_embeddings):
                sparse_embedding = sparse_embeddings[index]
                indices = (
                    sparse_embedding.indices.tolist()
                    if hasattr(sparse_embedding.indices, "tolist")
                    else sparse_embedding.indices
                )
                values = (
                    sparse_embedding.values.tolist()
                    if hasattr(sparse_embedding.values, "tolist")
                    else sparse_embedding.values
                )
                vectors["sparse"] = SparseVector(indices=indices, values=values)

            points.append(
                PointStruct(
                    id=self.point_id(title_point.user_id, title_point.source, title_point.title),
                    vector=vectors,
                    payload={
                        "user_id": title_point.user_id,
                        "user": title_point.user,
                        "source": title_point.source,
                        "title": title_point.title,
                        "articles": title_point.articles,
                        "reviewed_articles": title_point.reviewed_articles,
                    },
                )
            )

        self._client.upsert(collection_name=self.collection, points=points)

    def list_title_points(self) -> list[ReviewerStoredTitle]:
        if not self._client.collection_exists(self.collection):
            return []

        stored: list[ReviewerStoredTitle] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                collection_name=self.collection,
                limit=512,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for point in points:
                payload = point.payload or {}
                vectors = point.vector or {}
                dense_vector = vectors.get("dense") if isinstance(vectors, dict) else None
                sparse_vector = vectors.get("sparse") if isinstance(vectors, dict) else None
                if dense_vector is None:
                    continue
                stored.append(
                    ReviewerStoredTitle(
                        user_id=int(payload.get("user_id")),
                        user=str(payload.get("user") or ""),
                        source=str(payload.get("source") or ""),
                        title=str(payload.get("title") or ""),
                        articles=list(payload.get("articles") or []),
                        reviewed_articles=list(payload.get("reviewed_articles") or []),
                        dense_vector=dense_vector,
                        sparse_vector=sparse_vector,
                    )
                )
            if offset is None:
                break
        return stored

    def count_users(self) -> int:
        return len({point.user_id for point in self.list_title_points()})

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()
