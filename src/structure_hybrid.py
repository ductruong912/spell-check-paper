from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from docx import Document

# -----------------------------
# Logging
# -----------------------------
logger = logging.getLogger("structure_checker_tt27")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# -----------------------------
# Types
# -----------------------------
Status = str  # "ok" | "missing" | "implicit"


@dataclass
class SectionHit:
    status: Status
    count: int = 0
    evidence: Optional[str] = None
    source: str = "rule"  # "heading" | "keyword" | "rule"


@dataclass
class Report:
    file: str
    ok: bool
    sections: Dict[str, SectionHit]
    notes: List[str]
    references_format: str = "Unknown"
    references_confidence: float = 0.0
    references_counts: Optional[Dict[str, int]] = None
    references_evidence: Optional[List[str]] = None


# -----------------------------
# References format detection (STRICT)
# -----------------------------
@dataclass
class RefDetectResult:
    format: str  # "APA" | "IEEE" | "Chicago" | "Vancouver" | "Unknown"
    confidence: float
    counts: Dict[str, int]
    n_entries: int
    evidence: List[str]


# IEEE: [1] ...
IEEE_ENTRY_RE = re.compile(r"^\s*\[\s*\d{1,4}\s*\]\s+")
IEEE_QUOTED_TITLE_RE = re.compile(r"\".+?\"|“.+?”")
IEEE_VOL_NO_PP_RE = re.compile(r"\bvol\.|\bno\.|\bpp\.", re.IGNORECASE)

# Vancouver: 1. ... or 1) ...
VANCOUVER_ENTRY_RE = re.compile(r"^\s*\d{1,4}\s*[\.\)]\s+")
VANCOUVER_YEAR_SEMI_RE = re.compile(r"\b(19|20)\d{2}\s*;\s*\d")  # Year;Volume
VANCOUVER_PAGES_RE = re.compile(r"\b\d+\s*:\s*\d+(-\d+)?\b")     # Vol:Pages (loose)

# APA: ... (2020). ...
APA_YEAR_PARENS_RE = re.compile(r"\(\s*(19|20)\d{2}[a-z]?\s*\)\.")  # (2020). or (2020a).
APA_AMPERSAND_RE = re.compile(r"\s&\s")
APA_DOI_RE = re.compile(r"\bdoi:\s*10\.\d{4,9}/\S+|https?://doi\.org/10\.\d{4,9}/\S+", re.IGNORECASE)
APA_VOL_ISSUE_RE = re.compile(r"\b\d+\s*\(\s*\d+\s*\)\s*,")  # 12(3),
APA_AUTHOR_INITIALS_RE = re.compile(r"\b[A-Z]\.\s*(?:[A-Z]\.)?")   # A. or A. A.

# Chicago (very broad -> strict & conservative)
CHICAGO_AUTHOR_COMMA_FIRST_RE = re.compile(r"^[A-ZÀ-Ỵ][^,]{2,40},\s+[A-ZÀ-Ỵ]")  # Last, First...
CHICAGO_QUOTED_TITLE_RE = re.compile(r"“.+?”|\".+?\"")
CHICAGO_YEAR_END_RE = re.compile(r"(19|20)\d{2}\.\s*$")
CHICAGO_CITY_PUBLISHER_RE = re.compile(r":\s*[^.]{2,40},\s*(19|20)\d{2}\.")  # City: Publisher, 2019.

REF_NOISE_RE = re.compile(r"^\s*(tài liệu tham khảo|references|bibliography)\s*:?\s*$", re.IGNORECASE)
REF_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+|[IVXLC]+\.\s+)?(tài liệu tham khảo|references|bibliography)\s*:?\s*$",
    re.IGNORECASE,
)
REF_STOP_RE = re.compile(
    r"^\s*(phụ lục|appendix|đóng góp của tác giả|author contributions|xung đột lợi ích|mâu thuẫn lợi ích|conflict of interest|lời cảm ơn|acknowledg)\b",
    re.IGNORECASE,
)

