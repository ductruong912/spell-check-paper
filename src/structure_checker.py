from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# -----------------------------
# Text extraction
# -----------------------------

def extract_text_from_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise RuntimeError("Missing dependency: python-docx. Install: pip install python-docx") from e

    doc = Document(str(path))
    parts: List[str] = []
    for p in doc.paragraphs:
        if p.text:
            parts.append(p.text)
    return "\n".join(parts)


def extract_text_from_pdf(path: Path) -> str:
    """
    Tries multiple PDF extractors:
      1) PyMuPDF (fitz)
      2) pypdf
      3) pdfplumber
    """
    # 1) PyMuPDF
    try:
        import fitz  # type: ignore
        text_parts = []
        doc = fitz.open(str(path))
        for page in doc:
            text_parts.append(page.get_text("text"))
        doc.close()
        text = "\n".join(text_parts).strip()
        if text:
            return text
    except Exception:
        pass

    # 2) pypdf
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        text_parts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t:
                text_parts.append(t)
        text = "\n".join(text_parts).strip()
        if text:
            return text
    except Exception:
        pass

    # 3) pdfplumber
    try:
        import pdfplumber  # type: ignore
        text_parts = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    text_parts.append(t)
        text = "\n".join(text_parts).strip()
        if text:
            return text
    except Exception:
        pass

    raise RuntimeError(
        "Cannot extract text from PDF. Try installing one of: pymupdf, pypdf, pdfplumber.\n"
        "Example: pip install pymupdf"
    )


# -----------------------------
# Normalization helpers
# -----------------------------

_EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE)

def normalize_text(raw: str) -> str:
    if not raw:
        return ""
    s = unicodedata.normalize("NFC", raw)
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # Remove hyphenation at end of line: abc-\n def -> abcdef
    s = re.sub(r"(\w)\-\s*\n\s*(\w)", r"\1\2", s)

    # Reduce spaces
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)

    return s.strip()


def get_head(text: str, max_chars: int = 6000) -> str:
    return text[:max_chars]


def get_tail(text: str, max_chars: int = 12000) -> str:
    return text[-max_chars:] if len(text) > max_chars else text


# -----------------------------
# Language heuristics
# -----------------------------

VN_DIACRITICS_RE = re.compile(
    r"[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]",
    re.IGNORECASE
)
ASCII_LETTERS_RE = re.compile(r"[a-z]", re.IGNORECASE)

def is_mostly_english(s: str, min_len: int = 200) -> bool:
    t = re.sub(r"\s+", " ", s).strip()
    if len(t) < min_len:
        return False
    letters = len(re.findall(r"[A-Za-zÀ-ỹ]", t))
    if letters <= 0:
        return False
    ascii_letters = len(ASCII_LETTERS_RE.findall(t))
    diacritics = len(VN_DIACRITICS_RE.findall(t))
    ascii_ratio = ascii_letters / max(1, letters)
    dia_ratio = diacritics / max(1, letters)
    return ascii_ratio >= 0.80 and dia_ratio <= 0.01

def is_mostly_vietnamese(s: str, min_len: int = 200) -> bool:
    t = re.sub(r"\s+", " ", s).strip()
    if len(t) < min_len:
        return False
    letters = len(re.findall(r"[A-Za-zÀ-ỹ]", t))
    if letters <= 0:
        return False
    diacritics = len(VN_DIACRITICS_RE.findall(t))
    dia_ratio = diacritics / max(1, letters)
    # VI thường có dấu tương đối rõ
    return dia_ratio >= 0.04


# -----------------------------
# Patterns (config)
# -----------------------------

