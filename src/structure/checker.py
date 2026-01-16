# checker.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.config import DEFAULT_LLM_MODEL, DEFAULT_MIN_CONFIDENCE

from .parser import DocPara, extract_docx_paragraphs, split_by_structure
from .classifier import llm_classify_document_batch, guess_references_style

logger = logging.getLogger("structure_checker")


# ─────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────
@dataclass
class SectionHit:
    status: str  # "ok" | "missing"
    evidence: str = ""
    llm_verified: bool = False
    llm_confidence: float = 0.0
    llm_label: str = ""
    notes: str = ""
    references_style: str = ""


@dataclass
class Report:
    file: str
    ok: bool
    sections: Dict[str, SectionHit]
    notes: List[str]


# ─────────────────────────────────────────
# Targets / Required
# ─────────────────────────────────────────
TARGETS = [
    ("title_vi", "Tiêu đề tiếng Việt"),
    ("title_en", "Tiêu đề tiếng Anh"),
    ("authors", "Tác giả / Nhóm tác giả và thông tin liên hệ"),
    ("abstract_vi", "Tóm tắt tiếng Việt"),
    ("abstract_en", "Tóm tắt tiếng Anh"),
    ("keywords_vi", "Từ khóa tiếng Việt"),
    ("keywords_en", "Từ khóa tiếng Anh"),
    ("introduction", "Giới thiệu / Đặt vấn đề"),
    ("methods", "Vật liệu và/hoặc phương pháp nghiên cứu"),
    ("results", "Kết quả và thảo luận"),
    ("conclusion", "Kết luận"),
    ("references", "Tài liệu tham khảo: APA, IEEE, Chicago, Vancouver"),
    ("appendix", "Phụ lục"),
    ("contributions", "Tuyên bố về đóng góp khoa học"),
    ("conflict_of_interest", "Cam kết về mâu thuẫn lợi ích"),
    ("acknowledgements", "Lời cảm ơn"),
]

REQUIRED: Dict[str, bool] = {k: False for k, _ in TARGETS}
for _k in [
    "title_vi",
    "title_en",
    "authors",
    "abstract_vi",
    "abstract_en",
    "keywords_vi",
    "keywords_en",
    "introduction",
    "methods",
    "results",
    "conclusion",
    "references",
]:
    REQUIRED[_k] = True


# ─────────────────────────────────────────
# Regex anchors / headings
# ─────────────────────────────────────────
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_RE_KW_VI = re.compile(r"(^|\n)\s*Từ\s*khóa\b\s*[:：]?", flags=re.IGNORECASE)
_RE_KW_EN = re.compile(r"(^|\n)\s*Keywords\b\s*[:：]?", flags=re.IGNORECASE)

_RE_ABS_VI_ANCHOR = re.compile(r"(^|\n)\s*Tóm\s*tắt\b\s*[:：]?", flags=re.IGNORECASE)
_RE_ABS_EN_ANCHOR = re.compile(r"(^|\n)\s*Abstract\b\s*[:：]?", flags=re.IGNORECASE)
_RE_RECEIVED = re.compile(r"(Ngày\s*nhận\s*:|Received\s*:|Available\s*online)", flags=re.IGNORECASE)

_RE_H_INTRO = re.compile(r"\b(mở\s*đầu|giới\s*thiệu|đặt\s*vấn\s*đề|introduction)\b", re.IGNORECASE)
_RE_H_METHODS = re.compile(
    r"\b("
    r"phương\s*pháp|vật\s*liệu|đối\s*tượng\s*và\s*phương\s*pháp|"
    r"materials?\s*(and\s*methods?)?|methods?|methodology|"
    r"experimental(\s*section)?|experiments?|procedures?"
    r")\b",
    re.IGNORECASE,
)
_RE_H_RESULTS = re.compile(r"\b(kết\s*quả|thảo\s*luận|results?|discussion)\b", re.IGNORECASE)
_RE_H_CONCL = re.compile(r"\b(kết\s*luận|conclusion)\b", re.IGNORECASE)
_RE_H_REFS = re.compile(r"\b(tài\s*liệu\s*tham\s*khảo|references|bibliography)\b", re.IGNORECASE)

