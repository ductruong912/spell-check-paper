# plagiarism/index_build.py
import os
import glob
import logging
from datasketch import MinHash
from sentence_transformers import SentenceTransformer

from .io_extract import extract_text
from .normalize import normalize_text, text_for_embedding
from .chunking import chunk_text
from .index_store import IndexStore


def shingles(words, n=5):
    for i in range(len(words) - n + 1):
        yield " ".join(words[i:i+n])


def build_minhash(text: str, ngram=5, num_perm=128) -> MinHash:
    mh = MinHash(num_perm=num_perm)
    words = text.split()
    if len(words) < ngram:
        return mh
    for sh in shingles(words, ngram):
        mh.update(sh.encode("utf-8"))
    return mh


def build_corpus_index(corpus_dir="./corpus", index_dir="./src/plag_index"):
    logging.info("Building plagiarism index from corpus: %s", corpus_dir)

    model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    model = SentenceTransformer(model_name)

    store = IndexStore(num_perm=128, lsh_threshold=0.5, embedding_model=model_name)

    files = []
    for ext in ("pdf", "docx"):
        files.extend(glob.glob(os.path.join(corpus_dir, f"**/*.{ext}"), recursive=True))

    if not files:
        raise RuntimeError(f"No corpus files found in {corpus_dir}")

    chunk_global_id = 0
    for fp in files:
        try:
            raw = extract_text(fp)
            norm = normalize_text(raw)
            chunks = chunk_text(norm)
            if not chunks:
                continue

            embed_chunks = [text_for_embedding(c) for c in chunks]
            vecs = model.encode(embed_chunks, convert_to_numpy=True, normalize_embeddings=True)

            for i, ch in enumerate(chunks):
                mh = build_minhash(ch)
                cid = f"c{chunk_global_id}"
                store.add(cid, mh, vecs[i], {"doc_path": fp, "chunk_text": ch})
                chunk_global_id += 1

            logging.info("Indexed %s (%d chunks)", fp, len(chunks))
        except Exception as e:
            logging.warning("Skip corpus file %s due to error: %s", fp, e)

    store.build()
    store.save(index_dir)
    logging.info("Index saved to %s. Total chunks=%d", index_dir, chunk_global_id)
