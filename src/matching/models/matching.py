from dataclasses import dataclass, field


@dataclass(frozen=True)
class JournalArticle:
    article_id: str
    title: str
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchScore:
    article_id: str
    title: str
    keywords: list[str]
    score: float
    semantic_score: float
    lexical_score: float


@dataclass(frozen=True)
class MatchingResult:
    decision: str
    score: float
    semantic_score: float
    lexical_score: float
    top_matches: list[MatchScore] = field(default_factory=list)