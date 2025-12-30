import difflib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from docx import Document

# Optional Word COM (Windows only)
try:
    import pythoncom
    import win32com.client
    from plagiarism.checker import run_plagiarism_check

    WORD_COM_AVAILABLE = True
except ModuleNotFoundError:
    WORD_COM_AVAILABLE = False
    from src.plagiarism.checker import run_plagiarism_check
# Optional LanguageTool
try:
    import language_tool_python

    LANGUAGE_TOOL_AVAILABLE = True
except Exception:
    LANGUAGE_TOOL_AVAILABLE = False


WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*")
VI_WORD_RE = re.compile(r"[A-Za-z\u00c0-\u1ef9\u0110\u0111]+(?:[-'][A-Za-z\u00c0-\u1ef9\u0110\u0111]+)*")

# Vietnamese diacritics (precomposed + combining for OCR/PDF outputs)
VIETNAMESE_LETTERS = (
    "\u00e0\u00e1\u1ea1\u1ea3\u00e3\u00e2\u1ea7\u1ea5\u1ead\u1ea9\u1eab"
    "\u0103\u1eb1\u1eaf\u1eb7\u1eb3\u1eb5"
    "\u00e8\u00e9\u1eb9\u1ebb\u1ebd\u00ea\u1ec1\u1ebf\u1ec7\u1ec3\u1ec5"
    "\u00ec\u00ed\u1ecb\u1ec9\u0129"
    "\u00f2\u00f3\u1ecd\u1ecf\u00f5\u00f4\u1ed3\u1ed1\u1ed9\u1ed5\u1ed7"
    "\u01a1\u1edd\u1edb\u1ee3\u1edf\u1ee1"
    "\u00f9\u00fa\u1ee5\u1ee7\u0169\u01b0\u1eeb\u1ee9\u1ef1\u1eed\u1eef"
    "\u1ef3\u00fd\u1ef5\u1ef7\u1ef9\u0111"
    "\u00c0\u00c1\u1ea0\u1ea2\u00c3\u00c2\u1ea6\u1ea4\u1eac\u1ea8\u1eaa"
    "\u0102\u1eb0\u1eae\u1eb6\u1eb2\u1eb4"
    "\u00c8\u00c9\u1eb8\u1eba\u1ebc\u00ca\u1ec0\u1ebe\u1ec6\u1ec2\u1ec4"
    "\u00cc\u00cd\u1eca\u1ec8\u0128"
    "\u00d2\u00d3\u1ecc\u1ece\u00d5\u00d4\u1ed2\u1ed0\u1ed8\u1ed4\u1ed6"
    "\u01a0\u1edc\u1eda\u1ee2\u1ede\u1ee0"
    "\u00d9\u00da\u1ee4\u1ee6\u0168\u01af\u1eea\u1ee8\u1ef0\u1eec\u1eee"
    "\u1ef2\u00dd\u1ef4\u1ef6\u1ef8\u0110"
)
VIETNAMESE_CHARS = re.compile(f"[{VIETNAMESE_LETTERS}]")
VIETNAMESE_COMBINING = re.compile(r"[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff]")

# Cache for LanguageTool instances
_language_tool_cache: Dict[str, "language_tool_python.LanguageTool"] = {}
_vi_dict_words: Optional[Set[str]] = None
_vi_dict_unaccented: Optional[Set[str]] = None
_vi_dict_by_len: Dict[int, List[str]] = {}
DEFAULT_VI_DICT = Path(__file__).resolve().parent / "resources" / "hunspell_vi" / "vi_VN.dic"


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


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def _engine_unavailable(message: str) -> List[Dict]:
    issue = Issue(
        id="unavailable",
        type="unavailable",
        offset=0,
        length=0,
        original="",
        suggestions=[],
        message=message,
    )
    return [issue.to_dict()]


def _load_vi_dictionary(path: Optional[str] = None) -> bool:

    global _vi_dict_words, _vi_dict_by_len
    p = Path(path or os.getenv("VI_DICT_PATH") or DEFAULT_VI_DICT)
    if not p.exists():
        return False

    words: Set[str] = set()
    unaccented: Set[str] = set()
    with p.open(encoding="utf-8") as f:
        first = True
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if first and line.split()[0].isdigit():
                first = False
                continue
            first = False
            token = line.split("/", 1)[0].strip()
            if not token:
                continue
            token_norm = unicodedata.normalize("NFC", token).lower()
            words.add(token_norm)
            unaccented.add(_strip_accents(token_norm))

    _vi_dict_words = words
    _vi_dict_unaccented = unaccented
    buckets: Dict[int, List[str]] = {}
    for w in words:
        buckets.setdefault(len(w), []).append(w)
    _vi_dict_by_len = buckets
    return True


