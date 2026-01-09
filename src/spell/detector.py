import re
import unicodedata
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

from utils.config import (
    MAX_SUGGESTIONS,
    MIN_WORD_LENGTH,
    SKIP_TITLECASE_PROPER_NOUNS,
    SKIP_ALL_CAPS_WORDS,
    SKIP_STOPWORDS,
)

log = logging.getLogger(__name__)

# Word COM (Windows only)
try:
    import pythoncom
    import win32com.client

    WORD_COM_AVAILABLE = True
except Exception:
    WORD_COM_AVAILABLE = False

# ----------------------------
# Regex & constants
# ----------------------------
WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")

VIETNAMESE_CHARS = (
    "àáảãạăằắẳẵặâầấẩẫậ"
    "èéẻẽẹêềếểễệ"
    "ìíỉĩị"
    "òóỏõọôồốổỗộơờớởỡợ"
    "ùúủũụưừứửữự"
    "ỳýỷỹỵđ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬ"
    "ÈÉẺẼẸÊỀẾỂỄỆ"
    "ÌÍỈĨỊ"
    "ÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ"
    "ÙÚỦŨỤƯỪỨỬỮỰ"
    "ỲÝỶỸỴĐ"
)

# Vietnamese words (letters only) - for heuristic scan
VI_WORD_RE = re.compile(r"[A-Za-z" + re.escape(VIETNAMESE_CHARS) + r"]+")

# ASCII glued word candidate (very likely VN missing spaces/tones)
ASCII_LOWER_WORD_RE = re.compile(r"\b[a-z]{10,}\b")

STOPWORDS = {
    "the", "a", "an", "in", "of", "to", "and", "or", "is", "are", "was", "were",
    "be", "been", "with", "for", "on", "at", "by", "from", "as", "it", "this",
    "that", "these", "those"
}

# A tiny allowlist of common English long words to avoid false positives for vn_glued
EN_LONG_ALLOWLIST = {
    "international", "technology", "technological", "development", "management",
    "institutional", "innovation", "environmental", "sustainability", "sustainable",
    "globalization", "empirical", "evidence", "relationship", "moderating",
    "information", "communication", "participation", "systematic", "literature",
    "university", "research", "journal", "business", "strategy", "economics",
}

# ----------------------------
# NEW: filters to avoid VN-as-ASCII + codes/emails
# ----------------------------
EMAIL_RE = re.compile(r"\b\S+@\S+\.\S+\b")
DOMAIN_RE = re.compile(r"\b[a-z0-9-]+\.(edu|com|org|net|gov|vn|io|ai)\b", re.I)
URL_RE = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)

# letters+digits tokens often represent IDs/codes: FIBa21, GEMg31...
CODELIKE_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+$")

# garbage like "bdl" (all consonants)
ALL_CONSONANTS_RE = re.compile(r"^[bcdfghjklmnpqrstvwxz]+$", re.I)

VN_ASCII_COMMON = {
    "toan", "sinh", "trong", "moi", "quan", "he", "chuyen", "doi", "so", "viet", "nam",
    "kinh", "te", "quan", "ly", "doanh", "nghiep", "nghien", "cuu",
    "tai", "lieu", "tham", "khao", "tom", "tat", "tu", "khoa",
    "truong", "dai", "hoc", "tap", "chi", "khoa", "hoc",
    "xanh", "theo", "giai", "doan",
}

EN_VOWELS = set("aeiouy")


# ----------------------------
# Models
# ----------------------------
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


# ----------------------------
# Helpers
# ----------------------------
def _normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "")
    t = t.replace("\ufeff", "").replace("\u200b", "")
    return t


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


def _looks_like_sentence_start(text: str, idx: int) -> bool:
    if idx <= 0:
        return True
    j = idx - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0:
        return True
    return text[j] in ".!?\n"


def _should_skip_word(word: str, text: str, match_pos: int) -> bool:
    wl = word.lower()

    if SKIP_STOPWORDS and wl in STOPWORDS:
        return True
    if len(word) <= 2 or len(word) < MIN_WORD_LENGTH:
        return True
    if wl in {"et", "al"}:
        return True
    if SKIP_ALL_CAPS_WORDS and word.isupper():
        return True

    # Skip TitleCase proper nouns, but NOT at sentence start
    if SKIP_TITLECASE_PROPER_NOUNS and len(word) >= 3 and word[0].isupper() and word[1:].islower():
        if not _looks_like_sentence_start(text, match_pos):
            return True

    return False