# -----------------------------
# Utilities: normalization + header/footer + noise filtering
# -----------------------------
def _norm_ws(s: str) -> str:
    s = (s or "").replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _collect_header_footer_text(doc: Document) -> set[str]:
    hf_texts: set[str] = set()
    for sec in doc.sections:
        for p in sec.header.paragraphs:
            t = _norm_ws(p.text)
            if t:
                hf_texts.add(t)
        for p in sec.footer.paragraphs:
            t = _norm_ws(p.text)
            if t:
                hf_texts.add(t)
    return hf_texts


NOISE_PATTERNS = [
    # Journal / issue noise
    r"^\s*ISSN\s*\d",
    r"^\s*E-ISSN\s*\d",
    r"^\s*khoa học thương mại\s*$",
    r"^\s*thương mại\s*$",
    r"^\s*Số\s*\d+/\d{4}\s*$",
    r"^\s*MỤC LỤC\s*$",
    r"^\s*QUẢN TRỊ KINH DOANH\s*$",
    r"^\s*KINH TẾ VÀ QUẢN LÝ\s*$",
    # page numbers
    r"^\s*\d+\s*$",
    # stray symbols often from PDF->DOCX conversions
    r"^[\uF0BF\uF0B7\uF0A7\uF0A8\uF0A9\uF0AA\uF0AB\uF0AC\uF0AD\uF0AE\uF0AF]+$",
]
NOISE_RE = [re.compile(p, re.IGNORECASE) for p in NOISE_PATTERNS]


def _is_noise_line(t: str) -> bool:
    if not t:
        return True
    for rx in NOISE_RE:
        if rx.search(t):
            return True
    return False


def extract_docx_blocks(path: str) -> List[Tuple[str, str]]:
    doc = Document(path)
    hf_texts = _collect_header_footer_text(doc)

    blocks: List[Tuple[str, str]] = []
    for p in doc.paragraphs:
        t = _norm_ws(p.text)
        if not t:
            continue

        # drop exact header/footer lines
        if t in hf_texts:
            continue

        # drop common noise
        if _is_noise_line(t):
            continue

        style_name = (p.style.name or "").lower() if p.style is not None else ""
        is_heading = ("heading" in style_name) or bool(re.match(r"^h[1-9]$", style_name))
        blocks.append(("heading" if is_heading else "para", t))

    return blocks


# -----------------------------
# Section detection (strict)
# -----------------------------
def _mk_rx(keys: List[str], *, allow_trailing: bool = False) -> re.Pattern:
    escaped = [re.escape(k) for k in keys]
    prefix = r"^\s*(?:\d+(?:\.\d+)*\.?\s+|[IVXLC]+\.\s+)?"
    label = r"(?:%s)" % "|".join(escaped)
    if allow_trailing:
        suffix = r"(?:\s*:?\s*.*)?\s*$"
    else:
        suffix = r"\s*:?\s*$"
    return re.compile(prefix + label + suffix, re.IGNORECASE)