def _vi_suggestions(word: str, max_suggestions: int = 5) -> List[str]:
    if not _vi_dict_words:
        return []
    wl = len(word)
    candidates: List[str] = []
    for ln in range(wl - 1, wl + 3):
        candidates.extend(_vi_dict_by_len.get(ln, []))
    if not candidates:
        candidates = list(_vi_dict_words)
    return difflib.get_close_matches(word, candidates, n=max_suggestions, cutoff=0.7)


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")

_WS_RE = re.compile(r"\s+")
_PAGE_RE = re.compile(r"^\s*(?:page\s*)?\d+\s*(?:/\s*\d+)?\s*$", re.IGNORECASE)

NOISE_RE_LIST = [
    re.compile(r"^\s*issn\s*\d", re.IGNORECASE),
    re.compile(r"^\s*e-issn\s*\d", re.IGNORECASE),
    re.compile(r"^\s*số\s*\d+/\d{4}\s*$", re.IGNORECASE),
]

def _norm_line(s: str) -> str:
    s = (s or "").replace("\u00A0", " ")
    s = _WS_RE.sub(" ", s).strip()
    return s

def _collect_header_footer_lines(doc: Document) -> Set[str]:
    lines: Set[str] = set()
    for sec in doc.sections:
        for p in sec.header.paragraphs:
            t = _norm_line(p.text)
            if t:
                lines.add(t)
        for p in sec.footer.paragraphs:
            t = _norm_line(p.text)
            if t:
                lines.add(t)
    return lines

def _is_noise_line(t: str) -> bool:
    if not t:
        return True
    if _PAGE_RE.match(t):
        return True
    for rx in NOISE_RE_LIST:
        if rx.search(t):
            return True
    return False

def _norm_line(s: str) -> str:
    s = (s or "").replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _collect_header_footer_lines(doc: Document) -> Set[str]:
    lines: Set[str] = set()
    for sec in doc.sections:
        for p in sec.header.paragraphs:
            t = _norm_line(p.text)
            if t:
                lines.add(t)
        for p in sec.footer.paragraphs:
            t = _norm_line(p.text)
            if t:
                lines.add(t)
    return lines


_PAGE_RE = re.compile(r"^\s*(?:page|trang)?\s*\d+\s*(?:/\s*\d+)?\s*$", re.IGNORECASE)
_NOISE_RE_LIST = [
    re.compile(r"^\s*issn\s*\d", re.IGNORECASE),
    re.compile(r"^\s*e-issn\s*\d", re.IGNORECASE),
    re.compile(r"^\s*số\s*\d+/\d{4}\s*$", re.IGNORECASE),
]


def _is_noise_line(t: str) -> bool:
    if not t:
        return True
    if _PAGE_RE.match(t):
        return True
    for rx in _NOISE_RE_LIST:
        if rx.search(t):
            return True
    return False


def _iter_table_cell_lines(doc: Document):
    """Yield normalized lines from tables with per-cell dedupe to reduce duplication."""
    seen_cell_text: Set[str] = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_text = "\n".join((p.text or "") for p in cell.paragraphs)
                cell_text = _norm_line(cell_text)
                if not cell_text:
                    continue
                if cell_text in seen_cell_text:
                    continue
                seen_cell_text.add(cell_text)
                for line in cell_text.split("\n"):
                    t = _norm_line(line)
                    if t:
                        yield t


def extract_text_from_docx(path: str) -> str:
    """Extract text from DOCX body + tables (skip headers/footers by text match), with strict dedupe."""
    doc = Document(path)
    hf_lines = _collect_header_footer_lines(doc)

    parts: List[str] = []
    seen_lines: Set[str] = set()

    def push_line(t: str):
        if not t:
            return
        if t in hf_lines:
            return
        if _is_noise_line(t):
            return
        if t in seen_lines:
            return
        seen_lines.add(t)
        parts.append(t)

    # Body paragraphs
    for p in doc.paragraphs:
        push_line(_norm_line(p.text))

    # Tables
    for t in _iter_table_cell_lines(doc):
        push_line(t)

    return "\n".join(parts)