def _has_vi_chars(s: str) -> bool:
    return any(c in VIETNAMESE_CHARS for c in s)


def _has_mixed_tone_marks(word: str) -> bool:
    ascii_tones = set("`~?.'")
    return any(c in ascii_tones for c in word)


def _looks_like_vn_glued_ascii(word: str) -> bool:
    if not ASCII_LOWER_WORD_RE.fullmatch(word or ""):
        return False
    if word in EN_LONG_ALLOWLIST:
        return False
    common_chunks = (
        "nghien", "cuu", "doanh", "nghiep", "kinhte", "quanly",
        "chuyen", "doiso", "vietnam", "tailieu", "thamkhao"
    )
    return any(ch in word for ch in common_chunks)


def _in_references(m_start: int, ref_start: Optional[int]) -> bool:
    return (ref_start is not None) and (m_start >= ref_start)


def _looks_like_english_word(w: str) -> bool:
    """
    Conservative English gate:
    - block emails/domains/urls
    - block codes (letters+digits)
    - block VN common ASCII tokens
    - require vowels
    - block all-consonant garbage
    """
    if not w:
        return False

    if EMAIL_RE.search(w) or DOMAIN_RE.search(w) or URL_RE.search(w):
        return False

    if CODELIKE_RE.match(w):
        return False

    wl = w.lower()

    # reject short lowercase tokens (very noisy in Vietnamese metadata)
    if w.islower() and len(wl) <= 3:
        return False

    if wl in VN_ASCII_COMMON:
        return False

    if not any(ch in EN_VOWELS for ch in wl):
        return False

    if ALL_CONSONANTS_RE.match(wl):
        return False

    return True


def _is_vietnamese_context(text: str, start: int, end: int, window: int = 40) -> bool:
    """
    If surrounding context has significant Vietnamese diacritics, treat as VN context.
    This blocks VN paragraphs containing occasional ASCII words (e.g., 'xanh', 'theo').
    """
    left = max(0, start - window)
    right = min(len(text), end + window)
    ctx = text[left:start] + text[end:right]

    vi = sum(1 for c in ctx if c in VIETNAMESE_CHARS)
    alpha = sum(1 for c in ctx if c.isalpha())
    if alpha == 0:
        return False

    return (vi / alpha) > 0.15


# ----------------------------
# Word COM batch cache
# ----------------------------
def _batch_check_spelling_word_com(app, words: List[str]) -> Dict[str, Tuple[bool, List[str]]]:
    results: Dict[str, Tuple[bool, List[str]]] = {}

    for word in words:
        wl = word.lower()
        if wl in results:
            continue

        try:
            ok = bool(app.CheckSpelling(word))
            sugg: List[str] = []
            if not ok:
                try:
                    sugg_obj = app.GetSpellingSuggestions(word)
                    sugg = [s.Name for s in sugg_obj][:MAX_SUGGESTIONS]
                except Exception as e:
                    log.debug(f"Error getting suggestions for '{word}': {e}")
            results[wl] = (ok, sugg)
        except Exception as e:
            log.warning(f"Error checking word '{word}': {e}")
            results[wl] = (True, [])  # fail-open

    return results


# ----------------------------
# Vietnamese heuristic (conservative)
# ----------------------------
def spellcheck_vietnamese(text: str, ref_span: Optional[Tuple[int, int]] = None) -> Dict:
    from .reference_finder import find_references_span

    text = _normalize_text(text)
    total_words = len(text.split())

    if ref_span is None:
        ref_span = find_references_span(text)
    ref_start = ref_span[0] if ref_span else None

    issues: List[Issue] = []
    issue_id = 1

    for m in VI_WORD_RE.finditer(text):
        if _in_references(m.start(), ref_start):
            continue

        word = m.group(0)
        if len(word) <= 2:
            continue
        if any(c.isdigit() for c in word):
            continue

        w_lower = word.lower()

        if _has_mixed_tone_marks(word):
            clean_word = word
            for tone in "`~?.'":
                clean_word = clean_word.replace(tone, "")
            suggestions = [clean_word] if clean_word != word else []
            issues.append(Issue(
                id=str(issue_id),
                type="vi_mixed_tone",
                offset=m.start(),
                length=len(word),
                original=word,
                suggestions=suggestions,
                message="Nghi ngờ lỗi gõ dấu (ký tự `~?.' lẫn trong từ)",
            ))
            issue_id += 1
            continue

        if not _has_vi_chars(word) and _looks_like_vn_glued_ascii(w_lower):
            issues.append(Issue(
                id=str(issue_id),
                type="vi_glued",
                offset=m.start(),
                length=len(word),
                original=word,
                suggestions=[],
                message="Nghi ngờ từ tiếng Việt bị dính/thiếu dấu (heuristic)",
            ))
            issue_id += 1
            continue

    log.info(f"Vietnamese suspected check completed: {len(issues)} issues found")
    return {
        "issues": [i.to_dict() for i in issues],
        "total_words": total_words,
    }