def build_patterns() -> Dict[str, List[re.Pattern]]:
    def rx(p: str) -> re.Pattern:
        return re.compile(p, re.IGNORECASE | re.UNICODE)

    return {
        "email": [rx(_EMAIL_RE.pattern)],

        "author_hint_vi": [
            rx(r"\btác giả\b"),
            rx(r"\btrường đại học\b|\bviện\b|\bkhoa\b"),
            rx(r"\bliên hệ\b|\bcorresponding author\b"),
            rx(r"\bemail\s*:\b"),
        ],

        # Keywords
        "keywords_vi": [rx(r"\btừ khóa\b|\btừ khoá\b")],
        "keywords_en": [rx(r"\bkeywords?\b")],

        # Sections
        "introduction": [rx(r"\bmở đầu\b|\bgiới thiệu\b|\bđặt vấn đề\b|\bintroduction\b")],
        "methods": [rx(r"\bphương pháp\b|\bvật liệu\b|\bmethodology\b|\bmaterials and methods\b|\bmethods\b")],

        "results": [rx(r"\bkết quả\b|\bresults?\b")],
        "discussion": [rx(r"\bthảo luận\b|\bdiscussion\b")],

        "conclusion": [rx(r"\bkết luận\b|\bconclusions?\b")],
        "appendix": [rx(r"\bphụ lục\b|\bappendix\b|\bappendices\b")],

        "contribution": [
            rx(r"\bđóng góp khoa học\b|\btuyên bố.*đóng góp\b|\bauthor contributions?\b|\bcontribution statement\b")
        ],
        "conflict_of_interest": [
            rx(r"\bmâu thuẫn lợi ích\b|\bxung đột lợi ích\b|\bconflict of interest\b|\bcompeting interests\b")
        ],
        "acknowledgements_funding": [
            rx(r"\blời cảm ơn\b|\backnowledg(e)?ments\b|\bfunding\b|\btài trợ\b")
        ],

        "references": [rx(r"\btài liệu tham khảo\b|\breferences\b|\bbibliography\b")],

        # Metadata-ish
        "received": [rx(r"\bngày nhận\b|\breceived\b")],
        "doi": [rx(r"\bdoi\b\s*[:：]")],
        "jel": [rx(r"\bjel\b")],
    }


# -----------------------------
# Title heuristics
# -----------------------------

def score_line_vi(line: str) -> float:
    l = line.strip()
    if len(l) < 12:
        return 0.0
    diacritics = len(VN_DIACRITICS_RE.findall(l))
    letters = len(re.findall(r"[a-zA-ZÀ-ỹ]", l))
    alpha = sum(1 for c in l if c.isalpha())
    upper = sum(1 for c in l if c.isalpha() and c.isupper())
    upper_ratio = upper / max(1, alpha)
    return (diacritics / max(1, letters)) * 2.0 + upper_ratio + (min(len(l), 120) / 200.0)

def score_line_en(line: str) -> float:
    l = line.strip()
    if len(l) < 12:
        return 0.0
    ascii_letters = len(ASCII_LETTERS_RE.findall(l))
    diacritics = len(VN_DIACRITICS_RE.findall(l))
    letters = len(re.findall(r"[a-zA-ZÀ-ỹ]", l))
    ascii_ratio = ascii_letters / max(1, letters)
    penalty = diacritics / max(1, letters)
    return ascii_ratio * 2.0 - penalty + (min(len(l), 120) / 220.0)

def detect_titles(text_norm: str) -> Tuple[bool, bool]:
    head = get_head(text_norm, 12000)
    lines = [ln.strip() for ln in head.split("\n") if ln.strip()]
    lines = lines[:300]

    best_vi = ("", 0.0)
    best_en = ("", 0.0)

    for ln in lines:
        low = ln.lower()
        if any(k in low for k in ["issn", "e-issn", "doi", "email", "ngày nhận", "jel", "mục lục", "page "]):
            continue
        if len(ln) > 220:
            continue

        s_vi = score_line_vi(ln)
        if s_vi > best_vi[1]:
            best_vi = (ln, s_vi)

        s_en = score_line_en(ln)
        if s_en > best_en[1]:
            best_en = (ln, s_en)

    has_vi = best_vi[1] >= 1.0 and len(best_vi[0]) >= 15
    has_en = best_en[1] >= 1.0 and len(best_en[0]) >= 15 and not VN_DIACRITICS_RE.search(best_en[0])

    return has_vi, has_en


# -----------------------------
# Focus main article (reduce TOC noise in PDF)
# -----------------------------