def detect_language(text: str) -> str:

    text = _normalize_text(text)

    if not text or not text.strip():
        return "en"

    vietnamese_count = len(VIETNAMESE_CHARS.findall(text)) + len(VIETNAMESE_COMBINING.findall(text))

    alpha_count = sum(1 for ch in text if ch.isalpha())
    alpha_count = max(alpha_count, 1)

    # English token count
    english_words = WORD_RE.findall(text)
    english_count = len(english_words)

    viet_ratio = vietnamese_count / alpha_count

    # Rules tuned to be less noisy than >10
    is_viet = (vietnamese_count >= 2 and viet_ratio >= 0.01) or vietnamese_count >= 8
    is_englishy = english_count >= 5  # small threshold

    if is_viet and is_englishy:
        return "mixed"
    if is_viet:
        return "vi"
    return "en"


def _contains_vietnamese_diacritic(s: str) -> bool:
    return bool(VIETNAMESE_CHARS.search(s) or VIETNAMESE_COMBINING.search(s))


def spellcheck_vietnamese(text: str, require_vietnamese_chars: bool = False) -> List[Dict]:
    """
    Vietnamese spellchecking via Hunspell dictionary (surface-form lookup + fuzzy suggestions).
    """
    text = _normalize_text(text)
    if _vi_dict_words is None:
        if not _load_vi_dictionary():
            return _engine_unavailable(
                f"Thieu tu dien Hunspell vi_VN.dic (expected at {DEFAULT_VI_DICT}); cung cap duong dan bang tham so path."
            )

    issues: List[Issue] = []
    idx = 1
    for m in VI_WORD_RE.finditer(text):
        w = m.group(0)
        wl = w.lower()

        # Bỏ qua token quá ngắn hoặc chứa dấu tiếng Anh/không phải chữ
        if len(wl) <= 1 or wl.isdigit():
            continue

        accentless = _strip_accents(wl)
        if require_vietnamese_chars and not (_contains_vietnamese_diacritic(wl) or (_vi_dict_unaccented and accentless in _vi_dict_unaccented)):
            continue

        if wl in _vi_dict_words:
            continue
        if _vi_dict_unaccented and accentless in _vi_dict_unaccented:
            # likely thiếu/ sai dấu
            issues.append(
                Issue(
                    id=str(idx),
                    type="spelling",
                    offset=m.start(),
                    length=m.end() - m.start(),
                    original=w,
                    suggestions=[],
                    message="Co the thieu/sai dau tieng Viet",
                )
            )
            idx += 1
            continue

        issues.append(
            Issue(
                id=str(idx),
                type="spelling",
                offset=m.start(),
                length=m.end() - m.start(),
                original=w,
                suggestions=[],
                message="Co the sai chinh ta",
            )
        )
        idx += 1

    return [i.to_dict() for i in issues]


def spellcheck_english_with_languagetool(text: str) -> List[Dict]:
    text = _normalize_text(text)

    if not LANGUAGE_TOOL_AVAILABLE and not WORD_COM_AVAILABLE:
        return _engine_unavailable("No LanguageTool or Microsoft Word COM engine available")
    if not LANGUAGE_TOOL_AVAILABLE:
        return spellcheck_english_with_word(text)

    try:
        if "en" not in _language_tool_cache:
            _language_tool_cache["en"] = language_tool_python.LanguageTool("en-US")

        tool = _language_tool_cache["en"]
        matches = tool.check(text)

        issues: List[Issue] = []
        idx = 1
        for match in matches:
            # keep mainly spelling noise down
            rule_id = getattr(match, "ruleId", "") or ""
            if not (rule_id.startswith("MORFOLOGIK_RULE") or "SPELLER" in rule_id):
                continue

            off = match.offset
            ln = match.errorLength
            original = text[off: off + ln]

            # Avoid flagging Vietnamese segments in mixed text
            if _contains_vietnamese_diacritic(original):
                continue

            suggestions = (match.replacements or [])[:5]
            issues.append(
                Issue(
                    id=str(idx),
                    type="spelling",
                    offset=off,
                    length=ln,
                    original=original,
                    suggestions=suggestions,
                    message=match.message or "Possible spelling mistake",
                )
            )
            idx += 1

        return [i.to_dict() for i in issues]

    except Exception as e:
        # Optional debug (don't crash)
        print(f"[LanguageTool] error -> fallback to Word COM: {e!r}", file=sys.stderr)
        return spellcheck_english_with_word(text)


