from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional, Tuple

from .english_languagetool import EnglishLanguageToolChecker
from .vietnamese_hunspell import VietnameseHunspellChecker
from .tokenizer import Token, tokenize_words


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    return normalized.replace("\ufeff", "").replace("\u200b", "")


def clamp_span(span: Optional[Tuple[int, int]], text_len: int) -> Optional[Tuple[int, int]]:
    if not span:
        return None
    start, end = span
    start = max(0, min(int(start), text_len))
    end = max(0, min(int(end), text_len))
    return (start, end) if end > start else None


def _checked_words(text: str, ref_span: Optional[Tuple[int, int]]) -> int:
    if not ref_span:
        return len(text.split())
    ref_start = max(0, min(ref_span[0], len(text)))
    return len(text[:ref_start].split())


def normalize_language(language: str) -> str:
    lang = (language or "en").strip().lower()
    if lang in {"en", "english", "tiếng anh", "tieng anh"}:
        return "en"
    if lang in {"vi", "vietnamese", "tiếng việt", "tieng viet"}:
        return "vi"
    raise ValueError("Spell language must be 'en' or 'vi'")


def _tokens_before_ref(tokens: List[Token], ref_span: Optional[Tuple[int, int]]) -> List[Token]:
    if not ref_span:
        return tokens
    ref_start = max(0, int(ref_span[0]))
    return [token for token in tokens if token.start < ref_start]


def _issue_priority(issue: Dict) -> int:
    issue_type = str(issue.get("type") or "")
    if issue_type.startswith("vi_"):
        return 0
    if issue_type == "en_spelling":
        return 1
    if issue_type == "unavailable":
        return 9
    return 5


def _overlaps(a: Dict, b: Dict) -> bool:
    a_start = int(a.get("offset", 0))
    a_end = a_start + int(a.get("length", 0))
    b_start = int(b.get("offset", 0))
    b_end = b_start + int(b.get("length", 0))
    if a_end <= a_start or b_end <= b_start:
        return False
    return a_start < b_end and b_start < a_end


def dedupe_issues(issues: List[Dict]) -> List[Dict]:
    ordered = sorted(
        issues or [],
        key=lambda item: (
            int(item.get("offset", 0)),
            _issue_priority(item),
            -int(item.get("length", 0)),
        ),
    )
    kept: List[Dict] = []
    for issue in ordered:
        replacement_index = None
        should_drop = False
        for idx, existing in enumerate(kept):
            if not _overlaps(issue, existing):
                continue
            if _issue_priority(issue) < _issue_priority(existing):
                replacement_index = idx
            else:
                should_drop = True
            break

        if replacement_index is not None:
            kept[replacement_index] = issue
        elif not should_drop:
            kept.append(issue)

    return sorted(kept, key=lambda item: int(item.get("offset", 0)))


def _renumber_issues(issues: List[Dict]) -> List[Dict]:
    en_count = 0
    vi_count = 0
    other_count = 0
    out: List[Dict] = []
    for issue in issues:
        item = dict(issue)
        issue_type = str(item.get("type") or "")
        if issue_type == "en_spelling":
            en_count += 1
            item["id"] = f"en_{en_count}"
        elif issue_type.startswith("vi_"):
            vi_count += 1
            item["id"] = f"vi_{vi_count}"
        else:
            other_count += 1
            item["id"] = item.get("id") or f"other_{other_count}"
        out.append(item)
    return out


def spellcheck_text(
    text: str,
    ref_span: Optional[Tuple[int, int]] = None,
    *,
    language: str = "en",
    english_checker=None,
    vietnamese_checker=None,
    is_normalized: bool = False,
) -> Dict:
    norm_text = text if is_normalized else normalize_text(text)
    norm_ref_span = clamp_span(ref_span, len(norm_text)) if ref_span else None
    selected_language = normalize_language(language)

    tokens = _tokens_before_ref(tokenize_words(norm_text), norm_ref_span)

    if selected_language == "en":
        checker = english_checker if english_checker is not None else EnglishLanguageToolChecker()
        engines = {"english": "LanguageTool"}
    else:
        checker = vietnamese_checker if vietnamese_checker is not None else VietnameseHunspellChecker()
        engines = {"vietnamese": "Hunspell"}

    issues: List[Dict] = checker.check(norm_text, tokens)

    issues = _renumber_issues(dedupe_issues(issues))
    en_errors = sum(1 for item in issues if item.get("type") == "en_spelling")
    vi_errors = sum(1 for item in issues if str(item.get("type") or "").startswith("vi_"))

    return {
        "issues": issues,
        "total_words": len(norm_text.split()),
        "checked_words": _checked_words(norm_text, norm_ref_span),
        "meta": {
            "en_errors": en_errors,
            "vi_errors": vi_errors,
            "ref_span": norm_ref_span,
            "selected_language": selected_language,
            "engines": engines,
        },
    }
