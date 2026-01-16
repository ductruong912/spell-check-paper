"""Hàm tiện ích xử lý văn bản."""
import re


def normalize_text(text: str) -> str:
    """Chuẩn hóa khoảng trắng trong văn bản."""
    return " ".join(text.split())


def norm_ws(s: str) -> str:
    """Chuẩn khoảng trắng để so sánh."""
    return " ".join(s.strip().split())


# Heading patterns for document structure detection
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
