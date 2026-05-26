"""LLM classifier for paper structure detection."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from utils.config import DEFAULT_LLM_MODEL
from utils.validation import APIValidationError, validate_openai_api_key

from .prompt import build_structure_prompt

logger = logging.getLogger("structure_checker.classifier")

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False


# ----------------------------
# Structure targets (fixed)
# ----------------------------
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
    ("references", "Tài liệu tham khảo"),
    ("appendix", "Phụ lục"),
    ("contributions", "Tuyên bố về đóng góp khoa học"),
    ("conflict_of_interest", "Cam kết về mâu thuẫn lợi ích"),
    ("acknowledgements", "Lời cảm ơn"),
]

TARGET_IDS = [key for key, _label in TARGETS]
TARGETS_JSON = json.dumps([{"id": key, "label": label} for key, label in TARGETS], ensure_ascii=False)

_EVIDENCE_MAX_CHARS = 100
_REASON_MAX_CHARS = 100


def _norm_ws(s: str) -> str:
    """Chuẩn hoá khoảng trắng để prompt ổn định."""
    s = (s or "").replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _get_openai_client() -> OpenAI:
    """Tạo OpenAI client sau khi validate API key."""
    is_valid, api_key, error_msg = validate_openai_api_key()
    if not is_valid:
        raise APIValidationError(error_msg, f"OpenAI API validation failed: {error_msg}")
    return OpenAI(api_key=api_key)


def _safe_load_json(text: str) -> Dict[str, Any]:
    """Parse JSON “chịu lỗi” khi LLM dính text thừa."""
    txt = (text or "").strip()
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except Exception:
        match = re.search(r"\{.*\}", txt, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}


def _normalize_output(data: Dict[str, Any]) -> Dict[str, Any]:
    """Chuẩn hoá output: đủ key, clamp confidence, cắt evidence/reason."""
    out: Dict[str, Any] = {"sections": {}, "references_style": "Unknown"}

    references_style = str((data or {}).get("references_style") or "Unknown").strip()
    if references_style not in {"APA", "IEEE", "Chicago", "Vancouver", "Unknown"}:
        references_style = "Unknown"
    out["references_style"] = references_style

    sec_map = (data or {}).get("sections") or {}
    for target_id in TARGET_IDS:
        raw = sec_map.get(target_id) or {}
        present = bool(raw.get("present", False))
        try:
            confidence = float(raw.get("confidence", 0.0))
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        out["sections"][target_id] = {
            "present": present,
            "confidence": confidence,
            "evidence": str(raw.get("evidence") or "")[:_EVIDENCE_MAX_CHARS],
            "reason": str(raw.get("reason") or "")[:_REASON_MAX_CHARS],
        }

    return out


def _section_response_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["present", "confidence", "evidence", "reason"],
        "properties": {
            "present": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "evidence": {"type": "string", "maxLength": _EVIDENCE_MAX_CHARS},
            "reason": {"type": "string", "maxLength": _REASON_MAX_CHARS},
        },
    }


def _structure_response_format() -> Dict[str, Any]:
    section_props = {target_id: _section_response_schema() for target_id in TARGET_IDS}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "paper_structure_report",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sections", "references_style"],
                "properties": {
                    "sections": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": TARGET_IDS,
                        "properties": section_props,
                    },
                    "references_style": {
                        "type": "string",
                        "enum": ["APA", "IEEE", "Chicago", "Vancouver", "Unknown"],
                    },
                },
            },
        },
    }


def _build_structure_prompt(view_text: str) -> str:
    return build_structure_prompt(view_text, TARGETS_JSON)


def llm_detect_structure(*, view_text: str, openai_model: str = DEFAULT_LLM_MODEL) -> Dict[str, Any]:
    if not OPENAI_AVAILABLE:
        raise RuntimeError("OPENAI_AVAILABLE=False (pip install openai)")

    view_text = _norm_ws(view_text)
    if not view_text:
        return _normalize_output({})

    prompt = _build_structure_prompt(view_text)
    client = _get_openai_client()
    response_format = _structure_response_format()

    try:
        resp = client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=3000,
            response_format=response_format,
        )
    except TypeError:
        resp = client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

    choice = resp.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    raw_text = (choice.message.content or "").strip()
    if finish_reason != "stop":
        logger.warning(
            "LLM stopped before complete JSON: finish_reason=%s raw_head=%r raw_tail=%r",
            finish_reason,
            raw_text[:300],
            raw_text[-300:],
        )

    data = _safe_load_json(raw_text)
    if not data:
        logger.warning(
            "LLM returned invalid JSON. finish_reason=%s raw_head=%r raw_tail=%r",
            finish_reason,
            raw_text[:300],
            raw_text[-300:],
        )
        return _normalize_output({})

    return _normalize_output(data)