# ----------------------------
# Dual engine: English via Word COM + Vietnamese heuristic
# ----------------------------
def spellcheck_english_with_word(text: str, ref_span: Optional[Tuple[int, int]] = None) -> Dict:
    from .reference_finder import find_references_span

    text = _normalize_text(text)
    total_words = len(text.split())

    if ref_span is None:
        ref_span = find_references_span(text)
    ref_start = ref_span[0] if ref_span else None

    # Vietnamese heuristic (yellow)
    vi_res = spellcheck_vietnamese(text, ref_span=ref_span)
    issues_vi = [
        Issue(
            id=d["id"],
            type=d["type"],
            offset=d["offset"],
            length=d["length"],
            original=d["original"],
            suggestions=d.get("suggestions", []) or [],
            message=d["message"],
        )
        for d in vi_res.get("issues", [])
    ]

    issues_en: List[Issue] = []
    if not WORD_COM_AVAILABLE:
        log.warning("Microsoft Word COM engine not available - English spell check skipped")
        all_issues = [i.to_dict() for i in issues_vi] + _engine_unavailable("Microsoft Word engine không khả dụng")
        return {
            "issues": all_issues,
            "total_words": total_words,
            "meta": {
                "en_errors": 0,
                "vi_suspects": len(issues_vi),
                "ref_span": ref_span,
            },
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
        doc = app.Documents.Add()

        words_to_check: Dict[str, List[Tuple[int, int, str]]] = {}

        for m in WORD_RE.finditer(text):
            if _in_references(m.start(), ref_start):
                continue

            # ✅ NEW: if in VN context, skip Word COM
            if _is_vietnamese_context(text, m.start(), m.end()):
                continue

            w = m.group(0)

            if _has_vi_chars(w):
                continue

            if _should_skip_word(w, text, m.start()):
                continue

            # ✅ CRITICAL gate
            if not _looks_like_english_word(w):
                continue

            wl = w.lower()
            words_to_check.setdefault(wl, []).append((m.start(), m.end() - m.start(), w))

        log.debug(f"Found {len(words_to_check)} unique English words to spell check")

        if words_to_check:
            cache = _batch_check_spelling_word_com(app, list(words_to_check.keys()))
            issue_id = len(issues_vi) + 1

            for wl, positions in words_to_check.items():
                ok, sugg = cache.get(wl, (True, []))
                if not ok:
                    for offset, length, original in positions:
                        issues_en.append(Issue(
                            id=str(issue_id),
                            type="en_spelling",
                            offset=offset,
                            length=length,
                            original=original,
                            suggestions=sugg,
                            message="Lỗi chính tả tiếng Anh (Word)",
                        ))
                        issue_id += 1

    except Exception as e:
        log.error(f"Word COM spell check error: {e}", exc_info=True)
    finally:
        try:
            if doc is not None:
                doc.Close(SaveChanges=False)
        except Exception as e:
            log.debug(f"Error closing Word document: {e}")
        try:
            if app is not None:
                app.Quit()
        except Exception as e:
            log.debug(f"Error quitting Word app: {e}")
        if coinit_ok:
            try:
                pythoncom.CoUninitialize()
            except Exception as e:
                log.debug(f"Error in CoUninitialize: {e}")

    all_issues = [i.to_dict() for i in issues_vi] + [i.to_dict() for i in issues_en]
    log.info(
        f"Dual spellcheck done: EN={len(issues_en)} (red), "
        f"VI_suspects={len(issues_vi)} (yellow), ref_span={ref_span}"
    )

    return {
        "issues": all_issues,
        "total_words": total_words,
        "meta": {
            "en_errors": len(issues_en),
            "vi_suspects": len(issues_vi),
            "ref_span": ref_span,
        },
    }