SECTION_RULES = {
    # Core sections (Điều 6 - thành phần chính)
    "title": {"type": "front_matter", "required": True},
    "authors": {"type": "front_matter", "required": True},
    "abstract_vi": {"type": "front_matter", "required": True, "rx": _mk_rx(["Tóm tắt", "TÓM TẮT"], allow_trailing=True)},
    "keywords_vi": {"type": "front_matter", "required": True, "rx": _mk_rx(["Từ khóa", "TỪ KHÓA"], allow_trailing=True)},
    "abstract_en": {"type": "front_matter", "required": True, "rx": _mk_rx(["Abstract", "ABSTRACT", "Summary", "SUMMARY"], allow_trailing=True)},
    "keywords_en": {"type": "front_matter", "required": True, "rx": _mk_rx(["Keywords", "KEYWORDS", "Key words", "KEY WORDS"], allow_trailing=True)},
    "introduction": {"type": "body", "required": True, "rx": _mk_rx(["Mở đầu", "Giới thiệu", "Đặt vấn đề", "Introduction"])},
    "methods": {
        "type": "body",
        "required": True,
        "rx": _mk_rx([
            "Phương pháp nghiên cứu",
            "Vật liệu và phương pháp",
            "Đối tượng và phương pháp",
            "Materials and Methods",
            "Methodology",
            "Methods",
        ]),
    },
    "results_discussion": {
        "type": "body",
        "required": True,
        "rx": _mk_rx([
            "Kết quả và thảo luận",
            "Kết quả nghiên cứu và thảo luận",
            "Kết quả nghiên cứu",
            "Thảo luận",
            "Results and Discussion",
            "Results",
            "Discussion",
        ]),
    },
    "conclusion": {"type": "body", "required": True, "rx": _mk_rx(["Kết luận", "KẾT LUẬN", "Conclusion", "CONCLUSION"])},
    "references": {
        "type": "tail",
        "required": True,
        "rx": _mk_rx(["Tài liệu tham khảo", "TÀI LIỆU THAM KHẢO", "References", "REFERENCES", "Bibliography"], allow_trailing=True),
    },

    # Optional
    "acknowledgements": {"type": "tail_optional", "required": False, "rx": _mk_rx(["Lời cảm ơn", "Acknowledgements", "Acknowledgments"])},
    "funding": {"type": "tail_optional", "required": False, "rx": _mk_rx(["Tài trợ", "Funding"])},
    "conflict_of_interest": {"type": "tail_optional", "required": False, "rx": _mk_rx(["Xung đột lợi ích", "Mâu thuẫn lợi ích", "Conflict of interest"])},
    "author_contributions": {"type": "tail_optional", "required": False, "rx": _mk_rx(["Đóng góp của tác giả", "Author contributions"])},
    "appendix": {"type": "tail_optional", "required": False, "rx": _mk_rx(["Phụ lục", "Appendix"])},
}


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _detect_title_and_authors(blocks: List[Tuple[str, str]]) -> Tuple[SectionHit, SectionHit, List[str]]:
    """
    Strict heuristic for title/authors in first ~60 meaningful lines.
    - Title: first heading or uppercase-ish line (high upper ratio).
    - Authors: evidence of email/ORCID/keyword in top lines.
    """
    notes: List[str] = []
    window = blocks[:60]

    skip_title_exact = {"KINH TẾ VÀ QUẢN LÝ", "Ý KIẾN TRAO ĐỔI", "MỤC LỤC"}

    title_hit = SectionHit(status="missing")
    authors_hit = SectionHit(status="missing")

    # Title heuristic
    for kind, t in window[:25]:
        if len(t) < 12:
            continue
        if t.strip().upper() in skip_title_exact:
            continue
        if "mục lục" in t.lower() or "issn" in t.lower():
            continue
        alpha = sum(ch.isalpha() for ch in t)
        upper = sum(ch.isupper() for ch in t if ch.isalpha())
        is_upper_ratio = upper / max(1, alpha)
        if kind == "heading" or is_upper_ratio > 0.7:
            title_hit = SectionHit(status="ok", count=1, evidence=t[:200], source="rule")
            break

    # Authors heuristic
    for _, t in window[:40]:
        if EMAIL_RE.search(t) or "tác giả" in t.lower() or "email" in t.lower() or "orcid" in t.lower():
            authors_hit = SectionHit(status="ok", count=1, evidence=t[:200], source="rule")
            break

    if title_hit.status != "ok":
        notes.append("Không phát hiện tiêu đề chắc chắn ở đầu file (có thể do file không dùng heading/in hoa đúng).")
    if authors_hit.status != "ok":
        notes.append("Không phát hiện tác giả/liên hệ chắc chắn (email/ORCID/tác giả liên hệ).")

    return title_hit, authors_hit, notes


def _find_section_hits(blocks: List[Tuple[str, str]], rx: re.Pattern) -> List[Tuple[int, str, str]]:
    hits: List[Tuple[int, str, str]] = []
    for i, (kind, t) in enumerate(blocks):
        if rx.match(t):
            hits.append((i, "heading" if kind == "heading" else "keyword", t[:240]))
    return hits


