from dataclasses import dataclass, field

@dataclass(frozen=True)
class ValidPaperMatch:
    text: str
    score: float
    semantic: float
    lexical: float


@dataclass(frozen=True)
class ValidPaperSideResult:
    score: float
    matches: list[ValidPaperMatch] = field(default_factory=list)


@dataclass(frozen=True)
class ValidPaperResult:
    overall_score: float | None
    suitable: bool | None = None
    title: ValidPaperSideResult | None = None
    keywords: ValidPaperSideResult | None = None
