import json
from pathlib import Path

from ..models.matching import JournalArticle


ARTICLES_FILE = "articles.json"


def save_articles_to_index(index_dir: str | Path, articles: list[JournalArticle]) -> None:
    path = Path(index_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "article_id": article.article_id,
            "title": article.title,
            "keywords": article.keywords,
        }
        for article in articles
    ]
    (path / ARTICLES_FILE).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_articles_from_index(index_dir: str | Path) -> list[JournalArticle] | None:
    path = Path(index_dir) / ARTICLES_FILE
    if not path.exists():
        return None
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    return [
        JournalArticle(
            article_id=str(item["article_id"]),
            title=str(item["title"]),
            keywords=[str(keyword) for keyword in item.get("keywords", [])],
        )
        for item in raw_data
    ]