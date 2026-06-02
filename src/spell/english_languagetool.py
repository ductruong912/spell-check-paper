from __future__ import annotations

import logging
from functools import lru_cache
from typing import Dict, List, Tuple

from utils.config import MAX_SUGGESTIONS, SPELL_CHECK_CHUNK_SIZE, SPELL_CHECK_MIN_CHUNK_SIZE

from .models import Issue
from .tokenizer import Token

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_language_tool():
    import language_tool_python

    return language_tool_python.LanguageTool("en-US")


def _match_replacements(match) -> List[str]:
    replacements = getattr(match, "replacements", None) or []
    return [str(item) for item in replacements[:MAX_SUGGESTIONS]]


def _match_attr(match, *names: str, default=""):
    for name in names:
        value = getattr(match, name, None)
        if value not in (None, ""):
            return value
    return default


def _is_spelling_match(match) -> bool:
    issue_type = str(_match_attr(match, "rule_issue_type", "ruleIssueType")).lower()
    category = str(_match_attr(match, "category")).lower()
    rule_id = str(_match_attr(match, "rule_id", "ruleId")).lower()
    return (
        "misspell" in issue_type
        or "typo" in category
        or "spell" in category
        or "morfologik" in rule_id
    )


def _paragraph_ranges(text: str) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    start = 0
    for part in text.splitlines(keepends=True):
        end = start + len(part)
        if part.strip():
            leading = len(part) - len(part.lstrip())
            trailing = len(part.rstrip())
            ranges.append((start + leading, start + trailing))
        start = end

    if not ranges and text.strip():
        leading = len(text) - len(text.lstrip())
        trailing = len(text.rstrip())
        ranges.append((leading, trailing))

    return ranges


def _split_long_range(
    text: str,
    start: int,
    end: int,
    chunk_size: int,
    min_chunk_size: int,
) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    cursor = start

    while cursor < end:
        target = min(cursor + chunk_size, end)
        if target < end:
            split_at = text.rfind(" ", cursor + min_chunk_size, target + 1)
            if split_at <= cursor:
                split_at = target
            target = split_at

        chunk_start = cursor
        chunk_end = target
        while chunk_start < chunk_end and text[chunk_start].isspace():
            chunk_start += 1
        while chunk_end > chunk_start and text[chunk_end - 1].isspace():
            chunk_end -= 1

        if chunk_end > chunk_start:
            ranges.append((chunk_start, chunk_end))

        cursor = max(target + 1, chunk_end + 1) if target < end else end

    return ranges


def _chunk_ranges(text: str, chunk_size: int, min_chunk_size: int) -> List[Tuple[int, int]]:
    chunks: List[Tuple[int, int]] = []
    for start, end in _paragraph_ranges(text):
        if end - start <= chunk_size:
            chunks.append((start, end))
        else:
            chunks.extend(_split_long_range(text, start, end, chunk_size, min_chunk_size))
    return chunks


def _checked_text_end(text: str, tokens: List[Token]) -> int:
    end = max(token.end for token in tokens)
    while end < len(text) and not text[end].isalnum():
        end += 1
    return end


class EnglishLanguageToolChecker:
    def __init__(
        self,
        language_tool=None,
        chunk_size: int = SPELL_CHECK_CHUNK_SIZE,
        min_chunk_size: int = SPELL_CHECK_MIN_CHUNK_SIZE,
    ):
        self.language_tool = language_tool
        self.chunk_size = max(1, int(chunk_size or SPELL_CHECK_CHUNK_SIZE))
        self.min_chunk_size = max(1, int(min_chunk_size or SPELL_CHECK_MIN_CHUNK_SIZE))

    def check(self, text: str, tokens: List[Token]) -> List[Dict]:
        if not tokens:
            return []

        try:
            tool = self.language_tool if self.language_tool is not None else _get_language_tool()
        except Exception as exc:
            log.exception("Could not start LanguageTool")
            return [
                Issue(
                    id="en_languagetool_unavailable",
                    type="unavailable",
                    offset=0,
                    length=0,
                    original="",
                    suggestions=[],
                    message=f"LanguageTool unavailable: {exc}",
                ).to_dict()
            ]

        issues: List[Dict] = []
        checked_end = _checked_text_end(text or "", tokens)
        checked_text = (text or "")[:checked_end]

        for chunk_start, chunk_end in _chunk_ranges(checked_text, self.chunk_size, self.min_chunk_size):
            chunk = checked_text[chunk_start:chunk_end]
            try:
                matches = [match for match in tool.check(chunk) if _is_spelling_match(match)]
            except Exception:
                log.debug("LanguageTool check failed for chunk at %s:%s", chunk_start, chunk_end, exc_info=True)
                continue

            for match in matches:
                rel_offset = int(getattr(match, "offset", 0) or 0)
                length = int(_match_attr(match, "error_length", "errorLength", default=0) or 0)
                if length <= 0:
                    length = len(str(_match_attr(match, "matched_text", "matchedText")))
                if rel_offset < 0 or length <= 0:
                    continue

                abs_offset = chunk_start + rel_offset
                if abs_offset < chunk_start or abs_offset + length > chunk_end:
                    continue

                original = checked_text[abs_offset : abs_offset + length]
                issues.append(
                    Issue(
                        id="en_languagetool",
                        type="en_spelling",
                        offset=abs_offset,
                        length=length,
                        original=original,
                        suggestions=_match_replacements(match),
                        message="English spelling error (LanguageTool)",
                    ).to_dict()
                )

        return issues