# -----------------------------
# References helpers
# -----------------------------
def extract_references_lines_from_blocks(blocks: List[Tuple[str, str]]) -> List[str]:
    start = None
    for i, (_, t) in enumerate(blocks):
        if REF_HEADING_RE.match(t):
            start = i + 1
            break
    if start is None:
        return []
    ref_lines: List[str] = []
    for _, t in blocks[start:]:
        if REF_STOP_RE.match(t):
            break
        ref_lines.append(t)
    return ref_lines


def _normalize_ref_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    for s in lines:
        t = _norm_ws(s)
        if not t:
            continue
        if REF_NOISE_RE.match(t):
            continue
        out.append(t)
    return out


def _split_into_entries_strict(lines: List[str], max_entries: int = 120) -> List[str]:
    lines = _normalize_ref_lines(lines)
    if not lines:
        return []

    ieee_markers = sum(1 for t in lines if IEEE_ENTRY_RE.match(t))
    van_markers = sum(1 for t in lines if VANCOUVER_ENTRY_RE.match(t))

    entries: List[str] = []

    if ieee_markers >= 3 and ieee_markers >= van_markers:
        cur: Optional[str] = None
        for t in lines:
            if IEEE_ENTRY_RE.match(t):
                if cur:
                    entries.append(cur.strip())
                cur = t
            else:
                if cur:
                    cur += " " + t
        if cur:
            entries.append(cur.strip())
        return entries[:max_entries]

    if van_markers >= 3:
        cur = None
        for t in lines:
            if VANCOUVER_ENTRY_RE.match(t):
                if cur:
                    entries.append(cur.strip())
                cur = t
            else:
                if cur:
                    cur += " " + t
        if cur:
            entries.append(cur.strip())
        return entries[:max_entries]

    # Fallback: conservative merge
    cur = ""
    for t in lines:
        if IEEE_ENTRY_RE.match(t) or VANCOUVER_ENTRY_RE.match(t) or CHICAGO_AUTHOR_COMMA_FIRST_RE.match(t):
            if cur:
                entries.append(cur.strip())
            cur = t
        else:
            if not cur:
                cur = t
            else:
                cur += " " + t
    if cur:
        entries.append(cur.strip())

    entries = [e for e in entries if len(e) >= 25]
    return entries[:max_entries]


def _score_ieee(e: str) -> int:
    score = 0
    if IEEE_ENTRY_RE.match(e):
        score += 4
    if IEEE_QUOTED_TITLE_RE.search(e):
        score += 1
    if IEEE_VOL_NO_PP_RE.search(e):
        score += 1
    if re.search(r"\b(19|20)\d{2}\b", e):
        score += 1
    return score


def _score_vancouver(e: str) -> int:
    score = 0
    if VANCOUVER_ENTRY_RE.match(e):
        score += 4
    if VANCOUVER_YEAR_SEMI_RE.search(e):
        score += 2
    if VANCOUVER_PAGES_RE.search(e):
        score += 1
    if re.search(r"\b(19|20)\d{2}\b", e):
        score += 1
    return score


def _score_apa(e: str) -> int:
    score = 0
    if APA_YEAR_PARENS_RE.search(e):
        score += 5
    if APA_AMPERSAND_RE.search(e):
        score += 1
    if APA_VOL_ISSUE_RE.search(e):
        score += 1
    if APA_DOI_RE.search(e):
        score += 1
    if APA_AUTHOR_INITIALS_RE.search(e[:90]):
        score += 1
    return score


def _score_chicago(e: str) -> int:
    score = 0
    if CHICAGO_AUTHOR_COMMA_FIRST_RE.match(e):
        score += 2
    if CHICAGO_QUOTED_TITLE_RE.search(e):
        score += 1
    if CHICAGO_CITY_PUBLISHER_RE.search(e):
        score += 2
    if CHICAGO_YEAR_END_RE.search(e):
        score += 1

    # penalties
    if IEEE_ENTRY_RE.match(e):
        score -= 4
    if VANCOUVER_ENTRY_RE.match(e):
        score -= 3
    if APA_YEAR_PARENS_RE.search(e):
        score -= 3
    return score


