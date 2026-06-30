import hashlib
import logging
from pathlib import Path

# chromadb 0.5.x cố gửi telemetry qua posthog với chữ ký hàm không khớp, làm
# bẩn log bằng các dòng ERROR vô hại kể cả khi đã tắt anonymized_telemetry.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


class ValidPaperStore:
    """Lưu title + list keywords của các bài báo HỢP LỆ dưới dạng vector (Chroma).

    Mỗi bài góp một bản ghi title (text tiêu đề) và một bản ghi keywords (list từ
    khóa nối thành một chuỗi) vào hai collection riêng. Cả hai bản ghi của cùng
    một bài dùng chung id = hash(title + '\\n' + keywords) nên nạp lại cùng một
    bài sẽ ghi đè thay vì nhân bản. Mỗi bản ghi lưu kèm vector (đã normalize) và
    chính text gốc để vừa tính cosine vừa chạy BM25.
    """

    def __init__(self, path: str | Path, title_collection: str, keyword_collection: str):
        # pyrefly: ignore [missing-import]
        import chromadb

        store_path = Path(path)
        store_path.mkdir(parents=True, exist_ok=True)
        # Vector phụ thuộc model embedding; lưu tên model cạnh store để phát hiện
        # khi config đổi model nhưng kho chưa được embed lại.
        self._model_marker = store_path / "embedding_model.txt"
        self._client = chromadb.PersistentClient(
            path=str(store_path),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        self._titles = self._client.get_or_create_collection(
            name=title_collection,
            metadata={"hnsw:space": "cosine"},
        )
        self._keywords = self._client.get_or_create_collection(
            name=keyword_collection,
            metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def title_id(title: str) -> str:
        """Id ổn định của một title."""
        raw = title.casefold()
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def keyword_id(keywords_text: str) -> str:
        """Id ổn định của một chuỗi keywords."""
        raw = keywords_text.casefold()
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def stored_model(self) -> str | None:
        """Tên model embedding đã dùng để dựng kho hiện tại (None nếu chưa có)."""
        if not self._model_marker.exists():
            return None
        return self._model_marker.read_text(encoding="utf-8").strip() or None

    def _check_model(self, model_name: str) -> None:
        existing_model = self.stored_model()
        if (self.count_titles() > 0 or self.count_keywords() > 0) and existing_model and existing_model != model_name:
            raise ValueError(
                f"Valid-paper store đang dùng model '{existing_model}', không thể bổ "
                f"sung bằng model '{model_name}'. Xóa {self._model_marker.parent} rồi "
                f"nạp lại toàn bộ với model mới."
            )

    def add_titles(
        self,
        *,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        model_name: str,
    ) -> None:
        if not ids:
            return
        self._check_model(model_name)
        self._titles.upsert(ids=ids, embeddings=embeddings, documents=texts)
        self._model_marker.write_text(model_name, encoding="utf-8")

    def add_keywords(
        self,
        *,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        model_name: str,
    ) -> None:
        if not ids:
            return
        self._check_model(model_name)
        self._keywords.upsert(ids=ids, embeddings=embeddings, documents=texts)
        self._model_marker.write_text(model_name, encoding="utf-8")

    def count_titles(self) -> int:
        return self._titles.count()

    def count_keywords(self) -> int:
        return self._keywords.count()

    @staticmethod
    def _load(collection) -> tuple[list[str], list[list[float]]]:
        if collection.count() == 0:
            return [], []
        data = collection.get(include=["documents", "embeddings"])
        documents = data.get("documents") or []
        embeddings = data.get("embeddings")
        embeddings = [] if embeddings is None else [list(vector) for vector in embeddings]
        return list(documents), embeddings

    def load_titles(self) -> tuple[list[str], list[list[float]]]:
        return self._load(self._titles)

    def load_keywords(self) -> tuple[list[str], list[list[float]]]:
        return self._load(self._keywords)
