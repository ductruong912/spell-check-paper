import hashlib
import logging
from pathlib import Path

# chromadb 0.5.x cố gửi telemetry qua posthog với chữ ký hàm không khớp, làm
# bẩn log bằng các dòng ERROR vô hại kể cả khi đã tắt anonymized_telemetry.
# Hạ cấp logger này để giữ log sạch.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


class FieldVectorStore:
    """Lưu danh mục từ khóa lĩnh vực dưới dạng vector (Chroma, persistent).

    Mỗi từ khóa được embed + normalize sẵn rồi lưu kèm chính text từ khóa. ID
    của mỗi bản ghi là hash của từ khóa đã casefold, nên upsert cùng từ khóa
    (khác hoa/thường) sẽ ghi đè thay vì nhân bản — cho phép upload bổ sung
    (append) nhiều đợt mà vẫn loại trùng tự nhiên.
    """

    def __init__(self, path: str | Path, collection_name: str):
        import chromadb

        store_path = Path(path)
        store_path.mkdir(parents=True, exist_ok=True)
        # Vector phụ thuộc model embedding sinh ra nó; lưu tên model cạnh store để
        # phát hiện khi config đổi model nhưng catalog chưa được embed lại.
        self._model_marker = store_path / "embedding_model.txt"
        self._client = chromadb.PersistentClient(
            path=str(store_path),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        # Embedding đã normalize sẵn nên cosine là không gian khoảng cách phù hợp
        # cho mọi truy vấn nearest-neighbour về sau (scoring hiện dùng lại vector
        # đã lưu để tự tính cosine).
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def _keyword_id(keyword: str) -> str:
        return hashlib.sha1(keyword.casefold().encode("utf-8")).hexdigest()

    def stored_model(self) -> str | None:
        """Tên model embedding đã dùng để dựng catalog hiện tại (None nếu chưa có)."""
        if not self._model_marker.exists():
            return None
        return self._model_marker.read_text(encoding="utf-8").strip() or None

    def add_keywords(
        self, keywords: list[str], embeddings: list[list[float]], model_name: str
    ) -> None:
        """Bổ sung (upsert) từ khóa + vector. Trùng từ khóa sẽ được ghi đè.

        Trộn vector từ hai model khác nhau là vô nghĩa (khác không gian), nên nếu
        catalog hiện có được dựng bằng model khác thì từ chối append.
        """
        if not keywords:
            return
        existing_model = self.stored_model()
        if self.count() > 0 and existing_model and existing_model != model_name:
            raise ValueError(
                f"Vector store đang dùng model '{existing_model}', không thể bổ sung "
                f"bằng model '{model_name}'. Xóa store {self._model_marker.parent} rồi "
                f"upload lại toàn bộ danh mục với model mới."
            )
        ids = [self._keyword_id(keyword) for keyword in keywords]
        self._collection.upsert(ids=ids, embeddings=embeddings, documents=keywords)
        self._model_marker.write_text(model_name, encoding="utf-8")

    def count(self) -> int:
        return self._collection.count()

    def load_all(self) -> tuple[list[str], list[list[float]]]:
        """Trả về (keywords, embeddings) toàn bộ catalog, tương ứng theo index."""
        if self._collection.count() == 0:
            return [], []
        data = self._collection.get(include=["documents", "embeddings"])
        documents = data.get("documents") or []
        embeddings = data.get("embeddings")
        embeddings = [] if embeddings is None else [list(vector) for vector in embeddings]
        return list(documents), embeddings
