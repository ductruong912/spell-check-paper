# plagiarism/index_store.py
import os, pickle
from datasketch import MinHashLSH
import faiss
import numpy as np

class IndexStore:
    def __init__(self, num_perm=128, lsh_threshold=0.5, embedding_model: str = "", dim: int | None = None):
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=lsh_threshold, num_perm=num_perm)
        self.vecs = []
        self.meta = []  # (chunk_id, {doc_path, chunk_text})
        self.faiss = None
        self.embedding_model = embedding_model
        self.dim = dim

    def add(self, chunk_id: str, minhash, vec: np.ndarray, meta: dict):
        self.lsh.insert(chunk_id, minhash)
        v = vec.astype("float32")
        self.vecs.append(v)
        self.meta.append((chunk_id, meta))
        if self.dim is None:
            self.dim = int(v.shape[0])

    def build(self):
        if not self.vecs:
            raise RuntimeError("No vectors to build FAISS index.")
        mat = np.vstack(self.vecs).astype("float32")
        self.faiss = faiss.IndexFlatIP(mat.shape[1])  # cosine if vectors normalized
        self.faiss.add(mat)

    def save(self, dir_path: str):
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, "store.pkl"), "wb") as f:
            pickle.dump({
                "num_perm": self.num_perm,
                "lsh": self.lsh,
                "meta": self.meta,
                "vecs": self.vecs,
                "embedding_model": self.embedding_model,
                "dim": self.dim,
            }, f)
        faiss.write_index(self.faiss, os.path.join(dir_path, "faiss.index"))

    @staticmethod
    def load(dir_path: str):
        with open(os.path.join(dir_path, "store.pkl"), "rb") as f:
            obj = pickle.load(f)
        store = IndexStore(
            num_perm=obj.get("num_perm", 128),
            embedding_model=obj.get("embedding_model", ""),
            dim=obj.get("dim", None),
        )
        store.lsh = obj["lsh"]
        store.meta = obj["meta"]
        store.vecs = obj["vecs"]
        store.faiss = faiss.read_index(os.path.join(dir_path, "faiss.index"))
        return store
