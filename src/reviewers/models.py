from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReviewerProfile:
    user_id: int
    user: str
    articles: list[str] = field(default_factory=list)
    reviewed_articles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewerTitlePoint:
    user_id: int
    user: str
    source: str
    title: str
    articles: list[str]
    reviewed_articles: list[str]


@dataclass(frozen=True)
class ReviewerStoredTitle:
    user_id: int
    user: str
    source: str
    title: str
    articles: list[str]
    reviewed_articles: list[str]
    dense_vector: list[float]
    sparse_vector: Any | None = None


@dataclass(frozen=True)
class ReviewerSuggestion:
    user_id: int
    user: str
    group: int
    score: float
    authored_score: float
    reviewed_score: float
    matched_articles: list[str] = field(default_factory=list)
    matched_reviewed_articles: list[str] = field(default_factory=list)