def focus_main_article(text: str) -> str:
    """
    PDF số tạp chí thường chứa MỤC LỤC + nhiều bài.
    Heuristic: tìm điểm bắt đầu bài dựa trên "Ngày nhận" / "DOI:" / "Email:" xuất hiện sớm nhất
    rồi cắt từ đó lùi lại một đoạn để giữ title + authors.
    """
    t = text
    low = t.lower()

    candidates = []
    for pat in [
        r"\bngày nhận\b",
        r"\breceived\b",
        r"\bdoi\b\s*[:：]",
        r"\bemail\s*[:：]",
    ]:
        m = re.search(pat, low, flags=re.IGNORECASE)
        if m:
            candidates.append(m.start())

    if not candidates:
        return t

    start = max(0, min(candidates) - 2500)
    return t[start:]


# -----------------------------
# Abstract heuristics (VI/EN even if missing labels)
# -----------------------------

def extract_block_between(text: str, start_idx: int, end_markers: List[re.Pattern], max_chars: int = 4000) -> str:
    chunk = text[start_idx:start_idx + max_chars]
    cut = None
    for p in end_markers:
        m = p.search(chunk)
        if m:
            cut = m.start() if cut is None else min(cut, m.start())
    if cut is not None:
        chunk = chunk[:cut]
    return chunk.strip()

def detect_abstract_vi(text: str, patterns: Dict[str, List[re.Pattern]]) -> bool:
    low = text.lower()

    # 1) Nếu có nhãn "Tóm tắt" thì ok
    if re.search(r"\btóm tắt\b|\btóm lược\b", low, flags=re.IGNORECASE):
        return True

    # 2) Heuristic: đoạn sau "Ngày nhận/Email" và trước "Từ khóa/JEL/DOI/Mở đầu/Đặt vấn đề/Introduction"
    m = re.search(r"\bngày nhận\b|\breceived\b|\bemail\s*[:：]", low, flags=re.IGNORECASE)
    if not m:
        # fallback: sau title (đầu file) ~ bỏ qua
        return False

    end_markers = [
        re.compile(r"\btừ khóa\b|\btừ khoá\b", re.IGNORECASE),
        re.compile(r"\bjel\b", re.IGNORECASE),
        re.compile(r"\bdoi\b\s*[:：]", re.IGNORECASE),
        re.compile(r"\bmở đầu\b|\bđặt vấn đề\b|\bgiới thiệu\b|\bintroduction\b", re.IGNORECASE),
    ]
    block = extract_block_between(text, m.end(), end_markers, max_chars=5000)
    return is_mostly_vietnamese(block, min_len=250)

def detect_abstract_en(text: str, patterns: Dict[str, List[re.Pattern]]) -> bool:
    low = text.lower()

    # 1) Có nhãn "Abstract/Summary" thì ưu tiên
    m = re.search(r"\babstract\b|\bsummary\b", low, flags=re.IGNORECASE)
    if m:
        end_markers = [
            re.compile(r"\bkeywords?\b", re.IGNORECASE),
            re.compile(r"\btừ khóa\b|\btừ khoá\b", re.IGNORECASE),
            re.compile(r"\bjel\b", re.IGNORECASE),
            re.compile(r"\bdoi\b\s*[:：]", re.IGNORECASE),
            re.compile(r"\bmở đầu\b|\bđặt vấn đề\b|\bgiới thiệu\b|\bintroduction\b", re.IGNORECASE),
            re.compile(r"\btài liệu tham khảo\b|\breferences\b|\bbibliography\b", re.IGNORECASE),
        ]
        block = extract_block_between(text, m.end(), end_markers, max_chars=6000)
        if is_mostly_english(block, min_len=200):
            return True

    # 2) Heuristic không nhãn: tìm đoạn tiếng Anh dài ở phần cuối (tail), trước references
    tail = get_tail(text, 16000)
    tail_low = tail.lower()

    # cắt tail trước references (nếu có)
    rm = re.search(r"\btài liệu tham khảo\b|\breferences\b|\bbibliography\b", tail_low, flags=re.IGNORECASE)
    if rm:
        tail = tail[:rm.start()]

    # split theo đoạn
    paras = [p.strip() for p in re.split(r"\n\s*\n", tail) if p.strip()]
    # ưu tiên đoạn có nhiều câu và giống abstract
    for p in reversed(paras[-20:]):  # check 20 đoạn cuối
        # tránh dính “random english sentence” trong body ngắn
        if is_mostly_english(p, min_len=220) and (p.count(".") + p.count(";")) >= 4:
            return True

    return False


# -----------------------------
# Reference analysis
# -----------------------------