def spellcheck_english_with_word(text: str) -> List[Dict]:
    text = _normalize_text(text)

    if not WORD_COM_AVAILABLE:
        return _engine_unavailable("Microsoft Word COM engine not available")

    pythoncom.CoInitialize()

    app = None
    base_doc = None

    try:
        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0  # wdAlertsNone
        base_doc = app.Documents.Add()

        cache: Dict[str, Tuple[bool, List[str]]] = {}
        issues: List[Issue] = []
        issue_id = 1

        STOP = {
            "the", "a", "an", "in", "of", "to", "and", "or", "is", "are", "was", "were",
            "be", "been", "with", "for", "on", "at", "by", "from", "as", "it", "this",
            "that", "these", "those"
        }

        for m in WORD_RE.finditer(text):
            w = m.group(0)
            wl = w.lower()

            # Skip short/stopwords/all-caps, and skip Vietnamese-ish tokens just in case
            if len(w) <= 2 or w.isupper() or wl in STOP or _contains_vietnamese_diacritic(w):
                continue

            if wl in cache:
                ok, sugg = cache[wl]
            else:
                ok = bool(app.CheckSpelling(w))
                sugg = []
                if not ok:
                    sugg_obj = app.GetSpellingSuggestions(w)
                    sugg = [s.Name for s in sugg_obj][:5]
                cache[wl] = (ok, sugg)

            if not ok:
                issues.append(
                    Issue(
                        id=str(issue_id),
                        type="spelling",
                        offset=m.start(),
                        length=m.end() - m.start(),
                        original=w,
                        suggestions=sugg,
                        message="Possible spelling mistake",
                    )
                )
                issue_id += 1

        return [i.to_dict() for i in issues]

    finally:
        try:
            if base_doc is not None:
                base_doc.Close(False)
        finally:
            if app is not None:
                app.Quit()
            pythoncom.CoUninitialize()


def spellcheck_auto(text: str) -> List[Dict]:
    normalized = _normalize_text(text)
    lang = detect_language(normalized)

    if lang == "vi":
        return spellcheck_vietnamese(normalized)

    if lang == "en":
        return spellcheck_english_with_languagetool(normalized)

    # mixed: chạy song song hai checker và gộp kết quả (loại trùng theo offset/length/original/type)
    vi_issues = spellcheck_vietnamese(normalized, require_vietnamese_chars=True)
    en_issues = spellcheck_english_with_languagetool(normalized)

    seen = set()
    merged: List[Dict] = []
    for src in (vi_issues, en_issues):
        for it in src:
            key = (it.get("offset"), it.get("length"), it.get("original"), it.get("type"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
    return merged


def close_language_tools() -> None:
    """Optional: close cached LanguageTool instances to free resources."""
    if not LANGUAGE_TOOL_AVAILABLE:
        return
    for k, tool in list(_language_tool_cache.items()):
        try:
            tool.close()
        except Exception:
            pass
        _language_tool_cache.pop(k, None)

    
def check_plagiarism_in_file(
    input_path: str,
    index_dir: str = "./src/plag_index",
    topk: int = 10,
    make_report: bool = True,
    report_dir: str = "./reports",
    use_lsh_filter: bool = True,
    use_fuzzy_match: bool = False,  # OFF for speed
    use_llm_verify: bool = False,    # OFF for speed
    batch_size: int = 64,
) -> Dict[str, Any]:
    try:
        res = run_plagiarism_check(
            input_path,
            index_dir=index_dir,
            topk=topk,
            use_lsh_filter=use_lsh_filter,
            use_fuzzy_match=use_fuzzy_match,
            use_llm_verify=use_llm_verify,
            batch_size=batch_size,
        )

        out: Dict[str, Any] = {
            "success": True,
            "overall_score": res.get("overall_score", 0.0),
            "total_chunks": res.get("total_chunks", 0),
            "total_words": res.get("total_words", 0),
            "findings": res.get("findings", []),
            "lsh_filtered": res.get("lsh_filtered", 0),
            "semantic_filtered": res.get("semantic_filtered", 0),
        }

        return out

    except Exception as e:
        return {"success": False, "error": str(e)}