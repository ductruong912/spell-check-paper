"""Tiện ích xử lý và chuẩn hoá văn bản."""

import re


def normalize_text(text: str) -> str:
    """Chuẩn hoá khoảng trắng cho hiển thị/lưu trữ."""
    return " ".join(text.split())


def norm_ws(s: str) -> str:
    """Chuẩn khoảng trắng để so sánh chuỗi."""
    return " ".join(s.strip().split())


# ----------------------------
# Heading patterns (structure)
# ----------------------------
INTRO_HEADING = re.compile(
    r"^\s*([IVXLC]+\s*[\.\)]\s*)?(\d+(\.\d+)*)?\s*[:.\-–—]?\s*"
    r"(introduction|giới thiệu|đặt vấn đề|mở đầu)\b.*$",
    re.I,
)

REF_HEADING = re.compile(
    r"^\s*([IVXLC]+\s*[\.\)]\s*)?(\d+(\.\d+)*)?\s*[:.\-–—]?\s*"
    r"(references|bibliography|tài liệu tham khảo|works cited)\b.*$",
    re.I,
)