def analyze_references(text: str) -> Tuple[int, int, float]:
    """
    Analyze references section for count and DOI presence.
    Returns: (total_count, doi_count, doi_percentage)
    """
    # Extract references section
    m = re.search(r"\btài liệu tham khảo\b|\breferences\b|\bbibliography\b", text, flags=re.IGNORECASE)
    if not m:
        return 0, 0, 0.0
    
    ref_text = text[m.end():]
    
    # Count references based on different citation styles
    # IEEE/Vancouver: [1], [2], ... or 1., 2., ...
    ieee_refs = re.findall(r"^\s*\[\s*\d+\s*\]\s+", ref_text, flags=re.MULTILINE)
    numbered_refs = re.findall(r"^\s*\d+\.\s+\S", ref_text, flags=re.MULTILINE)
    
    # APA: Author, A. (YYYY). ... - count by author-year pattern at line start
    apa_refs = re.findall(r"^\s*[A-ZÀ-Ỹ][a-zà-ỹ]+,\s*[A-Z]", ref_text, flags=re.MULTILINE)
    
    # Take the maximum count as the likely reference count
    ref_count = max(len(ieee_refs), len(numbered_refs), len(apa_refs))
    
    # Count DOIs in references section
    doi_patterns = [
        r"doi\.org/[^\s,;)]+",
        r"doi:\s*[^\s,;)]+",
        r"DOI:\s*[^\s,;)]+",
    ]
    
    doi_count = 0
    for pattern in doi_patterns:
        doi_count += len(re.findall(pattern, ref_text, flags=re.IGNORECASE))
    
    # Calculate percentage
    doi_percentage = (doi_count / ref_count * 100) if ref_count > 0 else 0.0
    
    return ref_count, doi_count, doi_percentage


# -----------------------------
# Reference style guess
# -----------------------------

def guess_reference_style(text: str) -> str:
    t = text

    # lấy vùng references nếu tìm thấy (ưu tiên)
    m = re.search(r"\btài liệu tham khảo\b|\breferences\b|\bbibliography\b", t, flags=re.IGNORECASE)
    if m:
        t = t[m.end():]
    else:
        # nếu không thấy heading, lấy tail vì references thường ở cuối
        t = get_tail(t, 12000)

    sample = get_head(t, 9000)

    # --- Đếm tín hiệu theo style ---

    # IEEE: [1] ...
    ieee_cnt = len(re.findall(r"^\s*\[\s*\d+\s*\]\s+", sample, flags=re.MULTILINE))

    # Vancouver: 1. ... (đánh số) - nhưng phải có nhiều dòng như vậy liên tiếp mới đáng tin
    vanc_cnt = len(re.findall(r"^\s*\d+\.\s+\S", sample, flags=re.MULTILINE))

    # APA: Author, A. (YYYY). ...  + nhiều (YYYY)
    apa_author_year = len(re.findall(r"[A-ZÀ-Ỹ][a-zà-ỹ]+,\s*[A-Z]\.\s*\(\s*\d{4}\s*\)", sample))
    apa_year = len(re.findall(r"\(\s*\d{4}\s*\)", sample))
    amp_cnt = len(re.findall(r"\b&\b", sample))
    doi_cnt = len(re.findall(r"doi\.org/\S+", sample, flags=re.IGNORECASE))
    retrieved_cnt = len(re.findall(r"\bretrieved from\b", sample, flags=re.IGNORECASE))

    # Chicago (tín hiệu yếu): ibid / op. cit.
    if re.search(r"\bibid\.|\bop\. cit\.", sample, flags=re.IGNORECASE):
        return "Chicago"

    # --- Quyết định theo độ tin cậy ---
    # 1) IEEE nếu thấy đủ nhiều
    if ieee_cnt >= 3:
        return "IEEE"

    # 2) APA nếu có dạng tác giả-năm rõ hoặc mật độ (YYYY) cao
    # (với bài của bạn có rất nhiều "Author, A. (YYYY)." nên sẽ rơi vào đây)
    if apa_author_year >= 3 or (apa_year >= 10 and (amp_cnt >= 4 or doi_cnt >= 2 or retrieved_cnt >= 1)):
        return "APA"

    # 3) Vancouver chỉ khi có nhiều dòng đánh số và APA không áp đảo
    # tránh nhầm mục lục / số trang
    if vanc_cnt >= 8 and apa_year < 6:
        return "Vancouver"

    return "Không xác định"


