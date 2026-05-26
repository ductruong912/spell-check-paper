from __future__ import annotations

import logging
from functools import lru_cache
from typing import Dict, List

from utils.config import MAX_SUGGESTIONS

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


def _is_spelling_match(match) -> bool:
    issue_type = (getattr(match, "ruleIssueType", "") or "").lower()
    category = (getattr(match, "category", "") or "").lower()
    rule_id = (getattr(match, "ruleId", "") or "").lower()
    return (
        "misspell" in issue_type
        or "typo" in category
        or "spell" in category
        or "morfologik" in rule_id
    )


class EnglishLanguageToolChecker:
    def check(self, text: str, tokens: List[Token]) -> List[Dict]:
        if not tokens:
            return []

        try:
            tool = _get_language_tool()
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
        cache: Dict[str, List] = {}
        for token in tokens:
            word = token.text
            key = word.lower()
            if key not in cache:
                try:
                    cache[key] = [m for m in tool.check(word) if _is_spelling_match(m)]
                except Exception:
                    log.debug("LanguageTool check failed for %r", word, exc_info=True)
                    cache[key] = []

            if not cache[key]:
                continue

            match = cache[key][0]
            issues.append(
                Issue(
                    id="en_languagetool",
                    type="en_spelling",
                    offset=token.start,
                    length=token.length,
                    original=word,
                    suggestions=_match_replacements(match),
                    message="English spelling error (LanguageTool)",
                ).to_dict()
            )

        return issues
