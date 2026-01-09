"""Text processing utility functions."""
import re


def normalize_text(text: str) -> str:
    """Normalize whitespace in text."""
    return " ".join(text.split())


def norm_ws(s: str) -> str:
    """Normalize whitespace for comparison."""
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
