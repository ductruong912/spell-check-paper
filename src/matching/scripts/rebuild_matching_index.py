import sys
from pathlib import Path

# Allow running this script directly: put the project's "src" dir on sys.path so
# the top-level packages (matching, documents, config, ...) resolve.
SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from matching.repositories.article import JsonArticleRepository
from matching.config import load_matching_config
from matching.repositories.matching_index import save_articles_to_index


DEFAULT_ARTICLES_PATH = "data/journal_articles.json"


def rebuild_index(articles_path: str = DEFAULT_ARTICLES_PATH) -> int:
    config = load_matching_config()
    repository = JsonArticleRepository(articles_path)
    articles = repository.list_articles()
    save_articles_to_index(config.index_dir, articles)
    return len(articles)


if __name__ == "__main__":
    count = rebuild_index()
    print(f"Rebuilt matching index with {count} articles")
