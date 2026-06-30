"""Hiệu chỉnh ngưỡng field-relevance trên dữ liệu có nhãn.

Dùng đúng logic chấm điểm của production (FieldRelevanceChecker) nên ngưỡng tìm
được áp thẳng vào FIELD_SUITABLE_THRESHOLD / FIELD_REVIEW_THRESHOLD.

Quy trình:
  1. Nạp danh mục từ khóa lĩnh vực (file text), embed bằng model cần đánh giá.
  2. Chấm điểm toàn bộ bài in-field (positive) và, nếu có, bài off-field (negative).
  3. Đề xuất ngưỡng theo mục tiêu giữ lại tỉ lệ bài in-field (target recall);
     nếu có negative thì in thêm bảng quét recall/false-positive để chọn.

Chạy từ thư mục gốc repo, ví dụ:
  ./venv/Scripts/python.exe -m matching.scripts.calibrate_field_thresholds \
      --model BAAI/bge-base-en-v1.5 \
      --articles "data/ER - Article (Title - Keywords) - EN.json"
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

# Console Windows mặc định cp1252 không mã hóa được tiếng Việt khi print -> ép
# UTF-8 cho stdout/stderr để báo cáo (có dấu) không làm crash script.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Cho phép chạy như module/script độc lập: đảm bảo "src" nằm trên sys.path.
SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from matching.config import load_field_relevance_config
from matching.repositories.field_keywords import parse_field_keywords
from matching.services.embeddings import SbertEmbeddingProvider
from matching.services.field_relevance import FieldRelevanceChecker

DEFAULT_KEYWORDS = "data/Danh mục từ khóa ER.txt"
DEFAULT_ARTICLES = "data/ER - Article (Title - Keywords) - EN.json"


_HTML_TAG = re.compile(r"<[^>]+>")


def _clean_keyword(part: str) -> str:
    """Bóc thẻ HTML (vd <em>, </p>) và dấu phân cách/chấm thừa quanh một keyword.

    Dữ liệu export từ DB hay dính '</em>', '</p>', dấu ':' hoặc '.' ở đầu/cuối.
    """
    cleaned = _HTML_TAG.sub(" ", part)
    return cleaned.strip().strip(":.").strip()


def _split_keywords(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = [str(item) for item in raw]
    else:
        parts = re.split(r"[,;]", raw)
    return [cleaned for cleaned in (_clean_keyword(part) for part in parts) if cleaned]


def load_articles(path: str | Path) -> list[tuple[str, list[str]]]:
    """Đọc file bài viết. Hỗ trợ list trực tiếp hoặc dict bọc một list (export SQL)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # File export dạng {"<câu SQL>": [ {...}, ... ]}: lấy giá trị list đầu tiên.
        records = next((value for value in data.values() if isinstance(value, list)), [])
    elif isinstance(data, list):
        records = data
    else:
        records = []

    articles: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        keywords = _split_keywords(item.get("keywords"))
        if not (title or keywords):
            continue
        # Export DB hay có bản ghi trùng hệt nhau; loại để không lệch recall/FPR.
        signature = (title.casefold(), tuple(k.casefold() for k in keywords))
        if signature in seen:
            continue
        seen.add(signature)
        articles.append((title, keywords))
    return articles


def build_catalog_from_articles(articles: list[tuple[str, list[str]]]) -> list[str]:
    """Gom keywords của các bài thành danh mục lĩnh vực (dedup casefold, giữ thứ tự).

    Dùng cho đánh giá không rò rỉ: catalog được dựng từ chính keywords các bài,
    nên có thể loại đúng phần keyword của bài đang test ra khỏi catalog.
    """
    catalog: list[str] = []
    seen: set[str] = set()
    for _title, keywords in articles:
        for keyword in keywords:
            normalized = keyword.casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                catalog.append(keyword)
    return catalog


def make_folds(n: int, k: int, seed: int) -> list[list[int]]:
    """Chia n chỉ số thành k fold cân kích thước (xáo trộn theo seed cố định)."""
    indices = list(range(n))
    random.Random(seed).shuffle(indices)
    # Round-robin theo stride cho kích thước fold đều nhau nhất.
    return [indices[start::k] for start in range(k)]


