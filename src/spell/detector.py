import re
import unicodedata
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional, Set

from utils.config import (
    MAX_SUGGESTIONS,
    MIN_WORD_LENGTH,
    SKIP_TITLECASE_PROPER_NOUNS,
    SKIP_ALL_CAPS_WORDS,
    SKIP_STOPWORDS,
)

log = logging.getLogger(__name__)

try:
    import pythoncom
    import win32com.client

    WORD_AVAILABLE = True
except Exception:
    WORD_AVAILABLE = False


# ----------------------------
# Regex & constants
# ----------------------------
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

# Token VN (cho scan heuristic): cho phép dính dấu ASCII kiểu ` ~ ? '
VI_WORD_RE = re.compile(
    r"[A-Za-z" + re.escape(VIETNAMESE_CHARS) + r"]+(?:[`~?']*[A-Za-z" + re.escape(VIETNAMESE_CHARS) + r"]*)*[`~?']*"
)

# Token chữ cái (Unicode-aware), hỗ trợ nối bằng - hoặc '
WORD_RE = re.compile(
    r"[A-Za-z"
    + re.escape(VIETNAMESE_CHARS)
    + r"]+(?:[-'][A-Za-z"
    + re.escape(VIETNAMESE_CHARS)
    + r"]+)*"
)

# Token ASCII dài bất thường (hay gặp khi thiếu dấu/thiếu khoảng trắng)
ASCII_LOWER_WORD_RE = re.compile(r"\b[a-z]{10,}\b")

STOPWORDS = {
    "the", "a", "an", "in", "of", "to", "and", "or", "is", "are", "was", "were",
    "be", "been", "with", "for", "on", "at", "by", "from", "as", "it", "this",
    "that", "these", "those",
}

# Allowlist vài từ tiếng Anh dài để giảm false-positive
EN_LONG_ALLOWLIST = {
    "international",
    "technology",
    "technological",
    "development",
    "management",
    "institutional",
    "innovation",
    "environmental",
    "sustainability",
    "sustainable",
    "globalization",
    "empirical",
    "evidence",
    "relationship",
    "moderating",
    "information",
    "communication",
    "participation",
    "systematic",
    "literature",
    "university",
    "research",
    "journal",
    "business",
    "strategy",
    "economics",
}

# ----------------------------
# Bộ lọc: email, domain, url, code
# ----------------------------
EMAIL_RE = re.compile(r"\b\S+@\S+\.\S+\b")
DOMAIN_RE = re.compile(r"\b[a-z0-9-]+\.(edu|com|org|net|gov|vn|io|ai)\b", re.I)
URL_RE = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)

# ----------------------------
# Citation / proper-name filters
# ----------------------------
CITATION_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
ETAL_RE = re.compile(r"\bet\s+al\b", re.I)

# Ký tự "rất Việt" để phân biệt với tên nước ngoài có dấu (Sánchez, García...)
VN_CORE_CHARS = set("ăâêôơưđĂÂÊÔƠƯĐ")

EN_SUFFIX_RE = re.compile(
    r"(ing|tion|sion|ment|ness|ship|able|ible|less|ful|ous|ive|ize|ise|al|ary|ory|logy|graphy|scope|ware|wise|like|based|data)$",
    re.I,
)