_RE_H_ACK = re.compile(r"\b(lời\s*cảm\s*ơn|acknowledg(e)?ments?)\b", re.IGNORECASE)
_RE_H_COI = re.compile(
    r"\b("
    r"mâu\s*thuẫn\s*lợi\s*ích|xung\s*đột\s*lợi\s*ích|"
    r"conflict\s*of\s*interest|competing\s*interests?|declaration\s*of\s*competing\s*interest"
    r")\b",
    re.IGNORECASE,
)
_RE_H_CONTRIB = re.compile(r"\b(đóng\s*góp|contributions?|credit\s*authorship)\b", re.IGNORECASE)
_RE_H_APPX = re.compile(r"\b(phụ\s*lục|appendix|supplementary\s*data)\b", re.IGNORECASE)

# English abstract sometimes uses "Summary"
_RE_H_ABS_EN = re.compile(r"^\s*(abstract|summary)\b", re.IGNORECASE)

# Vietnamese diacritics heuristic
_VI_DIACRITICS = re.compile(
    r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩị"
    r"óòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
    re.IGNORECASE,
)

_RE_AFFILIATION = re.compile(
    r"\b(trường|đại\s*học|university|institute|faculty|khoa|department|viện)\b",
    re.IGNORECASE,
)

# Typical metadata headings that are NOT titles
_META_HEADINGS = {
    "ARTICLEINFO",
    "HIGHLIGHTS",
    "GRAPHICALABSTRACT",
    "ABSTRACT",
    "KEYWORDS",
    "TOMTAT",
    "TUKHOA",
    "SUMMARY",
    "CORRESPONDINGAUTHOR",
    "RECEIVED",
    "AVAILABLEONLINE",
    "DOI",
    "JEL",
    "CONTENTS",
    "MUCLUC",
}


# ─────────────────────────────────────────
# Small utilities
# ─────────────────────────────────────────
def _norm_ws(s: str) -> str:
    return re.sub(r"[ \t]+", " ", (s or "").strip())


def _collapse_spaced_caps_heading(line: str) -> str:
    """
    Collapse "A B S T R A C T" => "ABSTRACT" (and similar).
    Return uppercased, space-less token if it looks like spaced caps.
    """
    s = _norm_ws(line)
    if not s:
        return ""
    # spaced caps: "A B C" (at least 3 letters)
    if re.fullmatch(r"(?:[A-Z]\s+){2,}[A-Z]", s):
        return s.replace(" ", "").upper()
    # also handle "A  B  S" multiple spaces
    if re.fullmatch(r"(?:[A-Z]\s+){2,}[A-Z]\s*", re.sub(r"\s+", " ", s)):
        return re.sub(r"\s+", "", s).upper()
    # a normal heading: remove spaces/punct for metadata comparison
    return re.sub(r"[^A-Za-z0-9À-ỹ]+", "", s).upper()


def _english_ratio(text: str) -> float:
    """
    Rough ratio of ASCII letters among all letters (including Vietnamese).
    1.0 => fully English-like; 0.0 => no letters.
    """
    t = text or ""
    all_letters = re.findall(r"[A-Za-zÀ-ỹ]", t)
    if not all_letters:
        return 0.0
    en_letters = re.findall(r"[A-Za-z]", t)
    return len(en_letters) / max(1, len(all_letters))


def _mark(
    hits: Dict[str, SectionHit],
    key: str,
    evidence: str,
    note: str = "",
    llm_verified: bool = False,
    conf: float = 0.0,
    llm_label: str = "",
) -> None:
    h = hits.get(key)
    if not h:
        hits[key] = SectionHit(status="ok", evidence=evidence, notes=note, llm_verified=llm_verified, llm_confidence=conf, llm_label=llm_label)
        return
    h.status = "ok"
    h.evidence = evidence
    if note:
        h.notes = note
    if llm_verified:
        h.llm_verified = True
        h.llm_confidence = conf
        h.llm_label = llm_label


def _tail_text(paras: List[DocPara], start_ratio: float = 0.70) -> str:
    if not paras:
        return ""
    start = max(0, int(len(paras) * start_ratio))
    buf: List[str] = []
    for p in paras[start:]:
        s = (p.text or "").strip()
        if s:
            buf.append(s)
    return _norm_ws("\n".join(buf))


