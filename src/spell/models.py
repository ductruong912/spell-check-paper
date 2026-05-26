from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Issue:
    id: str
    type: str
    offset: int
    length: int
    original: str
    suggestions: List[str]
    message: str

    def to_dict(self) -> Dict:
        return asdict(self)
