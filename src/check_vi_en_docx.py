import re
import unicodedata
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

log = logging.getLogger(__name__)

# -----------------------------
# Word COM (Windows only)
# -----------------------------
try:
    import pythoncom
    import win32com.client
    WORD_COM_AVAILABLE = True
except Exception:
    WORD_COM_AVAILABLE = False

# -----------------------------
# Regex
# -----------------------------
WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")

REF_HEADING_RE = re.compile(
    r"(?im)^\s*(references|bibliography|works\s+cited|t?i\s*li?u\s*tham\s*kh?o|t?i\s*li?u\s*tham\s*kh?o\s*v?\s*tr?ch\s*d?n)\s*:?\s*$"
)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DOI_RE = re.compile(r"\bdoi\s*:\s*\S+|\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

CITATION_PREFIX_RE = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}\.)\s+")
INITIALS_RE = re.compile(r"\b[A-Z]\.\s*,?\s*[A-Z]\.")
AUTHOR_RE = re.compile(r"\b[A-Z][a-z]+,\s*[A-Z]\.")

STOPWORDS = {
    "the", "a", "an", "in", "of", "to", "and", "or", "is", "are", "was", "were",
    "be", "been", "with", "for", "on", "at", "by", "from", "as", "it", "this",
    "that", "these", "those"
}

# -----------------------------
# Types
# -----------------------------
@dataclass
class Issue:
    id: str
    type: str
    offset: int
    length: int
    original: str
    suggestions: List[str]
    message: str

    def to_dict(self) -> Dict:
        return asdict(self)

# -----------------------------
# Helpers
# -----------------------------
def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")

def _engine_unavailable(message: str) -> List[Dict]:
    return [Issue(
        id="unavailable",
        type="unavailable",
        offset=0,
        length=0,
        original="",
        suggestions=[],
        message=message,
    ).to_dict()]

def _split_lines_with_offsets(text: str) -> List[Tuple[str, int, int]]:
    lines: List[Tuple[str, int, int]] = []
    i = 0
    for raw in text.splitlines(True):
        start = i
        i += len(raw)
        end = i
        lines.append((raw.rstrip("\n"), start, end))
    return lines

def _line_reference_score(line: str) -> int:
    s = line.strip()
    if not s:
        return 0
    score = 0
    if YEAR_RE.search(s): score += 2
    if DOI_RE.search(s): score += 3
    if URL_RE.search(s): score += 2

    punct = sum(1 for ch in s if ch in ".,;:()[]")
    if punct >= 6: score += 2
    if CITATION_PREFIX_RE.match(s): score += 3
    if INITIALS_RE.search(s) or AUTHOR_RE.search(s): score += 2
    return score

def find_references_span(text: str, tail_window: float = 0.45) -> Optional[Tuple[int, int]]:
    if not text.strip():
        return None

    lines = _split_lines_with_offsets(text)

    for idx, (line, start, _end) in enumerate(lines):
        if REF_HEADING_RE.match(line.strip()):
            start_off = lines[idx + 1][1] if idx + 1 < len(lines) else start
            return (start_off, len(text))

    n = len(lines)
    tail_start_idx = max(0, int(n * (1 - tail_window)))

    best_run_start: Optional[int] = None
    run_len = 0
    best_run_len = 0

    TH = 4
    MIN_RUN = 6

    for i in range(tail_start_idx, n):
        score = _line_reference_score(lines[i][0])
        if score >= TH:
            if best_run_start is None:
                best_run_start = i
            run_len += 1
            best_run_len = max(best_run_len, run_len)
        else:
            if run_len >= MIN_RUN:
                break
            best_run_start = None
            run_len = 0

    if best_run_start is not None and best_run_len >= MIN_RUN:
        start_off = lines[best_run_start][1]
        return (start_off, len(text))

    return None

def truncate_at(text: str, span: Optional[Tuple[int, int]]) -> str:
    if not span:
        return text
    a, _b = span
    a = max(0, min(a, len(text)))
    return text[:a].rstrip() + "\n"

def _looks_like_sentence_start(text: str, idx: int) -> bool:
    # True if token is at beginning or right after .!? or newline
    if idx <= 0:
        return True
    j = idx - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0:
        return True
    return text[j] in ".!?\n"

# -----------------------------
# Spellcheck (Word COM)
# -----------------------------
def spellcheck_english_with_word(text: str) -> Dict:
    text = _normalize_text(text)
    original_text = text

    ref_span = find_references_span(text)
    if ref_span:
        text = truncate_at(text, ref_span)

    if not WORD_COM_AVAILABLE:
        return {
            "issues": _engine_unavailable("Microsoft Word COM engine not available"),
            "word_count": len(original_text.split()),
        }

    app = None
    doc = None
    coinit_ok = False

    try:
        pythoncom.CoInitialize()
        coinit_ok = True

        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0

        # Create a new document for spell checking
        doc = app.Documents.Add()

        cache: Dict[str, Tuple[bool, List[str]]] = {}
        issues: List[Issue] = []
        issue_id = 1

        for m in WORD_RE.finditer(text):
            w = m.group(0)
            wl = w.lower()

            if wl in STOPWORDS or len(w) <= 2 or w.isupper():
                continue
            if wl in {"et", "al"}:
                continue

            # Skip TitleCase proper nouns, but NOT at sentence start
            if len(w) >= 3 and w[0].isupper() and w[1:].islower():
                if not _looks_like_sentence_start(text, m.start()):
                    continue

            if wl in cache:
                ok, sugg = cache[wl]
            else:
                ok = bool(app.CheckSpelling(w))
                sugg = []
                if not ok:
                    try:
                        sugg_obj = app.GetSpellingSuggestions(w)
                        sugg = [s.Name for s in sugg_obj][:5]
                    except Exception:
                        sugg = []
                cache[wl] = (ok, sugg)

            if not ok:
                issues.append(Issue(
                    id=str(issue_id),
                    type="spelling",
                    offset=m.start(),
                    length=m.end() - m.start(),
                    original=w,
                    suggestions=sugg,
                    message="Possible spelling mistake",
                ))
                issue_id += 1

        return {
            "issues": [i.to_dict() for i in issues],
            "word_count": len(original_text.split()),
        }

    finally:
        try:
            if doc is not None:
                doc.Close(SaveChanges=False)
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        finally:
            if coinit_ok:
                pythoncom.CoUninitialize()

def spellcheck_auto(text: str) -> Dict:
    return spellcheck_english_with_word(_normalize_text(text))
