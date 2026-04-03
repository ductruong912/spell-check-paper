import re
import unicodedata
import logging
from functools import lru_cache
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
    "methodology",
    "organizational",
    "entrepreneurship",
    "digitalization",
    "digitalisation",
    "transformational",
    "interdisciplinary",
    "multidisciplinary",
    "comparative",
    "quantitative",
    "qualitative",
    "longitudinal",
    "crosssectional",
    "determinants",
    "governance",
    "productivity",
    "performance",
    "competitive",
    "competitiveness",
    "collaboration",
    "coordination",
    "implementation",
    "optimization",
    "optimisation",
    "framework",
    "stakeholder",
    "socioeconomic",
    "microfinance",
    "cryptocurrency",
    "blockchain",
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


@lru_cache(maxsize=8)
def _get_repeated_run_re(run: int):
    safe_run = max(2, int(run or 2))
    return re.compile(rf"(.)\1{{{safe_run - 1},}}")


def _has_repeated_run(word: str, run: int = 3) -> bool:
    """Nghi lỗi OCR: 1 ký tự lặp liên tiếp >= run."""
    if not word:
        return False
    return bool(_get_repeated_run_re(run).search(word.lower()))


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
        # Tránh bắn nhầm EN consonant-cluster ngắn (ctrl, str, bldg...).
        if len(w_base) <= 4:
            return False
        if _has_repeated_run(w_base, run=3):
            return True
        return len(w_base) >= 7

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


VI_CONTEXT_WINDOW = 120
VI_CONTEXT_STRONG_THRESHOLD = 0.5
VI_CONTEXT_MIXED_THRESHOLD = 0.2


def _vi_ratio_around(text: str, pos: int, window: int = VI_CONTEXT_WINDOW) -> float:
    """Tỷ lệ VN chars trong vùng ±window quanh vị trí token."""
    left = max(0, pos - window)
    right = min(len(text), pos + window)
    ctx = text[left:right]
    letters = 0
    vi = 0
    for c in ctx:
        if not c.isalpha():
            continue
        letters += 1
        if c in VIETNAMESE_CHARS or c.lower() == "đ":
            vi += 1
    if letters == 0:
        return 0.0
    return vi / letters


