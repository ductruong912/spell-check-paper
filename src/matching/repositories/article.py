import json
from pathlib import Path
from typing import Protocol

from ..models.matching import JournalArticle


class ArticleRepository(Protocol):
    def list_articles(self) -> list[JournalArticle]:
        ...


class JsonArticleRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def list_articles(self) -> list[JournalArticle]:
        raw_data = json.loads(self.path.read_text(encoding="utf-8"))
        articles: list[JournalArticle] = []
        for item in raw_data:
            articles.append(
                JournalArticle(
                    article_id=str(item["article_id"]),
                    title=str(item["title"]),
                    keywords=[str(keyword) for keyword in item.get("keywords", [])],
                )
            )
        return articles