def _looks_like_english_shape(word: str) -> bool:
    """Heuristic nhanh: token có dáng tiếng Anh (giảm bắn nhầm vi_glued_ascii)."""
    w = (word or "").lower()
    if not re.fullmatch(r"[a-z]{6,}", w):
        return False

    if EN_SUFFIX_RE.search(w):
        return True

    vowels = sum(1 for ch in w if ch in "aeiouy")
    if vowels >= max(2, len(w) // 4):
        return True

    return False

def _in_citation_parentheses(text: str, start: int, end: int, window: int = 80) -> bool:
    """Bỏ qua token nằm trong ngoặc (...) có năm (citation author-year)."""
    left = max(0, start - window)
    right = min(len(text), end + window)
    ctx = text[left:right]

    lpar = ctx.rfind("(", 0, start - left)
    rpar = ctx.find(")", end - left)
    if lpar == -1 or rpar == -1 or rpar <= lpar:
        return False

    inside = ctx[lpar + 1 : rpar]
    return bool(CITATION_YEAR_RE.search(inside))


def _looks_like_foreign_proper_name_with_accents(word: str) -> bool:
    """Tên nước ngoài có dấu Latin nhưng không có ăâêôơưđ (vd: Sánchez, García)."""
    if not word or len(word) < 3:
        return False
    if not any(c in VIETNAMESE_CHARS for c in word):
        return False
    if any(c in VN_CORE_CHARS for c in word):
        return False
    return word[0].isupper()


# Token kiểu mã: có cả chữ và số (vd: GEMg31, FIBa21...)
CODELIKE_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+$")
_HYPHENS = set("---‒–—­")  # hyphen/dash variants + soft hyphen


def _adjacent_to_digit(text: str, start: int, end: int) -> bool:
    """True nếu token dính công thức/mã có số (vd: EuCl3, Tb3+, L8-BO)."""
    if start > 0 and text[start - 1].isdigit():
        return True
    if end < len(text) and text[end].isdigit():
        return True
    return False


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
    """Chuẩn hoá NFC + bỏ BOM/ZW để offset ổn định."""
    t = unicodedata.normalize("NFC", text or "")
    t = t.replace("\ufeff", "").replace("\u200b", "")
    return t


def _engine_unavailable(message: str) -> List[Dict]:
    return [
        Issue(
            id="unavailable",
            type="unavailable",
            offset=0,
            length=0,
            original="",
            suggestions=[],
            message=message,
        ).to_dict()
    ]


def _looks_like_sentence_start(text: str, idx: int) -> bool:
    """Ước lượng idx có phải đầu câu không (để không skip Titlecase ở đầu câu)."""
    if idx <= 0:
        return True
    j = idx - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0:
        return True
    return text[j] in ".!?\n"


def _has_vi_chars(s: str) -> bool:
    return any(c in VIETNAMESE_CHARS for c in s)


def _has_mixed_tone_marks(word: str) -> bool:
    """Có dấu ASCII kiểu ` ~ ? ' (nghi gõ nhầm Telex/VNI)."""
    ascii_tones = set("`~?'")
    return any(c in ascii_tones for c in word)


def _looks_like_vn_glued_ascii(word: str) -> bool:
    """Token ASCII thường (>=10), không nằm allowlist -> nghi VN thiếu dấu/dính từ."""
    if not ASCII_LOWER_WORD_RE.fullmatch(word or ""):
        return False
    wl = word.lower()
    if wl in EN_LONG_ALLOWLIST:
        return False
    return True


def _strip_diacritics(s: str) -> str:
    """Bỏ dấu (combining marks); giữ đ theo unicode normalize."""
    if not s:
        return s
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


def _has_repeated_run(word: str, run: int = 3) -> bool:
    """Nghi lỗi OCR: 1 ký tự lặp liên tiếp >= run."""
    if not word:
        return False
    w = word.lower()
    return bool(re.search(r"(.)\1{" + str(run - 1) + r",}", w))


def _is_nonsense_combination(word: str) -> bool:
    """Bắt các tổ hợp 'rác' (aaa, bcdfg, iiia...) để tô vàng cảnh báo."""
    if not word or len(word) < 2:
        return False

    w = word.lower()
    w_base = _strip_diacritics(w)
    if len(w_base) < 2:
        return False

    if len(set(w_base)) == 1:
        return True

    vowels = set("aeiouy")
    consonants = set("bcdfghjklmnpqrstvwxz")

    if all(c in consonants for c in w_base):
        return True

    if len(w_base) >= 3:
        char_counts = {}
        for c in w_base:
            char_counts[c] = char_counts.get(c, 0) + 1

        max_char = max(char_counts, key=char_counts.get)
        max_count = char_counts[max_char]

        if max_char in vowels and max_count >= len(w_base) * 0.7:
            other_chars = [c for c in char_counts if c != max_char]
            if len(other_chars) <= 2 and all(char_counts[c] <= 2 for c in other_chars):
                return True

    return False


def _is_hyphenation_fragment(text: str, start: int, end: int) -> bool:
    """Bỏ qua mảnh từ bị ngắt dòng bằng hyphen của nhà xuất bản."""
    if end < len(text) and text[end] in _HYPHENS:
        if end + 1 < len(text) and text[end + 1].isspace():
            return True

    if start >= 2 and text[start - 1].isspace() and text[start - 2] in _HYPHENS:
        if start >= 3 and text[start - 3].isalpha():
            return True

    return False


def _is_acronymish(word: str) -> bool:
    """Heuristic viết tắt khoa học (PSC, EIPAs, PSCs...)."""
    if not word:
        return False
    if len(word) <= 2 or len(word) > 16:
        return False

    if re.fullmatch(r"[A-Z]{2,}(s)?", word):
        return True
    if re.fullmatch(r"[A-Z]{2,}[a-z]{0,4}s?", word):
        return True
    if re.fullmatch(r"[a-z]?[A-Z]{2,}[a-zA-Z]*", word):
        return True

    return False


def _iter_hyphen_segments(token: str, base_offset: int) -> List[Tuple[int, int, str]]:
    """Tách token theo dash/hyphen, giữ offset chuẩn."""
    out: List[Tuple[int, int, str]] = []
    seg_start = 0
    for i, ch in enumerate(token):
        if ch in _HYPHENS:
            seg = token[seg_start:i]
            if seg:
                out.append((base_offset + seg_start, len(seg), seg))
            seg_start = i + 1
    if seg_start < len(token):
        seg = token[seg_start:]
        if seg:
            out.append((base_offset + seg_start, len(seg), seg))
    return out


ALL_CONSONANTS_RE = re.compile(r"^[bcdfghjklmnpqrstvwxz]+$", re.I)

# Một ít từ VN không dấu hay gặp (để tránh gửi Word COM)
VN_ASCII_COMMON = {
    "toan", "sinh", "trong", "moi", "quan", "he", "chuyen", "doi", "so", "viet",
    "nam", "kinh", "te", "quan", "ly", "doanh", "nghiep", "nghien", "cuu", "tai",
    "lieu", "tham", "khao", "tom", "tat", "tu", "khoa",
}

_VN_VALID_CODAS = ("c", "ch", "m", "n", "ng", "nh", "p", "t")
_VN_VOWEL_BASES = set("aeiouy")


def _ends_with_invalid_vn_coda(word: str) -> bool:
    """Sanity-check VN: chỉ áp dụng khi có dấu/đ; flag nếu coda không thể xảy ra."""
    if not word:
        return False
    w = word.lower()

    if not _has_vi_chars(w) and "đ" not in w and "Đ" not in word:
        return False

    if _looks_like_foreign_proper_name_with_accents(word):
        return False

    w = re.sub(r"[^\w" + re.escape(VIETNAMESE_CHARS) + r"]+$", "", w)
    if len(w) <= 2:
        return False

    for coda in sorted(_VN_VALID_CODAS, key=len, reverse=True):
        if w.endswith(coda):
            return False

    last = w[-1]
    base = _strip_diacritics(last)
    if base in _VN_VOWEL_BASES:
        return False

    return True


def _looks_like_english_word(w: str) -> bool:
    """Gate gửi Word COM: loại VN có dấu/đ, url/email/code, và token 'VN không dấu' phổ biến."""
    if not w:
        return False

    if _has_vi_chars(w) or "đ" in w.lower():
        return False

    if ALL_CONSONANTS_RE.fullmatch(w):
        return False

    if EMAIL_RE.search(w) or DOMAIN_RE.search(w) or URL_RE.search(w):
        return False

    if CODELIKE_RE.match(w):
        return False

    wl = w.lower()

    if w.islower() and len(wl) <= 3:
        return False

    if wl in VN_ASCII_COMMON:
        return False

    return True


def _build_line_vi_ratio_map(text: str) -> Tuple[List[int], List[float]]:
    """Tính tỷ lệ chữ VN theo từng dòng để giảm chi phí Word COM."""
    ends: List[int] = []
    ratios: List[float] = []

    start = 0
    for i, ch in enumerate(text):
        if ch == "\n":
            line = text[start:i]
            letters = [c for c in line if c.isalpha()]
            if letters:
                vi = sum(1 for c in letters if c in VIETNAMESE_CHARS or c.lower() == "đ")
                ratios.append(vi / max(1, len(letters)))
            else:
                ratios.append(0.0)
            ends.append(i)
            start = i + 1

    if start <= len(text):
        line = text[start:]
        letters = [c for c in line if c.isalpha()]
        if letters:
            vi = sum(1 for c in letters if c in VIETNAMESE_CHARS or c.lower() == "đ")
            ratios.append(vi / max(1, len(letters)))
        else:
            ratios.append(0.0)
        ends.append(len(text))

    return ends, ratios


def _is_vietnamese_line(pos: int, line_ends: List[int], line_vi_ratio: List[float], threshold: float = 0.25) -> bool:
    """True nếu dòng chứa pos có VN nhiều (ratio >= threshold)."""
    lo, hi = 0, len(line_ends) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if pos <= line_ends[mid]:
            hi = mid - 1
        else:
            lo = mid + 1
    idx = max(0, min(lo, len(line_vi_ratio) - 1))
    return line_vi_ratio[idx] >= threshold


def _is_vietnamese_context(text: str, start: int, end: int, window: int = 40, threshold: float = 0.22) -> bool:
    """Gate theo ngữ cảnh: quanh token có nhiều chữ VN -> coi là VN context."""
    left = max(0, start - window)
    right = min(len(text), end + window)
    ctx = text[left:right]
    letters = [c for c in ctx if c.isalpha()]
    if not letters:
        return False
    vi = sum(1 for c in letters if c in VIETNAMESE_CHARS or c.lower() == "đ")
    return (vi / max(1, len(letters))) >= threshold


def _batch_check_spelling_word_com(app, words: List[str]) -> Dict[str, Tuple[bool, List[str]]]:
    """Batch Word COM: word_lower -> (ok, suggestions)."""
    cache: Dict[str, Tuple[bool, List[str]]] = {}
    for w in words:
        ok = True
        suggs: List[str] = []
        try:
            ok = bool(app.CheckSpelling(w))
            if not ok:
                try:
                    sugg_obj = app.GetSpellingSuggestions(w)
                    if sugg_obj:
                        for i in range(1, min(MAX_SUGGESTIONS, sugg_obj.Count) + 1):
                            try:
                                suggs.append(str(sugg_obj.Item(i).Name))
                            except Exception:
                                continue
                except Exception:
                    pass
        except Exception:
            ok = True
        cache[w.lower()] = (ok, suggs)
    return cache


def _in_references(pos: int, ref_start: Optional[int]) -> bool:
    return ref_start is not None and pos >= ref_start


def _should_skip_word(word: str, text: str, match_pos: int) -> bool:
    """Skip token chắc chắn không cần spellcheck (url/email/citation/acronym/proper-name...)."""
    wl = word.lower()

    if EMAIL_RE.search(word) or DOMAIN_RE.search(word) or URL_RE.search(word) or CODELIKE_RE.match(word):
        return True

    if SKIP_STOPWORDS and wl in STOPWORDS:
        return True
    if len(word) <= 2 or len(word) < MIN_WORD_LENGTH:
        return True
    if wl in {"et", "al"}:
        return True
    if SKIP_ALL_CAPS_WORDS and word.isupper():
        return True

    if _is_acronymish(word):
        return True

    if SKIP_TITLECASE_PROPER_NOUNS and len(word) >= 3 and word[0].isupper() and word[1:].islower():
        if not _looks_like_sentence_start(text, match_pos):
            return True

    if _looks_like_foreign_proper_name_with_accents(word):
        return True

    if _in_citation_parentheses(text, match_pos, match_pos + len(word)):
        return True

    return False


# ----------------------------
# Token classifier (ưu tiên precision)
# ----------------------------
def _token_kind(word: str, start: int, end: int, text: str, english_ok: Optional[Set[str]]) -> str:
    """
    Phân loại token: vi / en / skip / unknown.
    Mục tiêu: chỉ chạy heuristic VN lên token không chắc là EN và không thuộc nhóm skip.
    """
    if not word:
        return "skip"

    wl = word.lower()

    if EMAIL_RE.search(word) or URL_RE.search(word) or DOMAIN_RE.search(word) or CODELIKE_RE.match(word):
        return "skip"
    if _in_citation_parentheses(text, start, end):
        return "skip"
    if word.isupper() or _is_acronymish(word):
        return "skip"
    if _looks_like_foreign_proper_name_with_accents(word):
        return "skip"
    if SKIP_TITLECASE_PROPER_NOUNS and len(word) >= 3 and word[0].isupper() and word[1:].islower():
        if not _looks_like_sentence_start(text, start):
            return "skip"

    if ("đ" in wl) or any(c in VN_CORE_CHARS for c in word) or _has_vi_chars(word):
        return "vi"

    if english_ok is not None and wl in english_ok:
        return "en"

    return "unknown"


# ----------------------------
# Vietnamese heuristic spellcheck (yellow)
# ----------------------------
def spellcheck_vietnamese(
    text: str,
    ref_span: Optional[Tuple[int, int]] = None,
    english_ok: Optional[Set[str]] = None,
) -> Dict:
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
        start, end = m.start(), m.end()

        kind = _token_kind(word, start, end, text, english_ok=english_ok)

        # EN hoặc nhóm skip thì thôi, không tô vàng theo heuristic VN
        if kind in ("en", "skip"):
            continue

        if len(word) <= 2:
            continue
        if any(c.isdigit() for c in word):
            continue

        if _has_mixed_tone_marks(word):
            clean_word = word
            for tone in "`~?.'":
                clean_word = clean_word.replace(tone, "")
            issues.append(
                Issue(
                    id=str(issue_id),
                    type="vi_mixed_tone_marks",
                    offset=start,
                    length=len(word),
                    original=word,
                    suggestions=[clean_word],
                    message="Nghi gõ nhầm dấu ASCII (Telex/VNI)",
                )
            )
            issue_id += 1
            continue

        if _has_repeated_run(word, run=4):
            issues.append(
                Issue(
                    id=str(issue_id),
                    type="vi_ocr_repeat",
                    offset=start,
                    length=len(word),
                    original=word,
                    suggestions=[],
                    message="Nghi lỗi OCR: ký tự lặp nhiều lần",
                )
            )
            issue_id += 1
            continue

        if _is_nonsense_combination(word):
            # tránh bắt nhầm nếu nằm trong email/url quanh đó
            if EMAIL_RE.search(text[max(0, start - 50):end + 50]) or \
               URL_RE.search(text[max(0, start - 50):end + 50]) or \
               DOMAIN_RE.search(text[max(0, start - 50):end + 50]):
                continue

            issues.append(
                Issue(
                    id=str(issue_id),
                    type="vi_nonsense_combination",
                    offset=start,
                    length=len(word),
                    original=word,
                    suggestions=[],
                    message="Nghi tổ hợp ký tự lạ/không hợp lệ",
                )
            )
            issue_id += 1
            continue

        # ASCII dài: chỉ raise khi ngữ cảnh xung quanh là VN
        if _looks_like_vn_glued_ascii(word):
            if _is_vietnamese_context(text, start, end, window=70, threshold=0.20):
                if not _looks_like_english_shape(word):
                    issues.append(
                        Issue(
                            id=str(issue_id),
                            type="vi_glued_ascii",
                            offset=start,
                            length=len(word),
                            original=word,
                            suggestions=[],
                            message="Nghi VN thiếu dấu/dính từ (heuristic)",
                        )
                    )
                    issue_id += 1
            continue

        # OCR: kiểu "BNgày"
        if len(word) >= 4 and word[0].isupper() and word[1].isupper() and word[2:].islower():
            issues.append(
                Issue(
                    id=str(issue_id),
                    type="vi_ocr_glued_cap",
                    offset=start,
                    length=len(word),
                    original=word,
                    suggestions=[],
                    message="Nghi lỗi OCR: chữ cái bị dính",
                )
            )
            issue_id += 1
            continue

        if _ends_with_invalid_vn_coda(word):
            issues.append(
                Issue(
                    id=str(issue_id),
                    type="vi_invalid_coda",
                    offset=start,
                    length=len(word),
                    original=word,
                    suggestions=[],
                    message="Nghi VN: phụ âm cuối không hợp lệ",
                )
            )
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

    line_ends, line_vi_ratio = _build_line_vi_ratio_map(text)

    if not WORD_AVAILABLE:
        vi_res = spellcheck_vietnamese(text, ref_span=ref_span, english_ok=None)
        return {
            "issues": vi_res.get("issues", []) + _engine_unavailable("Word COM không khả dụng (thiếu win32com/pythoncom)."),
            "total_words": total_words,
            "meta": {
                "en_errors": 0,
                "vi_suspects": len(vi_res.get("issues", [])),
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
            if _in_citation_parentheses(text, m.start(), m.end()):
                continue

            is_vn_line = _is_vietnamese_line(m.start(), line_ends, line_vi_ratio)
            w = m.group(0)

            segments = (
                _iter_hyphen_segments(w, m.start())
                if any(h in w for h in _HYPHENS)
                else [(m.start(), len(w), w)]
            )

            for seg_start, seg_len, seg in segments:
                if not seg:
                    continue
                if _is_hyphenation_fragment(text, seg_start, seg_start + seg_len):
                    continue
                if _adjacent_to_digit(text, seg_start, seg_start + seg_len):
                    continue
                if _should_skip_word(seg, text, seg_start):
                    continue
                if not _looks_like_english_word(seg):
                    continue

                # VN line: bỏ token lowercase ngắn để tiết kiệm (thường là VN không dấu)
                if is_vn_line and seg.islower() and len(seg) <= 5:
                    continue

                wl = seg.lower()
                words_to_check.setdefault(wl, []).append((seg_start, seg_len, seg))

        log.debug(f"Found {len(words_to_check)} unique English words to spell check")

        issues_en: List[Issue] = []
        issue_id = 1
        english_ok: Set[str] = set()

        cache: Dict[str, Tuple[bool, List[str]]] = {}
        if words_to_check:
            cache = _batch_check_spelling_word_com(app, list(words_to_check.keys()))
            english_ok = {w for w, (ok, _) in cache.items() if ok}

            for wl, occs in words_to_check.items():
                ok, suggs = cache.get(wl, (True, []))
                if ok:
                    continue
                for (start, length, original) in occs:
                    issues_en.append(
                        Issue(
                            id=f"en_{issue_id}",
                            type="en_misspelling",
                            offset=start,
                            length=length,
                            original=original,
                            suggestions=suggs[:MAX_SUGGESTIONS],
                            message="English spelling error (Word COM)",
                        )
                    )
                    issue_id += 1

        vi_res = spellcheck_vietnamese(text, ref_span=ref_span, english_ok=english_ok)
        issues_vi = [
            Issue(
                id=it.get("id", ""),
                type=it.get("type", ""),
                offset=it.get("offset", 0),
                length=it.get("length", 0),
                original=it.get("original", ""),
                suggestions=it.get("suggestions", []),
                message=it.get("message", ""),
            )
            for it in vi_res.get("issues", [])
        ]

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

    except Exception as e:
        log.exception(f"Error in Word COM spellcheck: {e}")
        vi_res = spellcheck_vietnamese(text, ref_span=ref_span, english_ok=None)
        issues_en = _engine_unavailable(f"Word COM spellcheck failed: {e}")
        all_issues = vi_res.get("issues", []) + issues_en
        return {
            "issues": all_issues,
            "total_words": total_words,
            "meta": {
                "en_errors": 0,
                "vi_suspects": len(vi_res.get("issues", [])),
                "ref_span": ref_span,
            },
        }

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