def kfold_positive_scores(
    articles: list[tuple[str, list[str]]],
    k: int,
    seed: int,
    provider: SbertEmbeddingProvider,
    config,
    embedding_map: dict[str, list[float]],
) -> np.ndarray:
    """Chấm điểm positive theo k-fold không rò rỉ.

    Mỗi vòng: catalog dựng từ keywords các bài *train* (loại keyword của fold test
    bằng cách không đưa bài test vào catalog). Keyword riêng của bài test biến mất
    khỏi catalog; keyword lặp giữa các bài (tín hiệu lĩnh vực thật) vẫn còn.
    Vector lấy từ embedding_map đã embed sẵn nên không embed lại catalog mỗi vòng.
    """
    folds = make_folds(len(articles), k, seed)
    scores: list[float] = []
    for fold_no, test_indices in enumerate(folds, start=1):
        test_set = set(test_indices)
        train = [a for i, a in enumerate(articles) if i not in test_set]
        test = [articles[i] for i in test_indices]
        train_keywords = build_catalog_from_articles(train)
        train_embeddings = [embedding_map[kw.casefold()] for kw in train_keywords]
        checker = FieldRelevanceChecker(train_keywords, train_embeddings, provider, config)
        print(
            f"  fold {fold_no}/{k}: catalog={len(train_keywords)} từ khóa, "
            f"test={len(test)} bài",
            file=sys.stderr,
        )
        for title, keywords in test:
            result = checker.check(title, keywords, explain=False)
            if result is not None:
                scores.append(result.score)
    return np.array(scores, dtype=float)


def score_articles(
    checker: FieldRelevanceChecker, articles: list[tuple[str, list[str]]]
) -> np.ndarray:
    scores: list[float] = []
    for index, (title, keywords) in enumerate(articles, start=1):
        result = checker.check(title, keywords, explain=False)
        if result is not None:
            scores.append(result.score)
        if index % 50 == 0:
            print(f"  ...đã chấm {index}/{len(articles)}", file=sys.stderr)
    return np.array(scores, dtype=float)


def describe(label: str, scores: np.ndarray) -> None:
    if scores.size == 0:
        print(f"{label}: (không có dữ liệu)")
        return
    pcts = [0, 1, 2.5, 5, 10, 25, 50, 75, 90, 100]
    values = np.percentile(scores, pcts)
    print(f"{label}: n={scores.size} mean={scores.mean():.4f} std={scores.std():.4f}")
    print("  percentile: " + "  ".join(f"p{p}={v:.3f}" for p, v in zip(pcts, values)))


def recommend(
    positives: np.ndarray, negatives: np.ndarray, target_recall: float
) -> tuple[float, float]:
    """Đề xuất (suitable, review).

    - suitable: ngưỡng giữ lại `target_recall` tỉ lệ bài in-field.
    - review: ngưỡng thấp hơn để gần như mọi bài in-field tối thiểu vào 'needs_review'.
    """
    suitable = float(np.percentile(positives, (1.0 - target_recall) * 100.0))
    review = float(np.percentile(positives, max(0.0, (1.0 - target_recall) * 100.0 - 2.5)))
    review = min(review, suitable)

    if negatives.size:
        # Nếu có negative: kéo suitable lên cao hơn max(negative) khi khả thi để
        # tách hẳn nhóm off-field, miễn là không tụt recall quá nhiều.
        neg_p95 = float(np.percentile(negatives, 95))
        suitable = max(suitable, min(neg_p95, float(np.percentile(positives, 25))))
        review = min(review, suitable)
    return round(suitable, 4), round(review, 4)


def sweep(positives: np.ndarray, negatives: np.ndarray) -> None:
    print("\nBảng quét ngưỡng (recall in-field vs false-positive off-field):")
    print(f"  {'thr':>6} | {'recall':>7} | {'FPR':>7}")
    for thr in np.round(np.arange(0.30, 0.81, 0.05), 2):
        recall = float((positives >= thr).mean()) if positives.size else 0.0
        fpr = float((negatives >= thr).mean()) if negatives.size else float("nan")
        print(f"  {thr:>6.2f} | {recall:>7.3f} | {fpr:>7.3f}")


