from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from docx import Document

# Load env
load_dotenv()

# OpenAI
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

# Logging
logger = logging.getLogger("structure_checker")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# -----------------------------
# Targets (the exact list you provided)
# -----------------------------
TARGETS: List[Tuple[str, str]] = [
    ("title_vi", "Tiêu đề (tiếng Việt)"),
    ("title_en", "Tiêu đề (tiếng Anh)"),
    ("authors", "Tác giả / Nhóm tác giả và thông tin liên hệ"),
    ("abstract_vi", "Tóm tắt (tiếng Việt)"),
    ("abstract_en", "Tóm tắt (tiếng Anh)"),
    ("keywords_vi", "Từ khóa (tiếng Việt)"),
    ("keywords_en", "Từ khóa (tiếng Anh)"),
    ("introduction", "Giới thiệu / Đặt vấn đề"),
    ("methods", "Vật liệu và/hoặc phương pháp nghiên cứu"),
    ("results", "Kết quả và thảo luận"),
    ("conclusion", "Kết luận"),
    ("appendix", "Phụ lục (nếu có)"),
    ("contributions", "Tuyên bố về đóng góp khoa học (nếu có)"),
    ("conflict_of_interest", "Cam kết về mâu thuẫn lợi ích (nếu có)"),
    ("acknowledgements", "Lời cảm ơn đối với cơ quan tài trợ và/hoặc tổ chức, cá nhân liên quan (nếu có)"),
    ("references", "Tài liệu tham khảo theo một trong các chuẩn quốc tế: APA, IEEE, Chicago, Vancouver"),
]

REQUIRED: Dict[str, bool] = {
    "title_vi": True,
    "title_en": True,
    "authors": True,
    "abstract_vi": True,
    "abstract_en": True,
    "keywords_vi": True,
    "keywords_en": True,
    "introduction": True,
    "methods": True,
    "results": True,
    "conclusion": True,
    "references": True,
    # optionals:
    "appendix": False,
    "contributions": False,
    "conflict_of_interest": False,
    "acknowledgements": False,
}

# -----------------------------
# Precompute enums & sets (CLEAN)
# -----------------------------
ENUM: List[Dict[str, str]] = [{"id": tid, "label": tlabel} for tid, tlabel in TARGETS]
ENUM_JSON: str = json.dumps(ENUM, ensure_ascii=False)

FRONTMATTER_TARGETS = {
    "title_vi",
    "title_en",
    "authors",
    "abstract_vi",
    "abstract_en",
    "keywords_vi",
    "keywords_en",
}

# -----------------------------
# Models
# -----------------------------
@dataclass
class SectionHit:
    status: str  # "ok" | "missing"
    evidence: Optional[str] = None  # heading text or "frontmatter"
    llm_verified: Optional[bool] = None
    llm_confidence: float = 0.0
    llm_label: Optional[str] = None  # predicted target id
    notes: Optional[str] = None
    references_style: Optional[str] = None  # APA/IEEE/Chicago/Vancouver/Unknown


@dataclass
class Report:
    file: str
    ok: bool
    sections: Dict[str, SectionHit]
    notes: List[str]


@dataclass
class DocPara:
    text: str
    style: str
    heading_level: int  # 0 if not heading


@dataclass
class DocSection:
    heading: str
    content: str


# -----------------------------
# Utilities
# -----------------------------
def _norm_ws(s: str) -> str:
    s = (s or "").replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _collect_header_footer_text(doc: Document) -> set[str]:
    hf_texts: set[str] = set()
    try:
        for sec in doc.sections:
            for p in sec.header.paragraphs:
                t = _norm_ws(p.text)
                if t:
                    hf_texts.add(t)
            for p in sec.footer.paragraphs:
                t = _norm_ws(p.text)
                if t:
                    hf_texts.add(t)
    except Exception:
        # Some docx have weird section defs; ignore safely.
        pass
    return hf_texts