def _is_toc_line(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    if re.search(r"\b(mục\s*lục|contents)\b", t, re.IGNORECASE):
        return True
    # dot leaders often in TOC
    if re.search(r"\.{4,}", t) and re.search(r"\d", t):
        return True
    return False


# ─────────────────────────────────────────
# Body start detection
# ─────────────────────────────────────────
def _find_body_start_idx(paras: List[DocPara]) -> int:
    """
    Find boundary from frontmatter to main body.
    Priority: explicit intro heading, numbered heading, methods/results/conclusion short heading.
    Fallback: 20% of document.
    """
    texts = [(i, (p.text or "").strip()) for i, p in enumerate(paras)]

    # 1) intro
    for i, t in texts[:500]:
        if not t or _is_toc_line(t):
            continue
        h = _collapse_spaced_caps_heading(t)
        if _RE_H_INTRO.search(t) and len(t.split()) <= 12:
            return i
        if _RE_H_INTRO.search(h) and len(h.split()) <= 12:
            return i

    # 2) numbered heading "1.", "1.1", "I.", etc.
    re_num = re.compile(r"^\s*((\d+(\.\d+)*)|[IVXLC]+)\s*[\).\:-]\s+\S+")
    for i, t in texts[:800]:
        if not t or _is_toc_line(t):
            continue
        if re_num.match(t) and i >= 3:
            return i

    # 3) methods/results/conclusion (rare but some templates start at methods)
    for i, t in texts[:800]:
        if not t or _is_toc_line(t):
            continue
        h = _collapse_spaced_caps_heading(t)
        if (_RE_H_METHODS.search(t) or _RE_H_RESULTS.search(t) or _RE_H_CONCL.search(t)) and len(t.split()) <= 12:
            return i
        if (_RE_H_METHODS.search(h) or _RE_H_RESULTS.search(h) or _RE_H_CONCL.search(h)) and len(h.split()) <= 12:
            return i

    return max(0, int(len(paras) * 0.20))


# ─────────────────────────────────────────
# Frontmatter windowing (IMPORTANT for your bug cases)
# ─────────────────────────────────────────
def _frontmatter_window(front_lines: List[str]) -> List[str]:
    """
    Narrow down a 'reliable' frontmatter region to avoid false positives from:
    - journal headers
    - TOC
    - random metadata

    Anchor preference: email / received / DOI.
    """
    if not front_lines:
        return []
    anchor = None
    for i, l in enumerate(front_lines[:2500]):
        if _RE_EMAIL.search(l) or _RE_RECEIVED.search(l) or re.search(r"\bDOI\b", l, re.IGNORECASE):
            anchor = i
            break
    if anchor is None:
        # best-effort: still keep a reasonably small head
        return front_lines[:220]
    start = max(0, anchor - 50)
    end = min(len(front_lines), anchor + 260)
    return front_lines[start:end]


# ─────────────────────────────────────────
# Title / Keywords / Abstract detection
# ─────────────────────────────────────────
def _detect_titles(front_lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Fix false-positive: DO NOT treat abstract opening as title.
    Rule: if an email appears early, title must be ABOVE the first email line.
    Also block typical abstract starters like "Bài viết..." / "This study...".
    """
    if not front_lines:
        return None, None

    # stop early when hitting anchors
    stop_idx = len(front_lines)
    for i, l in enumerate(front_lines[:120]):
        if _is_toc_line(l):
            stop_idx = i
            break
        if re.search(
            r"(từ\s*khóa|keywords|tóm\s*tắt|abstract|summary|article\s*info|received|available\s*online|jel|doi|highlights|graphical)",
            l,
            re.IGNORECASE,
        ):
            stop_idx = i
            break

    head = [l.strip() for l in front_lines[:stop_idx] if (l or "").strip()]
    head = head[:40]

    # NEW: if email exists, only consider lines BEFORE first email as title candidates
    for i, l in enumerate(head):
        if _RE_EMAIL.search(l):
            head = head[:i]
            break

    def _is_bad_title_line(s: str) -> bool:
        if _RE_AFFILIATION.search(s):
            # line cơ quan thường ngắn; tiêu đề thật hiếm khi ngắn kiểu này
            if len(s.split()) <= 12:
                return True
        if not s:
            return True
        if _RE_EMAIL.search(s):
            return True
        if _is_toc_line(s):
            return True
        meta = _collapse_spaced_caps_heading(s)
        if meta in _META_HEADINGS:
            return True
        if re.search(r"^\s*(journal|volume|issue|issn|copyright|©)\b", s, re.IGNORECASE):
            return True
        if re.search(r"^\s*(article\s*info|highlights|graphical\s*abstract)\b", s, re.IGNORECASE):
            return True
        if re.search(r"^\s*(tác\s*giả|authors?|corresponding\s*author)\b", s, re.IGNORECASE):
            return True

        # NEW: block typical abstract openers
        if re.search(r"^\s*(bài\s*viết|nghiên\s*cứu\s+này|this\s+study|the\s+study)\b", s, re.IGNORECASE):
            return True

        if len(re.findall(r"\d", s)) >= 6:
            return True
        if re.search(r"\b(doi:|issn|sciencedirect)\b", s, re.IGNORECASE):
            return True
        return False

    candidates: List[str] = []
    for l in head:
        s = _norm_ws(l)
        if len(s) < 10 or len(s) > 240:
            continue
        if _is_bad_title_line(s):
            continue
        candidates.append(s)

    if not candidates:
        return None, None

    title_vi: Optional[str] = None
    title_en: Optional[str] = None

    for s in candidates[:10]:
        if title_vi is None:
            if _VI_DIACRITICS.search(s) and len(s.split()) >= 4:
                title_vi = s
                continue
            if _english_ratio(s) <= 0.55 and re.search(
                r"\b(và|của|trong|nghiên\s*cứu|đánh\s*giá|ứng\s*dụng)\b", s, re.IGNORECASE
            ):
                if len(s.split()) >= 4:
                    title_vi = s
                    continue
        if title_vi and title_en:
            break            
        if title_en is None:
            if (not _VI_DIACRITICS.search(s)) and _english_ratio(s) >= 0.80 and len(s.split()) >= 4:
                title_en = s
                continue
        
    # Small merge for wrapped titles (2 lines)
    def _maybe_merge_wrapped(title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        try:
            idx = candidates.index(title)
        except ValueError:
            return title
        if idx + 1 >= len(candidates):
            return title
        nxt = candidates[idx + 1]
        # merge only if next line looks like continuation (short-ish, not anchor/meta)
        if len(nxt) <= 140 and not re.search(r"(từ\s*khóa|keywords|tóm\s*tắt|abstract|summary|doi|received)", nxt, re.IGNORECASE):
            if not _is_bad_title_line(nxt):
                return _norm_ws(f"{title} {nxt}")
        return title

    title_vi = _maybe_merge_wrapped(title_vi)
    title_en = _maybe_merge_wrapped(title_en)

    return title_vi, title_en


def _detect_keywords(front_text: str) -> Tuple[bool, bool]:
    """
    Keyword detection across variants:
    - "Từ khóa:" / "Từ khóa"
    - "Keywords:" / "Keywords"
    Accept inline list or next line list.
    """
    t = front_text or ""
    kw_vi = False
    kw_en = False

    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        # VI
        if re.match(r"^Từ\s*khóa\b", ln, re.IGNORECASE):
            after = re.split(r"[:：]", ln, maxsplit=1)
            payload = after[1].strip() if len(after) > 1 else ""
            if not payload and i + 1 < len(lines):
                payload = lines[i + 1]
            if payload:
                kw_vi = True

        # EN
        if re.match(r"^Keywords\b", ln, re.IGNORECASE):
            after = re.split(r"[:：]", ln, maxsplit=1)
            payload = after[1].strip() if len(after) > 1 else ""
            if not payload and i + 1 < len(lines):
                payload = lines[i + 1]
            if payload:
                kw_en = True

    # backward compatible: if anchors exist at all
    if not kw_vi and _RE_KW_VI.search(t):
        kw_vi = True
    if not kw_en and _RE_KW_EN.search(t):
        kw_en = True

    return kw_vi, kw_en


def _collect_after_anchor(lines: List[str], anchor_idx: int, max_lines: int, stop_regexes: List[re.Pattern]) -> str:
    """
    Collect text after an anchor line until stop condition.
    stop_regexes applies to the NEXT line (heading/keywords/etc).
    """
    buf: List[str] = []
    for j in range(anchor_idx + 1, min(len(lines), anchor_idx + 1 + max_lines)):
        nxt = (lines[j] or "").strip()
        if not nxt:
            # allow a few empty lines
            if buf:
                buf.append("")
            continue
        if any(rx.search(nxt) for rx in stop_regexes):
            break
        if _is_keywords_line(nxt) or _is_heading_line(nxt):
            break
        buf.append(nxt)
    return _norm_ws("\n".join(buf))


def _is_keywords_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    return bool(re.match(r"^(từ\s*khóa|keywords)\b", s, re.IGNORECASE))


def _is_heading_line(line: str) -> bool:
    """
    Decide whether a line is a SECTION HEADING (not just containing words like 'method').
    Prevent stopping abstract capture too early when abstract text contains 'method', etc.
    """
    s = (line or "").strip()
    if not s:
        return False
    if _is_toc_line(s):
        return False

    raw = s
    # remove leading numbering "1.", "1.1", "I."
    raw = re.sub(r"^\s*((\d+(\.\d+)*)|[IVXLC]+)\s*[\).\:-]\s*", "", raw).strip()

    # spaced caps normalization
    collapsed = _collapse_spaced_caps_heading(raw)
    if collapsed in _META_HEADINGS:
        return True

    # short lines more likely headings
    words = raw.split()
    if len(words) <= 12:
        # if it matches known headings, treat as heading
        if (
            _RE_H_INTRO.search(raw)
            or _RE_H_METHODS.search(raw)
            or _RE_H_RESULTS.search(raw)
            or _RE_H_CONCL.search(raw)
            or _RE_H_REFS.search(raw)
            or _RE_H_ACK.search(raw)
            or _RE_H_COI.search(raw)
            or _RE_H_CONTRIB.search(raw)
            or _RE_H_APPX.search(raw)
            or _RE_ABS_VI_ANCHOR.search(raw)
            or _RE_ABS_EN_ANCHOR.search(raw)
            or _RE_H_ABS_EN.match(raw)
        ):
            return True

        # all caps / title-cased single short line
        if raw.isupper() and len(raw) <= 80:
            return True

    return False


def _detect_abstract_vi(front_lines: List[str]) -> Optional[str]:
    """
    Fix unlabelled VI abstract:
    If no 'Tóm tắt' anchor, but there is 'Từ khóa:', treat the block
    between (after email line) and 'Từ khóa' as VI abstract when long enough.
    """
    if not front_lines:
        return None

    # 1) keep existing anchor-based logic (original behavior)
    for i, l in enumerate(front_lines[:600]):
        if _RE_ABS_VI_ANCHOR.search(l):
            buf: List[str] = []
            for j in range(i + 1, min(len(front_lines), i + 1 + 160)):
                nxt = (front_lines[j] or "").strip()
                if not nxt:
                    if buf:
                        buf.append("")
                    continue
                if _is_keywords_line(nxt) or _is_heading_line(nxt) or _RE_ABS_EN_ANCHOR.search(nxt) or _RE_H_ABS_EN.match(nxt):
                    break
                buf.append(nxt)
            cand = _norm_ws("\n".join(buf))
            if len(cand.split()) >= 30 and (_english_ratio(cand) <= 0.65 or _VI_DIACRITICS.search(cand)):
                return cand

    # 2) NEW fallback: between email line and "Từ khóa:"
    kw_idx = None
    for i, l in enumerate(front_lines[:400]):
        if _RE_KW_VI.search(l):
            kw_idx = i
            break
    if kw_idx is None or kw_idx == 0:
        return None

    start = 0
    for i, l in enumerate(front_lines[:kw_idx]):
        if _RE_EMAIL.search(l):
            start = i + 1

    if start >= kw_idx:
        return None

    block = _norm_ws("\n".join(front_lines[start:kw_idx]))
    if len(block.split()) >= 30 and (_english_ratio(block) <= 0.65 or _VI_DIACRITICS.search(block)):
        return block

    return None


def _detect_abstract_en(lines: List[str]) -> Optional[str]:
    """
    EN abstract detection:
    - Accept 'Abstract', 'Summary', or spaced-caps 'A B S T R A C T'.
    - Stops only on true heading/keywords lines.
    - IMPORTANT: fixed early-return bug (do NOT return inside the loop).
    """
    if not lines:
        return None

    for i, l in enumerate(lines[:900]):
        h = _collapse_spaced_caps_heading(l)
        if _RE_ABS_EN_ANCHOR.search(l) or _RE_H_ABS_EN.match(l) or h == "ABSTRACT":
            buf: List[str] = []
            for j in range(i + 1, min(len(lines), i + 1 + 180)):
                nxt = (lines[j] or "").strip()
                if not nxt:
                    if buf:
                        buf.append("")
                    continue
                if _is_keywords_line(nxt) or _is_heading_line(nxt) or _RE_ABS_VI_ANCHOR.search(nxt):
                    break
                buf.append(nxt)
            cand = _norm_ws("\n".join(buf))
            if len(cand.split()) >= 30 and (_english_ratio(cand) >= 0.70) and (not _VI_DIACRITICS.search(cand)):
                return cand

    return None


# ─────────────────────────────────────────
# Authors / Contact (STRICT)
# ─────────────────────────────────────────
def _detect_authors_strict(all_lines: List[str], body_start_idx: int) -> Tuple[bool, str]:
    """
    Fix for merged author+email in one line (common after PDF->DOCX).
    Accept an author-like line even if it contains email by stripping email first.
    """
    if not all_lines:
        return False, "Empty document"

    early_end = min(len(all_lines), max(30, body_start_idx + 15))
    early = all_lines[:early_end]

    emails = []
    for l in early:
        emails.extend(_RE_EMAIL.findall(l or ""))
    if not emails:
        return False, "No email/contact found in early region"

    # Find author-like line: 2-8 words, mostly Title Case / uppercase, not metadata/anchors
    def _looks_like_author_line(s: str) -> bool:
        s = _norm_ws(s)
        if len(s) < 6 or len(s) > 220:
            return False
        if _is_toc_line(s):
            return False
        if re.search(r"\b(doi|received|available online|article info|highlights)\b", s, re.IGNORECASE):
            return False
        meta = _collapse_spaced_caps_heading(s)
        if meta in _META_HEADINGS:
            return False

        # NEW: remove email + "Email:" labels, then score remaining text
        s_wo_email = _RE_EMAIL.sub("", s)
        s_wo_email = re.sub(r"\b(email|e-mail)\b\s*[:：]?\s*", "", s_wo_email, flags=re.IGNORECASE)
        s_wo_email = _norm_ws(s_wo_email)
        if len(s_wo_email) < 4:
            return False

        # keep mostly the name part (before affiliation keywords)
        s_name = re.split(r"\b(trường|university|institute|faculty|khoa)\b", s_wo_email, maxsplit=1, flags=re.IGNORECASE)[0]
        s_name = _norm_ws(s_name)

        words = s_name.split()
        if not (2 <= len(words) <= 10):
            return False

        tc = 0
        alpha = 0
        for w in words:
            if re.fullmatch(r"[A-Za-zÀ-ỹ\.\-']+", w):
                alpha += 1
                if w[:1].isupper():
                    tc += 1

        if alpha == 0:
            return False
        return (tc / alpha) >= 0.55 or s_name.isupper()

    author_found = any(_looks_like_author_line(l or "") for l in early[:120])
    if not author_found:
        return False, f"Email found ({emails[0]}), but no clear author line nearby"

    return True, f"Found email ({emails[0]}) + author-like line"


# ─────────────────────────────────────────
# Heading -> structure mapping
# ─────────────────────────────────────────
def _detect_via_heading(heading: str, hits: Dict[str, SectionHit], content: str = "") -> None:
    h = (heading or "").strip()
    if not h:
        return

    # Normalize/collapse
    hc = _collapse_spaced_caps_heading(h)
    h_raw = h

    if _RE_H_INTRO.search(h_raw) or _RE_H_INTRO.search(hc):
        _mark(hits, "introduction", f"heading:{h_raw}", "Detected by heading")
        return

    if _RE_H_METHODS.search(h_raw) or _RE_H_METHODS.search(hc):
        _mark(hits, "methods", f"heading:{h_raw}", "Detected by heading")
        return

    if _RE_H_RESULTS.search(h_raw) or _RE_H_RESULTS.search(hc):
        _mark(hits, "results", f"heading:{h_raw}", "Detected by heading")
        return

    if _RE_H_CONCL.search(h_raw) or _RE_H_CONCL.search(hc):
        _mark(hits, "conclusion", f"heading:{h_raw}", "Detected by heading")
        return

    if _RE_H_REFS.search(h_raw) or _RE_H_REFS.search(hc):
        _mark(hits, "references", f"heading:{h_raw}", "Detected by heading")
        # style guess from content if any
        if content:
            try:
                hits["references"].references_style = guess_references_style(content)
            except Exception:
                pass
        return

    if _RE_H_APPX.search(h_raw) or _RE_H_APPX.search(hc):
        _mark(hits, "appendix", f"heading:{h_raw}", "Detected by heading")
        return

    if _RE_H_CONTRIB.search(h_raw) or _RE_H_CONTRIB.search(hc):
        _mark(hits, "contributions", f"heading:{h_raw}", "Detected by heading")
        return

    if _RE_H_COI.search(h_raw) or _RE_H_COI.search(hc):
        _mark(hits, "conflict_of_interest", f"heading:{h_raw}", "Detected by heading")
        return

    if _RE_H_ACK.search(h_raw) or _RE_H_ACK.search(hc):
        _mark(hits, "acknowledgements", f"heading:{h_raw}", "Detected by heading")
        return


# ─────────────────────────────────────────
# References pattern fallback
# ─────────────────────────────────────────
def _references_presence(text: str) -> bool:
    """
    Pattern-based references detection for tail scan:
    - multiple numbered entries OR [n] entries
    - author-year style patterns
    """
    t = text or ""
    if not t:
        return False

    if _RE_H_REFS.search(t):
        return True

    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return False

    # common entry patterns
    p1 = re.compile(r"^\s*\[\d{1,4}\]\s+")
    p2 = re.compile(r"^\s*\d{1,4}\.\s+")
    p3 = re.compile(r"\(\s*(19|20)\d{2}\s*\)")
    p4 = re.compile(r"\bdoi:\s*10\.\d{4,9}/", re.IGNORECASE)

    score = 0
    for ln in lines[:400]:
        if p1.search(ln) or p2.search(ln):
            score += 1
        elif p3.search(ln) and re.search(r"\b(et\s+al\.|Vol\.|pp\.|Journal|Proceedings)\b", ln, re.IGNORECASE):
            score += 1
        elif p4.search(ln):
            score += 1

        if score >= 3:
            return True

    return False


# ─────────────────────────────────────────
# Main API
# ─────────────────────────────────────────
def check_structure_docx(
    path: str,
    openai_model: str = DEFAULT_LLM_MODEL,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    parsed_paras: Optional[List[DocPara]] = None,
    enable_llm_fallback: bool = True,
) -> Report:
    if not path or not isinstance(path, str):
        raise ValueError(f"Invalid path type: {type(path)}")

    p = Path(path)
    if not p.exists():
        logger.error("File not found: %s", path)
        raise FileNotFoundError(f"File not found: {path}")

    if p.suffix.lower() != ".docx":
        raise ValueError(f"Only .docx is supported, got: {p.suffix}")

    notes: List[str] = []

    # Parse DOCX
    paras = parsed_paras if parsed_paras is not None else extract_docx_paragraphs(str(p))
    if not paras:
        hits = {k: SectionHit(status="missing") for k, _ in TARGETS}
        return Report(file=str(p), ok=False, sections=hits, notes=["Empty DOCX"])

    # Build all_lines
    all_lines = [(pp.text or "").strip() for pp in paras if (pp.text or "").strip()]

    # Find body start
    body_start_idx = _find_body_start_idx(paras)
    body_start_idx = max(0, min(body_start_idx, len(paras)))
    notes.append(f"body_start_idx={body_start_idx}")

    # Build front lines
    front_lines = [(pp.text or "").strip() for pp in paras[:body_start_idx] if (pp.text or "").strip()]
    front_win = _frontmatter_window(front_lines)
    front_text = "\n".join(front_win)

    # init hits
    hits: Dict[str, SectionHit] = {k: SectionHit(status="missing") for k, _ in TARGETS}

    # ─────────────────────────
    # 1) FRONTMATTER heuristics
    # ─────────────────────────
    title_vi, title_en = _detect_titles(front_win)
    if title_vi:
        _mark(hits, "title_vi", "front:title_vi", "Heuristic title_vi")
    if title_en:
        _mark(hits, "title_en", "front:title_en", "Heuristic title_en")

    kw_vi, kw_en = _detect_keywords(front_text)
    if kw_vi:
        _mark(hits, "keywords_vi", "front:keywords_vi", "Heuristic keywords_vi")
    if kw_en:
        _mark(hits, "keywords_en", "front:keywords_en", "Heuristic keywords_en")

    abs_vi = _detect_abstract_vi(front_win)
    if abs_vi:
        _mark(hits, "abstract_vi", "front:abstract_vi", "Heuristic abstract_vi")

    # IMPORTANT: abstract_en fixed + tail scan for "Summary" at end
    abs_en = _detect_abstract_en(front_win)
    if not abs_en:
        tail_lines = [(pp.text or "").strip() for pp in paras[int(len(paras) * 0.60) :] if (pp.text or "").strip()]
        abs_en = _detect_abstract_en(tail_lines)

    if abs_en:
        _mark(hits, "abstract_en", "front/tail:abstract_en", "Heuristic abstract_en (Abstract/Summary)")

    # Authors/contact (STRICT)
    authors_ok, authors_note = _detect_authors_strict(all_lines, body_start_idx)
    if authors_ok:
        _mark(hits, "authors", "front/early:authors", authors_note)
    else:
        notes.append(f"Authors check: {authors_note}")

    # ─────────────────────────
    # 2) BODY segmentation + headings
    # ─────────────────────────
    body_paras = paras[body_start_idx:] if body_start_idx < len(paras) else []
    try:
        _unused_front, sections = split_by_structure(body_paras)
    except Exception as e:
        sections = []
        notes.append(f"split_by_structure error: {e}")

    notes.append(f"Sections={len(sections)}")
    for s in sections:
        _detect_via_heading((getattr(s, "heading", "") or "").strip(), hits, content=getattr(s, "content", "") or "")

    # ─────────────────────────
    # 3) Tail scan for references (pattern fallback)
    # ─────────────────────────
    if hits["references"].status != "ok":
        tail = _tail_text(paras, 0.65)
        if _references_presence(tail):
            try:
                hits["references"].references_style = guess_references_style(tail)
            except Exception:
                pass
            _mark(hits, "references", "pattern-tail-scan", "Detected by tail reference patterns (no heading needed)")
        else:
            notes.append("Tail-scan: references patterns not strong enough")

    # ─────────────────────────
    # 4) LLM fallback (optional)
    # ─────────────────────────
    if enable_llm_fallback:
        payload: List[Dict[str, str]] = []

        # front excerpt
        front_excerpt = _norm_ws("\n".join(front_win[:120]))
        need_front = any(
            hits[k].status != "ok"
            for k in [
                "title_en",
                "abstract_vi",
                "abstract_en",
                "keywords_vi",
                "keywords_en",
                "introduction",
                "methods",
                "results",
                "conclusion",
            ]
        )
        if front_excerpt and need_front:
            payload.append({"id": "front", "heading": "FRONTMATTER", "content": front_excerpt})

        # section excerpts
        for i, s in enumerate(sections[:30]):  # cap to keep cost predictable
            heading = getattr(s, "heading", "") or ""
            content = getattr(s, "content", "") or ""
            if content.strip():
                payload.append({"id": f"sec_{i}", "heading": heading, "content": content[:1600]})

        # tail excerpt helps COI/ack/ref statements
        tail_excerpt = _tail_text(paras, 0.75)
        if tail_excerpt:
            payload.append({"id": "tail", "heading": "TAIL", "content": tail_excerpt[:1800]})

        if payload:
            try:
                batch = llm_classify_document_batch(payload, openai_model=openai_model) or {}
            except Exception as e:
                notes.append(f"LLM batch error: {e}")
                batch = {}

            for pid, r in (batch or {}).items():
                label_id = (r or {}).get("label", "NONE")
                conf = float((r or {}).get("confidence", 0.0))
                reason = (r or {}).get("reason", "")
                excerpt = (r or {}).get("excerpt", "")

                if conf < min_confidence:
                    continue

                # Conservative language gating for abstracts
                if label_id == "abstract_vi":
                    # If excerpt is mostly English, skip marking VI abstract
                    if _english_ratio(excerpt) >= 0.75 and not _VI_DIACRITICS.search(excerpt):
                        continue

                if label_id == "abstract_en":
                    # If excerpt has Vietnamese diacritics heavily, skip
                    if _VI_DIACRITICS.search(excerpt) and _english_ratio(excerpt) < 0.60:
                        continue

                if label_id in hits and hits[label_id].status != "ok":
                    _mark(
                        hits,
                        label_id,
                        f"llm:{pid}",
                        f"LLM fallback: {reason}",
                        llm_verified=True,
                        conf=conf,
                        llm_label=label_id,
                    )

    # ─────────────────────────
    # 5) Overall OK based on REQUIRED
    # ─────────────────────────
    required_ids = [k for k, v in REQUIRED.items() if v]
    ok = all(hits.get(k, SectionHit(status="missing")).status == "ok" for k in required_ids)

    return Report(file=str(p), ok=ok, sections=hits, notes=notes)
