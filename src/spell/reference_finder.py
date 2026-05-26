from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

from utils.config import REF_TAIL_WINDOW


REF_SCORE_THRESHOLD = 4
REF_MIN_RUN_LENGTH = 6

REF_HEADING_KEYWORDS = {
    "references",
    "reference",
    "bibliography",
    "works cited",
    "works-cited",
    "tai lieu tham khao",
    "tai lieu trich dan",
}

REF_HEADING_PREFIX_RE = re.compile(r"^\s*(\d{1,2}\s*[\.\)]\s*)?(.*)$")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DOI_RE = re.compile(r"\bdoi\s*:\s*\S+|\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
CITATION_PREFIX_RE = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}\.)\s+")
INITIALS_RE = re.compile(r"\b[A-Z]\.\s*,?\s*[A-Z]\.")
AUTHOR_RE = re.compile(r"\b[A-Z][a-z]+,\s*[A-Z]\.")


def _strip_diacritics(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text or "") if unicodedata.category(ch) != "Mn"
    )


def _normalize_for_heading(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.replace("\ufeff", "").replace("\u200b", "")
    normalized = _strip_diacritics(normalized)
    normalized = re.sub(r"\s+", " ", normalized.strip().lower())
    return normalized


def _split_lines_with_offsets(text: str) -> List[Tuple[str, int, int]]:
    lines: List[Tuple[str, int, int]] = []
    offset = 0
    for raw in (text or "").splitlines(True):
        start = offset
        offset += len(raw)
        lines.append((raw.rstrip("\r\n"), start, offset))
    return lines


def _looks_like_heading(norm_line: str) -> bool:
    if not norm_line or len(norm_line) > 70 or norm_line.endswith("."):
        return False
    if sum(1 for ch in norm_line if ch in ".,;!?") >= 2:
        return False
    return len(norm_line.split()) <= 8


def _is_reference_heading(line: str) -> bool:
    norm = _normalize_for_heading(line).strip(":;.-–— ").strip()
    match = REF_HEADING_PREFIX_RE.match(norm)
    heading = (match.group(2) or "").strip(":;.-–— ").strip() if match else norm
    if heading in REF_HEADING_KEYWORDS:
        return True
    return any(keyword in heading and _looks_like_heading(heading) for keyword in REF_HEADING_KEYWORDS)


def _line_reference_score(line: str) -> int:
    value = (line or "").strip()
    if not value:
        return 0

    score = 0
    if DOI_RE.search(value):
        score += 3
    if URL_RE.search(value):
        score += 2
    if YEAR_RE.search(value):
        score += 2
    if sum(1 for ch in value if ch in ".,;:()[]") >= 6:
        score += 2
    if CITATION_PREFIX_RE.match(value):
        score += 3
    if INITIALS_RE.search(value) or AUTHOR_RE.search(value):
        score += 2
    if len(value) < 18:
        score = max(0, score - 1)
    return score


def find_references_span(text: str, tail_window: float = REF_TAIL_WINDOW) -> Optional[Tuple[int, int]]:
    if not (text or "").strip():
        return None

    lines = _split_lines_with_offsets(text)
    for idx, (line, start, _end) in enumerate(lines):
        if _is_reference_heading(line):
            start_offset = lines[idx + 1][1] if idx + 1 < len(lines) else start
            return (start_offset, len(text))

    total_lines = len(lines)
    if total_lines == 0:
        return None

    tail_start_idx = max(0, int(total_lines * (1 - float(tail_window))))
    run_start: Optional[int] = None
    run_len = 0
    gaps = 0
    best_run_start: Optional[int] = None
    best_run_len = 0

    for idx in range(tail_start_idx, total_lines):
        if _line_reference_score(lines[idx][0]) >= REF_SCORE_THRESHOLD:
            if run_start is None:
                run_start = idx
                run_len = 0
                gaps = 0
            run_len += 1
            gaps = 0
            if run_len > best_run_len:
                best_run_len = run_len
                best_run_start = run_start
        elif run_start is not None:
            gaps += 1
            if gaps > 2:
                run_start = None
                run_len = 0
                gaps = 0

    if best_run_start is not None and best_run_len >= REF_MIN_RUN_LENGTH:
        return (lines[best_run_start][1], len(text))
    return None


def truncate_at(text: str, span: Optional[Tuple[int, int]]) -> str:
    if not span:
        return text
    start, _end = span
    start = max(0, min(int(start), len(text or "")))
    return (text or "")[:start].rstrip() + "\n"
