from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldKeywordMatch:
    term: str       # title/keyword của bài
    keyword: str    # từ khóa lĩnh vực gần nghĩa nhất với term
    score: float


@dataclass(frozen=True)
class FieldRelevanceResult:
    decision: str
    score: float
    semantic_score: float
    lexical_score: float
    matched_keywords: list[FieldKeywordMatch] = field(default_factory=list)


@dataclass(frozen=True)
class ValidPaperMatch:
    text: str        # title hoặc list keywords của một bài hợp lệ trong kho
    score: float     # điểm tổng hợp = semantic_weight*cosine + lexical_weight*BM25(norm)
    semantic: float
    lexical: float


@dataclass(frozen=True)
class ValidPaperSideResult:
    """Kết quả một mặt (title hoặc keywords): trung bình top_k bản ghi cao điểm nhất."""

    score: float
    matches: list[ValidPaperMatch] = field(default_factory=list)


@dataclass(frozen=True)
class ValidPaperResult:
    overall_score: float | None  # trung bình điểm title + keywords (mặt nào có)
    suitable: bool | None = None
    title: ValidPaperSideResult | None = None
    keywords: ValidPaperSideResult | None = None