# -----------------------------
# Administrative document detection
# -----------------------------

def is_administrative_document(text: str) -> bool:
    """
    Detect if document is administrative (thông tư, nghị định, quyết định, etc.)
    instead of a research paper.
    """
    text_lower = text.lower()
    head = get_head(text, 3000)
    head_lower = head.lower()
    
    # Strong indicators of administrative documents
    admin_patterns = [
        r"\bcăn cứ luật\b",
        r"\bcăn cứ nghị định\b",
        r"\bthủ tướng chính phủ\b",
        r"\bbộ trưởng\b.*\bquyết định\b",
        r"\bnghị định số\b",
        r"\bthông tư số\b",
        r"\bquyết định số\b",
        r"\bđiều \d+\b.*\bđiều \d+\b",  # Multiple "Điều 1, Điều 2..."
        r"\bchương [IVX\d]+\b",  # Chapter numbering
        r"\bnơi nhận\b.*\bcục\b",
        r"\bkhoản \d+\b.*\bkhoản \d+\b",
    ]
    
    admin_count = sum(1 for p in admin_patterns if re.search(p, head_lower, re.IGNORECASE))
    
    # If 3+ administrative patterns found, likely not a research paper
    if admin_count >= 3:
        return True
    
    # Check for legal structure markers
    has_dieu_structure = len(re.findall(r"\bđiều \d+", text_lower)) >= 5
    has_khoan_structure = len(re.findall(r"\bkhoản \d+", text_lower)) >= 5
    
    if has_dieu_structure or has_khoan_structure:
        return True
    
    return False


def is_likely_research_paper(text: str) -> Tuple[bool, str]:
    """
    Verify if document is likely a research paper before detailed checking.
    Returns: (is_paper, reason)
    """
    # First, reject administrative documents
    if is_administrative_document(text):
        return False, "Văn bản này có cấu trúc của văn bản hành chính (thông tư/nghị định/quyết định), không phải bài báo khoa học."
    
    text_lower = text.lower()
    
    # Core signatures of research papers
    has_abstract = bool(re.search(r"\btóm tắt\b|\babstract\b", text_lower))
    has_keywords = bool(re.search(r"\btừ khóa\b|\btừ khoá\b|\bkeywords?\b", text_lower))
    has_references = bool(re.search(r"\btài liệu tham khảo\b|\breferences\b|\bbibliography\b", text_lower))
    has_introduction = bool(re.search(r"\bmở đầu\b|\bgiới thiệu\b|\bđặt vấn đề\b|\bintroduction\b", text_lower))
    has_methods = bool(re.search(r"\bphương pháp\b|\bmethodology\b|\bmaterials and methods\b", text_lower))
    
    # Score system
    score = 0
    if has_abstract: score += 2
    if has_keywords: score += 2
    if has_references: score += 2
    if has_introduction: score += 1
    if has_methods: score += 1
    
    # Need at least 4 points to be considered a research paper
    # Typically: abstract + keywords + references = 6 points
    if score >= 4:
        return True, ""
    
    # Give helpful feedback
    missing = []
    if not has_abstract: missing.append("tóm tắt/abstract")
    if not has_keywords: missing.append("từ khóa/keywords")
    if not has_references: missing.append("tài liệu tham khảo/references")
    
    reason = f"Văn bản này thiếu các yếu tố cơ bản của bài báo khoa học: {', '.join(missing)}."
    return False, reason


# -----------------------------
# Core checks
# -----------------------------

