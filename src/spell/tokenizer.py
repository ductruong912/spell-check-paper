from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

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

_HYPHENS = set("-‒–—­")

WORD_RE = re.compile(
    r"[A-Za-z"
    + re.escape(VIETNAMESE_CHARS)
    + r"]+(?:[-'][A-Za-z"
    + re.escape(VIETNAMESE_CHARS)
    + r"]+)*[`~?']*"
)


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


def _iter_hyphen_segments(token: Token) -> Iterable[Token]:
    if not any(h in token.text for h in _HYPHENS):
        yield token
        return

    seg_start = 0
    for i, ch in enumerate(token.text):
        if ch in _HYPHENS:
            if seg_start < i:
                yield Token(token.text[seg_start:i], token.start + seg_start, token.start + i)
            seg_start = i + 1
    if seg_start < len(token.text):
        yield Token(token.text[seg_start:], token.start + seg_start, token.end)


def tokenize_words(text: str, ref_span: Optional[Tuple[int, int]] = None) -> List[Token]:
    tokens: List[Token] = []

    for match in WORD_RE.finditer(text or ""):
        raw = Token(match.group(0), match.start(), match.end())
        tokens.extend(_iter_hyphen_segments(raw))

    return tokens