def _context_band(text: str, start: int, end: int, window: int = VI_CONTEXT_WINDOW) -> str:
    """Phân loại ngữ cảnh token: vi_strong | mixed | en."""
    center = start + max(0, (end - start) // 2)
    ratio = _vi_ratio_around(text, center, window=window)
    if ratio >= VI_CONTEXT_STRONG_THRESHOLD:
        return "vi_strong"
    if ratio >= VI_CONTEXT_MIXED_THRESHOLD:
        return "mixed"
    return "en"


def _is_vietnamese_context(
    text: str,
    start: int,
    end: int,
    window: int = VI_CONTEXT_WINDOW,
    threshold: float = VI_CONTEXT_STRONG_THRESHOLD,
) -> bool:
    """True khi token nằm trong vùng VN mạnh (mặc định ratio >= 0.5)."""
    center = start + max(0, (end - start) // 2)
    return _vi_ratio_around(text, center, window=window) >= threshold


def _batch_check_spelling_word_com(app, words: List[str]) -> Dict[str, Tuple[bool, List[str]]]:
    """Batch Word COM qua 1 scratch doc + map lỗi theo range Start/End."""
    cache: Dict[str, Tuple[bool, List[str]]] = {}
    if not words:
        return cache

    unique_words: List[str] = []
    seen: Set[str] = set()
    for w in words:
        wl = (w or "").lower()
        if not wl or wl in seen:
            continue
        seen.add(wl)
        unique_words.append(w)

    if not unique_words:
        return cache

    scratch_ranges: List[Tuple[int, int, str]] = []
    cursor = 0
    for idx, w in enumerate(unique_words):
        wl = w.lower()
        start = cursor
        end = start + len(w)
        scratch_ranges.append((start, end, wl))
        cursor = end + (1 if idx < len(unique_words) - 1 else 0)

    proofing_ok = False
    misspelled: Set[str] = set()
    scratch_doc = None

    try:
        scratch_doc = app.Documents.Add()
        scratch_doc.Content.Text = "\r".join(unique_words)

        proof_errors = scratch_doc.Content.SpellingErrors
        proofing_ok = True

        scan_idx = 0
        for i in range(1, int(proof_errors.Count) + 1):
            try:
                err = proof_errors.Item(i)
                err_start = int(err.Start)
                err_end = int(err.End)
            except Exception:
                continue

            if err_end <= err_start:
                err_end = err_start + 1

            while scan_idx < len(scratch_ranges) and scratch_ranges[scan_idx][1] <= err_start:
                scan_idx += 1

            mapped = False
            probe = scan_idx
            while probe < len(scratch_ranges) and scratch_ranges[probe][0] < err_end:
                w_start, w_end, w_lower = scratch_ranges[probe]
                if w_end > err_start and w_start < err_end:
                    misspelled.add(w_lower)
                    mapped = True
                probe += 1

            if mapped:
                continue

            # Fallback nhẹ cho trường hợp range dính ký tự phân cách.
            if scan_idx < len(scratch_ranges):
                w_start, w_end, w_lower = scratch_ranges[scan_idx]
                if abs(w_start - err_start) <= 1 or abs(w_end - err_end) <= 1:
                    misspelled.add(w_lower)
                    continue

            if scan_idx > 0:
                _, w_end, w_lower = scratch_ranges[scan_idx - 1]
                if abs(err_start - w_end) <= 1:
                    misspelled.add(w_lower)

    except Exception as e:
        log.debug(f"ProofreadingErrors batch failed: {e}")
    finally:
        try:
            if scratch_doc is not None:
                scratch_doc.Close(SaveChanges=False)
        except Exception as e:
            log.debug(f"Error closing scratch proofing doc: {e}")

    if not proofing_ok:
        for w in unique_words:
            cache[w.lower()] = (True, [])
        return cache

    for w in unique_words:
        wl = w.lower()
        ok = wl not in misspelled
        suggs: List[str] = []

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

        cache[wl] = (ok, suggs)

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
def _classify_token_language(word: str, text: str, start: int, english_ok: Set[str]) -> str:
    """
    Phân loại token theo ngữ cảnh: vi | en | en_term | skip.
    en_term = thuật ngữ EN nằm trong vùng VN mạnh.
    """
    if not word:
        return "skip"

    end = start + len(word)
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

    if wl in english_ok:
        return "en"

    if _is_vietnamese_context(text, start, end):
        return "en_term"

    return "en"


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
    english_engine_available = english_ok is not None
    english_ok_set = english_ok or set()

    issues: List[Issue] = []
    issue_id = 1

    for m in VI_WORD_RE.finditer(text):
        if _in_references(m.start(), ref_start):
            continue

        word = m.group(0)
        start, end = m.start(), m.end()

        kind = _classify_token_language(word, text, start, english_ok=english_ok_set)
        band = _context_band(text, start, end)

        if kind == "skip":
            continue

        if english_engine_available:
            # en_term luôn check bằng EN engine, không chạy heuristic VN.
            if kind == "en_term":
                continue

            # Mixed context (0.2-0.5): cho phép chạy cả heuristic VN trên token EN.
            if kind == "en" and band != "mixed":
                continue
        else:
            # Không có EN engine: chỉ bỏ qua EN context thuần, còn mixed/VN context vẫn chạy heuristic.
            if kind == "en" and band == "en":
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
            if _context_band(text, start, end, window=70) in ("mixed", "vi_strong"):
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
def spellcheck_english_with_word(
    text: str,
    ref_span: Optional[Tuple[int, int]] = None,
    is_normalized: bool = False,
) -> Dict:
    from .reference_finder import find_references_span

    if not is_normalized:
        text = _normalize_text(text)
    total_words = len(text.split())

    if ref_span is None:
        ref_span = find_references_span(text)
    ref_start = ref_span[0] if ref_span else None

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
    coinit_ok = False

    try:
        pythoncom.CoInitialize()
        coinit_ok = True

        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0

        words_to_check: Dict[str, List[Tuple[int, int, str]]] = {}
        empty_english_ok: Set[str] = set()

        for m in WORD_RE.finditer(text):
            if _in_references(m.start(), ref_start):
                continue
            if _in_citation_parentheses(text, m.start(), m.end()):
                continue

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

                token_lang = _classify_token_language(seg, text, seg_start, english_ok=empty_english_ok)
                if token_lang in ("skip", "vi"):
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
            if app is not None:
                app.Quit()
        except Exception as e:
            log.debug(f"Error quitting Word app: {e}")
        if coinit_ok:
            try:
                pythoncom.CoUninitialize()
            except Exception as e:
                log.debug(f"Error in CoUninitialize: {e}")