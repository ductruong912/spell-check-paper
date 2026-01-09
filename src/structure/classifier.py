"""LLM-based section classification for academic papers."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Tuple

from utils.config import DEFAULT_LLM_MODEL
from utils.validation import validate_openai_api_key, APIValidationError
from utils.rate_limiter import rate_limit, retry_with_backoff, openai_limiter

# Logging
logger = logging.getLogger("structure_checker.classifier")

# OpenAI
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

# Constants
LLM_MAX_EXCERPT_LENGTH = 2500
LLM_MAX_HEADING_LENGTH = 200
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 250

# References style detection thresholds
REF_STYLE_IEEE_MIN_HITS = 3
REF_STYLE_VANCOUVER_MIN_HITS = 3
REF_STYLE_APA_MIN_HITS = 5
REF_STYLE_DOI_MIN_HITS = 3
REF_STYLE_SAMPLE_SIZE = 30

# Section classification targets
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
    ("appendix", "Phụ lục"),
    ("contributions", "Tuyên bố về đóng góp khoa học"),
    ("conflict_of_interest", "Cam kết về mâu thuẫn lợi ích"),
    ("acknowledgements", "Lời cảm ơn đối với cơ quan tài trợ và/hoặc tổ chức, cá nhân liên quan"),
    ("references", "Tài liệu tham khảo: APA, IEEE, Chicago, Vancouver"),
]

# Precompute enums
ENUM = [{"id": tid, "label": tlabel} for tid, tlabel in TARGETS]
ENUM_JSON = json.dumps(ENUM, ensure_ascii=False)


# -----------------------------
# References style heuristic
# -----------------------------
_RE_IEEE_BRACKET = re.compile(r"^\s*\[\d+\]\s+")
_RE_VANCOUVER_NUM = re.compile(r"^\s*\d+\.\s+")
_RE_APA_YEAR = re.compile(r"\(\s*(19|20)\d{2}\s*\)")
_RE_DOI = re.compile(r"\bdoi:\s*\S+|\b10\.\d{4,9}/\S+", flags=re.IGNORECASE)


def guess_references_style(ref_text: str) -> str:
    lines = [l.strip() for l in (ref_text or "").splitlines() if l.strip()]
    if not lines:
        return "Unknown"

    sample = lines[:REF_STYLE_SAMPLE_SIZE]
    ieee_hits = sum(1 for l in sample if _RE_IEEE_BRACKET.search(l))
    van_hits = sum(1 for l in sample if _RE_VANCOUVER_NUM.search(l))
    apa_hits = sum(1 for l in sample if _RE_APA_YEAR.search(l))
    doi_hits = sum(1 for l in sample if _RE_DOI.search(l))

    if ieee_hits >= REF_STYLE_IEEE_MIN_HITS:
        return "IEEE"
    if van_hits >= REF_STYLE_VANCOUVER_MIN_HITS and ieee_hits == 0:
        return "Vancouver"
    if apa_hits >= REF_STYLE_APA_MIN_HITS and (ieee_hits + van_hits) <= 2:
        return "APA"
    if doi_hits >= REF_STYLE_DOI_MIN_HITS:
        return "Unknown"
    return "Unknown"


# -----------------------------
# LLM Classification
# -----------------------------
def _norm_ws(s: str) -> str:
    """Normalize whitespace for LLM input."""
    s = (s or "").replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _get_openai_client():
    """Initialize OpenAI client with API key from environment."""
    is_valid, api_key, error_msg = validate_openai_api_key()
    if not is_valid:
        raise APIValidationError(error_msg, f"OpenAI API validation failed: {error_msg}")
    return OpenAI(api_key=api_key)


@rate_limit(openai_limiter)
@retry_with_backoff(max_retries=3, initial_delay=2.0)
def llm_classify_document_batch(sections: list[dict], openai_model: str) -> dict:
    """
    Classify all document sections in a single LLM call.
    
    Args:
        sections: List of dicts with 'id', 'heading', 'content'
        openai_model: OpenAI model name
    
    Returns:
        Dict mapping section_id -> {"label": str, "confidence": float, "reason": str}
    """
    # Prepare sections data for prompt
    sections_text = []
    for idx, sec in enumerate(sections):
        sec_id = sec.get("id", f"section_{idx}")
        heading = _norm_ws(sec.get("heading", ""))[:LLM_MAX_HEADING_LENGTH]
        content = _norm_ws(sec.get("content", ""))[:LLM_MAX_EXCERPT_LENGTH]
        sections_text.append(f"[ID: {sec_id}]\nHeading: \"{heading}\"\nNội dung:\n\"\"\"{content}\"\"\"")
    
    sections_input = "\n\n---\n\n".join(sections_text)
    
    prompt = f"""Bạn là chuyên gia kiểm tra cấu trúc bài báo khoa học theo DANH MỤC CỐ ĐỊNH.