def _heading_level_from_style(style_name: str) -> int:
    s = (style_name or "").strip().lower()

    m = re.match(r"heading\s+(\d+)", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return 0
    # Vietnamese style names (common): "Ti?u ?? 1", "Tieu de 1"
    m = re.match(r"(ti?u ??|tieu de)\s+(\d+)", s)
    if m:
        try:
            return int(m.group(2))
        except Exception:
            return 0

    return 0


def extract_docx_paragraphs(path: str) -> List[DocPara]:
    doc = Document(path)
    hf_texts = _collect_header_footer_text(doc)

    out: List[DocPara] = []
    for p in doc.paragraphs:
        t = _norm_ws(p.text)
        if not t:
            continue
        if t in hf_texts:
            continue

        style_name = ""
        try:
            style_name = (p.style.name or "")
        except Exception:
            style_name = ""

        lvl = _heading_level_from_style(style_name)
        out.append(DocPara(text=t, style=style_name, heading_level=lvl))

    return out


def split_by_heading1(paras: List[DocPara]) -> Tuple[str, List[DocSection]]:
    front_buf: List[str] = []
    sections: List[DocSection] = []

    cur_heading: Optional[str] = None
    cur_buf: List[str] = []
    seen_h1 = False

    def flush():
        nonlocal cur_heading, cur_buf
        if cur_heading is None:
            return
        content = _norm_ws("\n".join(cur_buf))
        sections.append(DocSection(heading=cur_heading, content=content))
        cur_heading = None
        cur_buf = []

    for p in paras:
        if p.heading_level == 1:
            seen_h1 = True
            flush()
            cur_heading = p.text
            cur_buf = []
            continue

        if not seen_h1:
            front_buf.append(p.text)
        else:
            if cur_heading is not None:
                if p.heading_level >= 2:
                    # Embed sub-headings into content for better LLM understanding
                    cur_buf.append(f"## {p.text}")
                else:
                    cur_buf.append(p.text)

    flush()
    return _norm_ws("\n".join(front_buf)), sections


# -----------------------------
# References style heuristic (offline)
# -----------------------------
_RE_IEEE_BRACKET = re.compile(r"^\s*\[\d+\]\s+")
_RE_VANCOUVER_NUM = re.compile(r"^\s*\d+\.\s+")
_RE_APA_YEAR = re.compile(r"\(\s*(19|20)\d{2}\s*\)")
_RE_DOI = re.compile(r"\bdoi:\s*\S+|\b10\.\d{4,9}/\S+", flags=re.IGNORECASE)


def guess_references_style(ref_text: str) -> str:
    lines = [l.strip() for l in (ref_text or "").splitlines() if l.strip()]
    if not lines:
        return "Unknown"

    sample = lines[:30]

    ieee_hits = sum(1 for l in sample if _RE_IEEE_BRACKET.search(l))
    van_hits = sum(1 for l in sample if _RE_VANCOUVER_NUM.search(l))
    apa_hits = sum(1 for l in sample if _RE_APA_YEAR.search(l))
    doi_hits = sum(1 for l in sample if _RE_DOI.search(l))

    if ieee_hits >= 3:
        return "IEEE"
    if van_hits >= 3 and ieee_hits == 0:
        return "Vancouver"
    if apa_hits >= 5 and (ieee_hits + van_hits) <= 2:
        return "APA"

    # Not confident: keep Unknown (LLM or humans decide).
    if doi_hits >= 3:
        return "Unknown"
    return "Unknown"

# -----------------------------
# LLM: classification of a chunk into target structure
# -----------------------------
def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENAI_API_KEY (or LLM_API_KEY) in .env")
    return OpenAI(api_key=api_key)


def llm_classify_chunk(
    heading: str,
    content: str,
    openai_model: str,
) -> Tuple[str, float, str]:
    excerpt = _norm_ws(content)[:2500]
    heading = _norm_ws(heading)[:200]

    # Build enum
    enum = [{"id": tid, "label": tlabel} for tid, tlabel in TARGETS]
    enum_json = json.dumps(enum, ensure_ascii=False)

    prompt = f"""Bạn là chuyên gia kiểm tra cấu trúc bài báo khoa học theo DANH MỤC CỐ ĐỊNH.

    Danh mục hợp lệ (JSON):
    {enum_json}

    Đầu vào:
    - Heading: "{heading}"
    - Nội dung thuộc heading này (trích đoạn):
    \"\"\"{excerpt}\"\"\"

    QUY TẮC PHÂN LOẠI (BẮT BUỘC TUÂN THỦ):
    1) Ưu tiên phân loại theo VAI TRÒ CẤU TRÚC của đoạn, không phải theo chủ đề.
    2) Abstract/Tóm tắt (abstract_vi/abstract_en) ĐƯỢC PHÉP chứa: mục tiêu, dữ liệu, phương pháp, kết quả chính, hàm ý/chính sách.
    3) Chỉ chọn "results" nếu đoạn này chủ yếu là phần thân bài: trình bày kết quả/diễn giải/so sánh, có chi tiết phân tích; KHÔNG có mô tả tổng quan mục tiêu + phương pháp ở mức tóm tắt.
    4) Nếu heading là "abstract" hoặc "summary" hoặc "tóm tắt" thì ƯU TIÊN chọn abstract tương ứng trừ khi nội dung rõ ràng là phần thân bài.
    5) Nếu không chắc chắn, chọn "NONE" (ưu tiên không nhầm hơn là miss).

    Nhiệm vụ:
    - Chọn MỘT id phù hợp nhất trong danh mục, hoặc "NONE".
    - Trả về confidence 0..1.
    - Trả về lý do NGẮN (1 câu) dựa trên NGỮ NGHĨA + VAI TRÒ CẤU TRÚC.

    Trả lời CHỈ JSON, đúng schema:
    {{"id": "<id hoặc NONE>", "confidence": <0..1>, "reason": "<ngắn>"}}
    """

    if not OPENAI_AVAILABLE:
        raise RuntimeError("OPENAI_AVAILABLE=False (pip install openai)")

    client = _get_openai_client()
    resp = client.chat.completions.create(
        model=openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=250,
    )
    txt = (resp.choices[0].message.content or "").strip()

    try:
        data = json.loads(txt)
        label_id = str(data.get("id") or "NONE").strip()
        conf = float(data.get("confidence") or 0.0)
        conf = max(0.0, min(1.0, conf))
        reason = str(data.get("reason") or "").strip()
        return label_id, conf, reason
    except Exception:
        m = re.search(r"\{.*\}", txt, flags=re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                label_id = str(data.get("id") or "NONE").strip()
                conf = float(data.get("confidence") or 0.0)
                conf = max(0.0, min(1.0, conf))
                reason = str(data.get("reason") or "").strip()
                return label_id, conf, reason
            except Exception:
                pass

        logger.warning("LLM returned non-JSON. Raw head=%r", txt[:200])
        return "NONE", 0.0, "LLM non-JSON output"


# -----------------------------
# Main checker
# -----------------------------
def check_structure_docx(
    path: str,
    openai_model: str = "gpt-4o-mini",
    min_confidence: float = 0.70,
) -> Report:
    p = Path(path)
    if p.suffix.lower() != ".docx":
        raise ValueError("Only .docx supported")

    paras = extract_docx_paragraphs(str(p))
    if not paras:
        return Report(file=str(p), ok=False, sections={}, notes=["Empty document"])

    frontmatter_text, h1_sections = split_by_heading1(paras)

    notes: List[str] = []
    notes.append(f"Paragraphs={len(paras)}")
    notes.append(f"Heading1 sections={len(h1_sections)}")

    # Initialize hits
    hits: Dict[str, SectionHit] = {tid: SectionHit(status="missing") for tid, _ in TARGETS}

    # -----------------------------
    # 1) Frontmatter: chunk by "\n\n" (CLEAN)
    # -----------------------------
    front_chunks: List[str] = []
    if frontmatter_text:
        front_chunks = [c.strip() for c in frontmatter_text.split("\n\n") if c.strip()]
        front_chunks = front_chunks[:20]  # cap to control cost

    if front_chunks:
        notes.append(f"Frontmatter chunks={len(front_chunks)}")
        for idx, chunk in enumerate(front_chunks):
            label_id, conf, reason = llm_classify_chunk(
                heading=f"FRONTMATTER_CHUNK_{idx+1}",
                content=chunk,
                openai_model=openai_model,
            )

            if label_id in FRONTMATTER_TARGETS and conf >= min_confidence:
                prev = hits[label_id]
                if prev.status != "ok" or conf > prev.llm_confidence:
                    hits[label_id] = SectionHit(
                        status="ok",
                        evidence="frontmatter",
                        llm_verified=True,
                        llm_confidence=conf,
                        llm_label=label_id,
                        notes=reason,
                    )

    # -----------------------------
    # 2) Heading1 sections
    # -----------------------------
    for s in h1_sections:
        label_id, conf, reason = llm_classify_chunk(
            heading=s.heading,
            content=s.content,
            openai_model=openai_model,
        )

        if label_id in hits and label_id != "NONE" and conf >= min_confidence:
            prev = hits[label_id]
            if prev.status != "ok" or conf > prev.llm_confidence:
                hits[label_id] = SectionHit(
                    status="ok",
                    evidence=s.heading,
                    llm_verified=True,
                    llm_confidence=conf,
                    llm_label=label_id,
                    notes=reason,
                )

        if label_id == "references" and conf >= min_confidence:
            hits["references"].references_style = guess_references_style(s.content)

    # -----------------------------
    # 3) Heuristic fallback for references heading match
    # -----------------------------
    if hits["references"].status != "ok":
        for s in h1_sections:
            hl = s.heading.lower()
            if "t?i li?u tham kh?o" in hl or "tai lieu tham khao" in hl or "references" in hl or "bibliography" in hl:
                hits["references"] = SectionHit(
                    status="ok",
                    evidence=s.heading,
                    llm_verified=False,
                    llm_confidence=0.0,
                    llm_label="references",
                    notes="Heuristic heading match; LLM not used or below threshold",
                    references_style=guess_references_style(s.content),
                )
                break

    # -----------------------------
    # 4) Final OK check
    # -----------------------------
    ok = True
    for tid, _ in TARGETS:
        if REQUIRED.get(tid, False) and hits[tid].status != "ok":
            ok = False
            notes.append(f"Missing required: {tid}")

    if hits["references"].status == "ok":
        rs = hits["references"].references_style or "Unknown"
        if rs not in {"APA", "IEEE", "Chicago", "Vancouver"}:
            notes.append("References style not confidently detected (APA/IEEE/Chicago/Vancouver)")

    return Report(file=str(p), ok=ok, sections=hits, notes=notes)


# -----------------------------
# CLI
# -----------------------------
def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="DOCX structure checker (Heading1 -> content -> LLM classify).")
    ap.add_argument("docx_path", help="Path to .docx")
    ap.add_argument("--json", default="", help="Write JSON output to file")
    ap.add_argument("--model", default="gpt-4o-mini", help="OpenAI model name")
    ap.add_argument("--min-conf", type=float, default=0.70, help="Min confidence to accept a match")
    args = ap.parse_args()

    report = check_structure_docx(
        args.docx_path,
        openai_model=args.model,
        min_confidence=args.min_conf,
    )

    output = {
        "file": report.file,
        "ok": report.ok,
        "sections": {k: asdict(v) for k, v in report.sections.items()},
        "notes": report.notes,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote JSON to %s", args.json)


if __name__ == "__main__":
    main()