def main() -> None:
    config = load_field_relevance_config()
    parser = argparse.ArgumentParser(description="Hiệu chỉnh ngưỡng field-relevance.")
    parser.add_argument("--model", default=config.model_name, help="Tên model SentenceTransformer.")
    parser.add_argument("--prefix", default=config.model_prefix, help="Tiền tố model (vd 'query: ' cho e5).")
    parser.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="File danh mục từ khóa lĩnh vực.")
    parser.add_argument("--articles", default=DEFAULT_ARTICLES, help="File bài in-field (positive).")
    parser.add_argument("--negatives", default=None, help="File bài off-field (negative), tùy chọn.")
    parser.add_argument("--semantic-weight", type=float, default=config.semantic_weight)
    parser.add_argument("--lexical-weight", type=float, default=config.lexical_weight)
    parser.add_argument("--target-recall", type=float, default=0.975, help="Tỉ lệ giữ bài in-field.")
    parser.add_argument(
        "--kfold",
        type=int,
        default=0,
        help="Số fold cho đánh giá KHÔNG rò rỉ (>=2 để bật). Catalog dựng từ keywords "
        "các bài train; bỏ qua --keywords. 0 = dùng full catalog từ --keywords (có leakage).",
    )
    parser.add_argument("--seed", type=int, default=42, help="Seed chia fold.")
    args = parser.parse_args()

    eval_config = replace(
        config,
        model_name=args.model,
        model_prefix=args.prefix,
        semantic_weight=args.semantic_weight,
        lexical_weight=args.lexical_weight,
    )
    provider = SbertEmbeddingProvider(args.model, args.prefix)
    articles = load_articles(args.articles)
    if not articles:
        parser.error(f"Không đọc được bài nào từ {args.articles}")

    if args.kfold and args.kfold >= 2:
        # Chế độ không rò rỉ: catalog = keywords các bài train. Embed toàn bộ keyword
        # (union) một lần rồi tra theo từng fold để khỏi embed lại mỗi vòng.
        full_keywords = build_catalog_from_articles(articles)
        if not full_keywords:
            parser.error("Các bài không có keyword nào để dựng catalog k-fold.")
        print(
            f"K-fold không rò rỉ: k={args.kfold} | catalog union={len(full_keywords)} "
            f"từ khóa từ {len(articles)} bài | Model: {args.model}"
        )
        print("Đang embed catalog (union)...", file=sys.stderr)
        full_embeddings = provider.embed_texts(full_keywords)
        embedding_map = {
            kw.casefold(): vec for kw, vec in zip(full_keywords, full_embeddings)
        }
        print("Đang chấm điểm bài in-field (k-fold)...", file=sys.stderr)
        positives = kfold_positive_scores(
            articles, args.kfold, args.seed, provider, eval_config, embedding_map
        )
        # Negatives không bao giờ nằm trong catalog nên chấm trên full catalog.
        checker = FieldRelevanceChecker(
            full_keywords, full_embeddings, provider, eval_config
        )
    else:
        keywords = parse_field_keywords(Path(args.keywords).read_text(encoding="utf-8"))
        if not keywords:
            parser.error(f"Không đọc được từ khóa nào từ {args.keywords}")
        print(f"Danh mục: {len(keywords)} từ khóa | Model: {args.model}")
        print(
            "CẢNH BÁO: chế độ full catalog — nếu các bài test nằm trong danh mục thì "
            "điểm in-field bị thổi phồng (data leakage). Dùng --kfold để đánh giá trung thực.",
            file=sys.stderr,
        )
        print("Đang embed danh mục...", file=sys.stderr)
        keyword_embeddings = provider.embed_texts(keywords)
        checker = FieldRelevanceChecker(keywords, keyword_embeddings, provider, eval_config)
        print("Đang chấm điểm bài in-field...", file=sys.stderr)
        positives = score_articles(checker, articles)

    negatives = np.array([], dtype=float)
    if args.negatives:
        print("Đang chấm điểm bài off-field...", file=sys.stderr)
        negatives = score_articles(checker, load_articles(args.negatives))

    print("\n=== Phân phối điểm ===")
    describe("in-field (positive)", positives)
    describe("off-field (negative)", negatives)
    if positives.size and negatives.size:
        pooled = np.sqrt((positives.var() + negatives.var()) / 2) or 1e-9
        cohens_d = (positives.mean() - negatives.mean()) / pooled
        print(f"Khoảng cách (Cohen's d) = {cohens_d:.2f}  (càng lớn càng tách tốt)")
    sweep(positives, negatives)

    suitable, review = recommend(positives, negatives, args.target_recall)
    retained = float((positives >= suitable).mean()) if positives.size else 0.0
    print("\n=== Đề xuất ngưỡng ===")
    print(f"  (giữ ~{args.target_recall:.1%} bài in-field; thực tế recall@suitable = {retained:.1%})")
    print(f"  FIELD_SUITABLE_THRESHOLD={suitable}")
    print(f"  FIELD_REVIEW_THRESHOLD={review}")
    if negatives.size == 0:
        print("\nLưu ý: không có dữ liệu off-field nên không đo được false-positive. "
              "Cấp file --negatives để chọn ngưỡng chặt hơn.")


if __name__ == "__main__":
    main()