Danh mục hợp lệ (JSON):
{ENUM_JSON}

Nhiệm vụ: Phân loại TẤT CẢ các sections dưới đây trong 1 lần. Mỗi section có ID riêng.

CÁC SECTION CẦN PHÂN LOẠI:
{sections_input}

QUY TẮC PHÂN LOẠI (BẮT BUỘC TUÂN THỦ):
1) Ưu tiên phân loại theo VAI TRÒ CẤU TRÚC của đoạn, không phải theo chủ đề.
2) Abstract/Tóm tắt (abstract_vi/abstract_en) ĐƯỢC PHÉP chứa: mục tiêu, dữ liệu, phương pháp, kết quả chính, hàm ý/chính sách.
3) Chỉ chọn "results" nếu đoạn này chủ yếu là phần thân bài: trình bày kết quả/diễn giải/so sánh, có chi tiết phân tích; KHÔNG có mô tả tổng quan mục tiêu + phương pháp ở mức tóm tắt.
4) Nếu heading là "abstract" hoặc "summary" hoặc "tóm tắt" thì ƯU TIÊN chọn abstract tương ứng trừ khi nội dung rõ ràng là phần thân bài.
5) Nếu không chắc chắn, chọn "NONE" (ưu tiên không nhầm hơn là miss).

Trả lời CHỈ JSON với format:
{{
  "classifications": [
    {{"id": "<section_id>", "label": "<label hoặc NONE>", "confidence": <0..1>, "reason": "<ngắn>"}},
    ...
  ]
}}
"""

    if not OPENAI_AVAILABLE:
        raise RuntimeError("OPENAI_AVAILABLE=False (pip install openai)")

    client = _get_openai_client()
    resp = client.chat.completions.create(
        model=openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS * 2,  # More tokens for batch response
    )
    txt = (resp.choices[0].message.content or "").strip()

    try:
        data = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, flags=re.DOTALL)
        if not m:
            logger.warning("LLM returned non-JSON for batch. Raw head=%r", txt[:200])
            return {}
        data = json.loads(m.group(0))

    # Parse results into dict
    results = {}
    for item in data.get("classifications", []):
        sec_id = item.get("id")
        label = str(item.get("label", "NONE")).strip()
        conf = float(item.get("confidence", 0.0))
        conf = max(0.0, min(1.0, conf))
        reason = str(item.get("reason", ""))[:100]
        
        if sec_id:
            results[sec_id] = {
                "label": label,
                "confidence": conf,
                "reason": reason
            }
    
    return results


@rate_limit(openai_limiter)
@retry_with_backoff(max_retries=3, initial_delay=2.0)
def llm_classify_chunk(heading: str, content: str, openai_model: str) -> Tuple[str, float, str]:
    """Classify a document section using LLM."""
    excerpt = _norm_ws(content)[:LLM_MAX_EXCERPT_LENGTH]
    heading = _norm_ws(heading)[:LLM_MAX_HEADING_LENGTH]

    prompt = f"""Bạn là chuyên gia kiểm tra cấu trúc bài báo khoa học theo DANH MỤC CỐ ĐỊNH.

Danh mục hợp lệ (JSON):
{ENUM_JSON}

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

Trả lời CHỈ JSON, đúng schema:
{{"id":"<id hoặc NONE>","confidence":<0..1>,"reason":"<ngắn>"}}
"""

    if not OPENAI_AVAILABLE:
        raise RuntimeError("OPENAI_AVAILABLE=False (pip install openai)")

    client = _get_openai_client()
    resp = client.chat.completions.create(
        model=openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
    )
    txt = (resp.choices[0].message.content or "").strip()

    try:
        data = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, flags=re.DOTALL)
        if not m:
            logger.warning("LLM returned non-JSON. Raw head=%r", txt[:200])
            return "NONE", 0.0, "LLM non-JSON output"
        data = json.loads(m.group(0))

    label_id = str(data.get("id") or "NONE").strip()
    conf = float(data.get("confidence") or 0.0)
    conf = max(0.0, min(1.0, conf))
    reason = str(data.get("reason") or "").strip()
    return label_id, conf, reason
