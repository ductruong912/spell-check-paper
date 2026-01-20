"""Chia đoạn văn để gửi kiểm tra đạo văn (chunking + overlap)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from utils.config import (
    DEFAULT_CHUNK_WORDS,
    DEFAULT_OVERLAP_WORDS,
    DYNAMIC_CHUNK_SMALL_THRESHOLD,
    DYNAMIC_CHUNK_SMALL_SIZE,
    DYNAMIC_CHUNK_SMALL_OVERLAP,
    DYNAMIC_CHUNK_MEDIUM_THRESHOLD,
    DYNAMIC_CHUNK_MEDIUM_SIZE,
    DYNAMIC_CHUNK_MEDIUM_OVERLAP,
    DYNAMIC_CHUNK_LARGE_THRESHOLD,
    DYNAMIC_CHUNK_LARGE_SIZE,
    DYNAMIC_CHUNK_LARGE_OVERLAP,
    DYNAMIC_CHUNK_XLARGE_SIZE,
    DYNAMIC_CHUNK_XLARGE_OVERLAP,
)
from .text_extraction import extract_body_text_from_docx, extract_references_text_from_docx


@dataclass
class TextChunk:
    """Một chunk text kèm label và số từ."""
    label: str
    text: str
    words: int


def get_dynamic_chunk_config(total_words: int) -> Dict[str, int]:
    """Chọn (chunk_size, overlap) theo tổng số từ."""
    if total_words < DYNAMIC_CHUNK_SMALL_THRESHOLD:
        return {"chunk_size": DYNAMIC_CHUNK_SMALL_SIZE, "overlap": DYNAMIC_CHUNK_SMALL_OVERLAP}
    elif total_words < DYNAMIC_CHUNK_MEDIUM_THRESHOLD:
        return {"chunk_size": DYNAMIC_CHUNK_MEDIUM_SIZE, "overlap": DYNAMIC_CHUNK_MEDIUM_OVERLAP}
    elif total_words < DYNAMIC_CHUNK_LARGE_THRESHOLD:
        return {"chunk_size": DYNAMIC_CHUNK_LARGE_SIZE, "overlap": DYNAMIC_CHUNK_LARGE_OVERLAP}
    else:
        return {"chunk_size": DYNAMIC_CHUNK_XLARGE_SIZE, "overlap": DYNAMIC_CHUNK_XLARGE_OVERLAP}


def _chunk_words(
    text: str,
    target_words: int = DEFAULT_CHUNK_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> List[str]:
    """Chunk theo số từ + overlap để giảm mất ngữ cảnh ở biên."""
    words = (text or "").split()
    if not words:
        return []

    target_words = max(200, int(target_words))
    overlap_words = max(0, min(int(overlap_words), target_words // 2))

    chunks: List[str] = []
    i = 0
    n = len(words)

    while i < n:
        j = min(n, i + target_words)
        chunk = " ".join(words[i:j]).strip()
        if chunk:
            chunks.append(chunk)

        if j >= n:
            break
        i = j - overlap_words

    return chunks


def extract_body_chunks_from_docx(
    path: str,
    min_words_per_chunk: int = 50,
    chunk_target_words: int = 900,
    chunk_overlap_words: int = 120,
) -> List[TextChunk]:
    """Trích body từ DOCX rồi chia thành chunks."""
    body = extract_body_text_from_docx(path)
    if not body.strip():
        return []

    parts = _chunk_words(body, target_words=chunk_target_words, overlap_words=chunk_overlap_words)
    out: List[TextChunk] = []
    for i, part in enumerate(parts, start=1):
        w = len(part.split())
        if w >= min_words_per_chunk:
            out.append(TextChunk(label=f"Phần {i}", text=part, words=w))
    return out


def extract_reference_chunks_from_docx(
    path: str,
    min_words_per_ref: int = 20,
    chunk_target_words: int = 1000,
    chunk_overlap_words: int = 100,
) -> List[TextChunk]:
    """Trích references rồi chia chunks (ưu tiên theo dòng)."""
    refs_text = extract_references_text_from_docx(path)
    if not refs_text.strip():
        return []

    ref_lines = [line.strip() for line in refs_text.split("\n") if line.strip()]
    if not ref_lines:
        return []

    if len(ref_lines) <= 10:
        out: List[TextChunk] = []
        for i, line in enumerate(ref_lines, start=1):
            w = len(line.split())
            if w >= min_words_per_ref:
                out.append(TextChunk(label=f"ref_{i}", text=line, words=w))
        return out

    refs_combined = "\n".join(ref_lines)
    parts = _chunk_words(refs_combined, target_words=chunk_target_words, overlap_words=chunk_overlap_words)
    out: List[TextChunk] = []
    for i, part in enumerate(parts, start=1):
        w = len(part.split())
        if w >= min_words_per_ref:
            out.append(TextChunk(label=f"ref_chunk_{i}", text=part, words=w))
    return out