def has_any(text: str, patterns: List[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)

def check_structure(raw_text: str) -> Dict[str, object]:
    raw = normalize_text(raw_text)
    # khoanh vùng để giảm nhiễu PDF (MỤC LỤC, nhiều bài)
    focused = focus_main_article(raw)
    
    # VALIDATE: Check if this is actually a research paper
    is_paper, reason = is_likely_research_paper(focused)
    if not is_paper:
        return {
            "Loại văn bản": "KHÔNG PHẢI BÀI BÁO KHOA HỌC",
            "Lý do": reason,
            "Hướng dẫn": "Tool này chỉ dùng để kiểm tra cấu trúc bài báo khoa học. Vui lòng upload file bài báo nghiên cứu có đầy đủ: tóm tắt, từ khóa, và tài liệu tham khảo."
        }

    patterns = build_patterns()
    # Titles from focused head
    title_vi_ok, title_en_ok = detect_titles(focused)

    head = get_head(focused, 9000)
    tail = get_tail(focused, 20000)

    # Author/contact: email anywhere + hint in head
    email_ok = has_any(focused, patterns["email"])
    author_hint_ok = has_any(head, patterns["author_hint_vi"]) or email_ok
    authors_ok = bool(author_hint_ok and email_ok)

    # Abstracts (label + heuristic)
    abstract_vi_ok = detect_abstract_vi(focused, patterns)
    abstract_en_ok = detect_abstract_en(focused, patterns)

    # Keywords
    keywords_vi_ok = has_any(focused, patterns["keywords_vi"])
    keywords_en_ok = has_any(focused, patterns["keywords_en"])

    # Sections
    intro_ok = has_any(focused, patterns["introduction"])
    methods_ok = has_any(focused, patterns["methods"])

    results_ok = has_any(focused, patterns["results"])
    discussion_ok = has_any(focused, patterns["discussion"])
    results_discussion_ok = results_ok and discussion_ok

    conclusion_ok = has_any(focused, patterns["conclusion"])
    appendix_ok = has_any(focused, patterns["appendix"])

    contribution_ok = has_any(focused, patterns["contribution"])
    coi_ok = has_any(focused, patterns["conflict_of_interest"])
    ack_ok = has_any(focused, patterns["acknowledgements_funding"])

    # References: ưu tiên tail
    references_ok = has_any(tail, patterns["references"]) or has_any(focused, patterns["references"])
    
    # Analyze references in detail
    ref_count, doi_count, doi_percentage = analyze_references(focused)
    ref_style = guess_reference_style(tail) if references_ok else "Không xác định"
    
    # Evaluate reference quality
    ref_count_ok = ref_count >= 10  # At least 10 references for scientific paper
    has_doi = doi_count > 0

    return {
        "Tiêu đề tiếng Việt *": title_vi_ok,
        "Tiêu đề tiếng Anh *": title_en_ok,

        "Tác giả / Nhóm tác giả *": authors_ok,
        "Thông tin liên hệ *": email_ok,

        "Tóm tắt tiếng Việt *": abstract_vi_ok,
        "Tóm tắt tiếng Anh *": abstract_en_ok,

        "Từ khóa tiếng Việt *": keywords_vi_ok,
        "Từ khóa tiếng Anh *": keywords_en_ok,

        "Giới thiệu / Đặt vấn đề *": intro_ok,
        "Vật liệu và/hoặc phương pháp nghiên cứu *": methods_ok,

        "Kết quả và thảo luận *": results_discussion_ok,
        "Kết luận *": conclusion_ok,

        "Phụ lục": appendix_ok,
        "Tuyên bố đóng góp khoa học": contribution_ok,
        "Cam kết mâu thuẫn lợi ích": coi_ok,
        "Lời cảm ơn / Tài trợ": ack_ok,

        "Tài liệu tham khảo *": references_ok,
        "Chuẩn tài liệu tham khảo (ước đoán) *": ref_style,

        "Số lượng trích dẫn *": ref_count,
        "Có DOI *": f"{doi_count}/{ref_count}" if ref_count > 0 else "0/0",
    }


# -----------------------------
# CLI
# -----------------------------

def load_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_text_from_docx(path)
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    raise ValueError(f"Unsupported file type: {suffix}. Use PDF or DOCX.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=str, help="Path to PDF/DOCX")
    ap.add_argument("--pretty", action="store_true", help="Pretty JSON output (indent=2)")
    ap.add_argument("--save", type=str, default="", help="Save JSON to file")
    ap.add_argument("--dump", type=str, default="", help="Dump focused text to file (debug extract)")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    raw = load_text(path)
    raw_norm = normalize_text(raw)
    focused = focus_main_article(raw_norm)

    if args.dump:
        Path(args.dump).write_text(focused, encoding="utf-8")

    result = check_structure(raw)

    out = json.dumps(result, ensure_ascii=False, indent=2 if (args.pretty or True) else None)
    print(out)

    if args.save:
        Path(args.save).write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
