import re
import logging
import unicodedata
from typing import List, Tuple, Optional

from utils.config import REF_TAIL_WINDOW

log = logging.getLogger(__name__)

# ----------------------------
# Hằng phát hiện phần tham khảo
# ----------------------------
REF_SCORE_THRESHOLD = 4
REF_MIN_RUN_LENGTH = 6

# ----------------------------
# Helpers
# ----------------------------
def _normalize_for_heading(s: str) -> str:
    """Chuẩn hoá dòng để so khớp heading ổn định."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\ufeff", "")  # BOM
    s = s.replace("\u200b", "")  # zero-width space
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _split_lines_with_offsets(text: str) -> List[Tuple[str, int, int]]:
    """Tách dòng kèm offset (ổn định cho \\n và \\r\\n)."""
    lines: List[Tuple[str, int, int]] = []
    i = 0
    for raw in text.splitlines(True):
        start = i
        i += len(raw)
        end = i
        lines.append((raw.rstrip("\r\n"), start, end))
    return lines


def _looks_like_heading(norm_line: str) -> bool:
    """Heuristic: dòng ngắn, ít dấu câu, không giống câu văn."""
    if not norm_line:
        return False
    if len(norm_line) > 70:
        return False
    if norm_line.endswith("."):
        return False

    punct = sum(1 for ch in norm_line if ch in ".,;!?")
    if punct >= 2:
        return False

    if len(norm_line.split()) > 8:
        return False

    return True


# ----------------------------
# Phát hiện heading (ổn định)
# ----------------------------
# Keyword heading "Tài liệu tham khảo/References" (có thể mất dấu).
REF_HEADING_KEYWORDS = {
    "references",
    "reference",
    "bibliography",
    "works cited",
    "works-cited",
    "tài liệu tham khảo",
    "tai lieu tham khao",
    "tài liệu tham khảo và trích dẫn",
    "tai lieu tham khao va trich dan",
    "tài liệu trích dẫn",
    "tai lieu trich dan",
}

# Hỗ trợ heading có số thứ tự: "6. References"
REF_HEADING_PREFIX_RE = re.compile(r"^\s*(\d{1,2}\s*[\.\)]\s*)?(.*)$")


def _is_reference_heading(line: str) -> bool:
    """True nếu dòng là heading phần tham khảo."""
    raw = line or ""
    norm = _normalize_for_heading(raw)
    norm = norm.strip(":;.-–— ").strip()

    m = REF_HEADING_PREFIX_RE.match(norm)
    norm2 = (m.group(2) or "").strip(":;.-–— ").strip() if m else norm

    if norm2 in REF_HEADING_KEYWORDS:
        return True

    for kw in REF_HEADING_KEYWORDS:
        if kw in norm2 and _looks_like_heading(norm2):
            return True

    return False


# ----------------------------
# Heuristic scoring (tail)
# ----------------------------
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DOI_RE = re.compile(r"\bdoi\s*:\s*\S+|\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

CITATION_PREFIX_RE = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}\.)\s+")
INITIALS_RE = re.compile(r"\b[A-Z]\.\s*,?\s*[A-Z]\.")
AUTHOR_RE = re.compile(r"\b[A-Z][a-z]+,\s*[A-Z]\.")


def _line_reference_score(line: str) -> int:
    """Chấm điểm dòng có “mùi” tài liệu tham khảo."""
    s = (line or "").strip()
    if not s:
        return 0

    score = 0

    if DOI_RE.search(s):
        score += 3
    if URL_RE.search(s):
        score += 2
    if YEAR_RE.search(s):
        score += 2

    punct = sum(1 for ch in s if ch in ".,;:()[]")
    if punct >= 6:
        score += 2

    if CITATION_PREFIX_RE.match(s):
        score += 3

    if INITIALS_RE.search(s) or AUTHOR_RE.search(s):
        score += 2

    if len(s) < 18:
        score = max(0, score - 1)

    return score


def find_references_span(text: str, tail_window: float = REF_TAIL_WINDOW) -> Optional[Tuple[int, int]]:
    """Tìm (start,end) phần tham khảo: ưu tiên heading, fallback quét tail."""
    if not (text or "").strip():
        return None

    lines = _split_lines_with_offsets(text)

    # 1) Heading rõ ràng
    for idx, (line, start, _end) in enumerate(lines):
        if _is_reference_heading(line):
            start_off = lines[idx + 1][1] if idx + 1 < len(lines) else start
            return (start_off, len(text))

    # 2) Quét đoạn cuối (run + cho phép gap nhỏ)
    n = len(lines)
    if n == 0:
        return None

    tail_start_idx = max(0, int(n * (1 - float(tail_window))))

    TH = REF_SCORE_THRESHOLD
    MIN_RUN = REF_MIN_RUN_LENGTH
    GAP_ALLOW = 2

    run_start: Optional[int] = None
    run_len = 0
    gaps = 0

    best_run_start: Optional[int] = None
    best_run_len = 0

    for i in range(tail_start_idx, n):
        line = lines[i][0]
        score = _line_reference_score(line)

        if score >= TH:
            if run_start is None:
                run_start = i
                run_len = 0
                gaps = 0
            run_len += 1
            gaps = 0

            if run_len > best_run_len:
                best_run_len = run_len
                best_run_start = run_start
        else:
            if run_start is not None:
                gaps += 1
                if gaps > GAP_ALLOW:
                    run_start = None
                    run_len = 0
                    gaps = 0

    if best_run_start is not None and best_run_len >= MIN_RUN:
        start_off = lines[best_run_start][1]
        return (start_off, len(text))


def truncate_at(text: str, span: Optional[Tuple[int, int]]) -> str:
    """Cắt phần từ span.start trở đi (loại tham khảo)."""
    if not span:
        return text
    a, _b = span
    a = max(0, min(int(a), len(text)))
    return text[:a].rstrip() + "\n"