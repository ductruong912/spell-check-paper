import re
from typing import Any


PublicMetadata = dict[str, str | list[str] | None]


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def evidence_matches(source_text: str, evidence: str | None) -> bool:
    normalized_source = normalize_text(source_text)
    normalized_evidence = normalize_text(evidence)
    return bool(normalized_source and normalized_evidence and normalized_evidence in normalized_source)


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def build_public_metadata(raw_metadata: dict[str, Any], source_text: str) -> PublicMetadata:
    title = None
    raw_title = raw_metadata.get("title")
    if isinstance(raw_title, dict):
        title_value = _clean_string(raw_title.get("value"))
        if title_value:
            title = title_value

    keywords: list[str] = []
    seen_keywords: set[str] = set()
    raw_keywords = raw_metadata.get("keywords")
    if isinstance(raw_keywords, list):
        for raw_keyword in raw_keywords:
            if not isinstance(raw_keyword, dict):
                continue
            keyword_value = _clean_string(raw_keyword.get("value"))
            keyword_evidence = _clean_string(raw_keyword.get("evidence"))
            normalized_keyword = normalize_text(keyword_value)
            if not keyword_value or not normalized_keyword:
                continue
            if normalized_keyword in seen_keywords:
                continue
            if not evidence_matches(source_text, keyword_evidence):
                continue
            seen_keywords.add(normalized_keyword)
            keywords.append(keyword_value)

    return {"title": title, "keywords": keywords}
