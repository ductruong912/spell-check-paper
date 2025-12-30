# plagiarism/chunking.py
from __future__ import annotations
import re
from typing import List

_SENT_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s+|\n+")

def _split_sentences(text: str) -> List[str]:
    parts = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]
    return parts

def chunk_text(
    text: str,
    min_words: int = 60,
    max_words: int = 180,
    overlap_words: int = 30,
) -> List[str]:
    """
    Chunk theo câu (sentence-based) để ổn định với văn bản học thuật.
    - min_words/max_words: khung độ dài chunk theo số từ
    - overlap_words: chồng lấp để bắt paraphrase tốt hơn
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    sents = _split_sentences(text)
    if not sents:
        return []

    chunks: List[str] = []
    cur_words: List[str] = []
    cur_len = 0

    def flush():
        nonlocal cur_words, cur_len
        if cur_len >= min_words:
            chunks.append(" ".join(cur_words).strip())
        cur_words, cur_len = [], 0

    for sent in sents:
        w = sent.split()
        if not w:
            continue

        # Nếu thêm câu này vượt max_words -> flush + overlap
        if cur_len + len(w) > max_words:
            flush()
            # overlap từ câu trước (nếu có)
            if chunks and overlap_words > 0:
                tail = chunks[-1].split()[-overlap_words:]
                cur_words = tail[:]
                cur_len = len(cur_words)

        cur_words.extend(w)
        cur_len += len(w)

    # flush phần cuối
    if cur_words:
        chunks.append(" ".join(cur_words).strip())

    # lọc chunk quá ngắn
    chunks = [c for c in chunks if len(c.split()) >= max(10, min_words // 2)]
    return chunks