def detect_references_format_strict(
    ref_lines: List[str],
    *,
    min_entries: int = 5,
    min_winner_ratio: float = 0.75,
    min_winner_margin: int = 3,
) -> RefDetectResult:
    entries = _split_into_entries_strict(ref_lines)
    n = len(entries)

    counts = {"APA": 0, "IEEE": 0, "Chicago": 0, "Vancouver": 0}
    evidence: List[str] = []

    if n < min_entries:
        return RefDetectResult("Unknown", 0.0, counts, n, evidence)

    voted = 0
    for e in entries:
        s_ieee = _score_ieee(e)
        s_van = _score_vancouver(e)
        s_apa = _score_apa(e)
        s_chi = _score_chicago(e)

        scores = {"IEEE": s_ieee, "Vancouver": s_van, "APA": s_apa, "Chicago": s_chi}
        winner = max(scores, key=scores.get)
        best = scores[winner]
        runner = sorted(scores.values(), reverse=True)[1]

        # per-entry strict vote
        if best >= 5 and (best - runner) >= 2:
            counts[winner] += 1
            voted += 1
            if len(evidence) < 5:
                evidence.append(e[:240])

    if voted < max(4, n // 3):
        return RefDetectResult("Unknown", 0.0, counts, n, evidence)

    winner = max(counts, key=counts.get)
    winner_count = counts[winner]
    runner_up_count = sorted(counts.values(), reverse=True)[1]
    ratio = winner_count / max(1, voted)

    if ratio >= min_winner_ratio and (winner_count - runner_up_count) >= min_winner_margin:
        confidence = min(0.99, 0.55 + ratio / 2.0)
        return RefDetectResult(winner, confidence, counts, n, evidence)

    return RefDetectResult("Unknown", 0.0, counts, n, evidence)



def _detect_implicit_vi_abstract_and_keywords(blocks: List[Tuple[str, str]]) -> Tuple[Optional[str], Optional[str]]:
    """
    Heuristic when 'Tóm tắt' heading is missing.
    Capture text after the received/accepted dates line until 'Từ khóa:' or until the body starts.
    """
    date_re = re.compile(r"ngày\s+nhận|ngày\s+duyệt|ngày\s+nhận\s+lại", re.IGNORECASE)
    kw_re = re.compile(r"^\s*từ\s+khóa\s*:?\s*", re.IGNORECASE)
    body_re = re.compile(r"^\s*(đặt\s+vấn\s+đề|mở\s+đầu|giới\s+thiệu)\b", re.IGNORECASE)

    start = None
    for i, (_, t) in enumerate(blocks[:140]):
        if date_re.search(t):
            start = i + 1
            break
    if start is None:
        start = 0

    abstract_parts: List[str] = []
    keywords_line: Optional[str] = None

    for _, t in blocks[start:start + 90]:
        if kw_re.match(t):
            keywords_line = t
            break
        if body_re.match(t):
            break
        if len(t) >= 40:
            abstract_parts.append(t)

    abstract_text = " ".join(abstract_parts).strip() if abstract_parts else None
    return abstract_text, keywords_line

# -----------------------------
# Main checker
# -----------------------------
def check_structure_docx(path: str) -> Report:
    p = Path(path)
    if p.suffix.lower() != ".docx":
        raise ValueError("Only .docx is supported for strict structure checking.")

    blocks = extract_docx_blocks(str(p))
    if not blocks:
        return Report(
            file=str(p),
            ok=False,
            sections={},
            notes=["Không trích xuất được nội dung (file trống hoặc bị lỗi)."],
        )

    sections: Dict[str, SectionHit] = {}

    # title/authors
    title_hit, authors_hit, ta_notes = _detect_title_and_authors(blocks)
    sections["title"] = title_hit
    sections["authors"] = authors_hit
    notes: List[str] = ta_notes

    # remaining sections via heading/keyword
    for sec_name, cfg in SECTION_RULES.items():
        if sec_name in ("title", "authors"):
            continue
        rx = cfg.get("rx")
        if not rx:
            continue

        hits = _find_section_hits(blocks, rx)
        if hits:
            _, source, ev = hits[0]
            sections[sec_name] = SectionHit(status="ok", count=len(hits), evidence=ev, source=source)
        else:
            req = bool(cfg.get("required", False))
            sections[sec_name] = SectionHit(status="missing" if req else "missing", count=0, evidence=None, source="rule")

    # Implicit Vietnamese abstract/keywords (only if headings missing)
    if sections.get("abstract_vi", SectionHit("missing")).status != "ok" or sections.get("keywords_vi", SectionHit("missing")).status != "ok":
        abs_text, kw_line = _detect_implicit_vi_abstract_and_keywords(blocks)
        if abs_text and sections.get("abstract_vi", SectionHit("missing")).status != "ok":
            sections["abstract_vi"] = SectionHit(status="implicit", count=1, evidence=abs_text[:200], source="rule")
            notes.append("Tóm tắt tiếng Việt không có heading; đã suy luận theo vị trí (implicit).")
        if kw_line and sections.get("keywords_vi", SectionHit("missing")).status != "ok":
            sections["keywords_vi"] = SectionHit(status="implicit", count=1, evidence=kw_line[:200], source="rule")
            notes.append("Từ khóa tiếng Việt nằm cùng dòng; đã suy luận theo pattern (implicit).")

    # Decide overall ok: all required present
    ok = True
    for sec_name, cfg in SECTION_RULES.items():
        if cfg.get("required", False):
            if sections.get(sec_name, SectionHit(status="missing")).status != "ok":
                ok = False

    # Detect references format (strict)
    ref_format = "Unknown"
    ref_conf = 0.0
    ref_counts: Optional[Dict[str, int]] = None
    ref_evidence: Optional[List[str]] = None

    if sections.get("references", SectionHit("missing")).status == "ok":
        ref_lines = extract_references_lines_from_blocks(blocks)
        det = detect_references_format_strict(ref_lines)

        ref_format = det.format
        ref_conf = det.confidence
        ref_counts = det.counts
        ref_evidence = det.evidence

        if det.format == "Unknown":
            notes.append(
                "Đã phát hiện mục Tài liệu tham khảo nhưng KHÔNG xác định chắc chắn chuẩn (strict). "
                f"counts={det.counts}, n_entries={det.n_entries}."
            )
        else:
            notes.append(
                f"Tài liệu tham khảo theo chuẩn {det.format} (strict), "
                f"confidence={det.confidence:.2f}, counts={det.counts}."
            )
    else:
        notes.append("Thiếu mục Tài liệu tham khảo hoặc không nhận diện được bằng heading/keyword chuẩn.")

    return Report(
        file=str(p),
        ok=ok,
        sections=sections,
        notes=notes,
        references_format=ref_format,
        references_confidence=ref_conf,
        references_counts=ref_counts,
        references_evidence=ref_evidence,
    )


# -----------------------------
# CLI
# -----------------------------
def main():
    import argparse

    ap = argparse.ArgumentParser(description="DOCX structure checker (strict).")
    ap.add_argument("docx_path", help="Path to .docx file")
    ap.add_argument("--json", dest="json_out", default="", help="Write JSON report to file")
    args = ap.parse_args()

    rep = check_structure_docx(args.docx_path)
    payload = {
        "file": rep.file,
        "ok": rep.ok,
        "sections": {k: asdict(v) for k, v in rep.sections.items()},
        "notes": rep.notes,
        "references_format": rep.references_format,
        "references_confidence": rep.references_confidence,
        "references_counts": rep.references_counts,
        "references_evidence": rep.references_evidence,
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote report JSON to %s", args.json_out)


if __name__ == "__main__":
    main()
