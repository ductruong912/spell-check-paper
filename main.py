import logging
import os
import re
import sys
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from matching.services.valid_paper_match import (
    get_valid_paper_matcher,
    replace_valid_paper_batch,
)
from reviewers.models import ReviewerProfile
from reviewers.services.reviewer_suggestion import (
    ingest_reviewers,
    parse_reviewer_titles,
    suggest_reviewers,
)
from domain_ids import normalize_domain_id

from config import load_reviewer_config, load_valid_paper_config, settings
from services import detect_structure_bytes


load_dotenv()

logger = logging.getLogger(__name__)

# Nhóm endpoint trên trang /docs — đặt tên rõ để dễ tìm thay vì để mặc định.
TAGS_METADATA = [
    {
        "name": "Structure",
    },
    {
        "name": "Valid papers",
    },
    {
        "name": "Reviewers",
    },
]

app = FastAPI(title="Article Review API", openapi_tags=TAGS_METADATA)


def _split_keywords(value: Any) -> Any:
    # Cho phép nạp keywords dạng chuỗi phân tách bằng "," hoặc ";"
    # (khớp với data nguồn lưu keywords trong một ô) ngoài dạng mảng.
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
    return value


class ValidPaperIngestItem(BaseModel):
    title: str | None = None
    keywords: list[str] = Field(default_factory=list)

    @field_validator("keywords", mode="before")
    @classmethod
    def split_keyword_string(cls, value: Any) -> Any:
        if isinstance(value, list):
            return value
        return _split_keywords(value)

class ValidBatchIngestResponse(BaseModel):
    ingested_titles: int
    ingested_keywords: int
    total_items: int


class ValidPaperMatchRequest(BaseModel):
    title: str | None = None
    keywords: list[str] = Field(default_factory=list)
    explain: bool = False

    @field_validator("keywords", mode="before")
    @classmethod
    def split_keyword_string(cls, value: Any) -> Any:
        return _split_keywords(value)


class ValidPaperMatchItem(BaseModel):
    text: str
    score: float
    semantic: float
    lexical: float


class ValidPaperSideResponse(BaseModel):
    score: float
    matches: list[ValidPaperMatchItem] | None = None


class ValidPaperMatchResponse(BaseModel):
    overall_score: float | None
    title: ValidPaperSideResponse | None = None
    keywords: ValidPaperSideResponse | None = None


class ReviewerIngestItem(BaseModel):
    user_id: int
    user: str
    article: list[str] = Field(default_factory=list)
    article_review: list[str] = Field(default_factory=list)

    @field_validator("article", "article_review", mode="before")
    @classmethod
    def split_title_string(cls, value: Any) -> list[str]:
        return parse_reviewer_titles(value)


class ReviewerIngestResponse(BaseModel):
    ingested_users: int
    total_users: int
    total_titles: int


class ReviewerSuggestRequest(BaseModel):
    title: str
    explain: bool = False


class ReviewerSuggestionItem(BaseModel):
    user_id: int
    user: str
    score: float
    authored_score: float
    reviewed_score: float
    matched_articles: list[str] | None = None
    matched_reviewed_articles: list[str] | None = None


class ReviewerSuggestionPools(BaseModel):
    pool_1: list[ReviewerSuggestionItem] = Field(default_factory=list)
    pool_2: list[ReviewerSuggestionItem] = Field(default_factory=list)
    pool_3: list[ReviewerSuggestionItem] = Field(default_factory=list)


class ReviewerSuggestResponse(BaseModel):
    suggestions: ReviewerSuggestionPools


def _normalize_domain_id(value: str) -> str:
    return normalize_domain_id(value)


def _serialize_side(side: Any, explain: bool) -> dict[str, Any] | None:
    if side is None:
        return None
    payload: dict[str, Any] = {"score": side.score}
    if explain:
        payload["matches"] = [
            {
                "text": match.text,
                "score": match.score,
                "semantic": match.semantic,
                "lexical": match.lexical,
            }
            for match in side.matches
        ]
    return payload


@app.post(
    "/valid-papers/ingest/batch",
    response_model=ValidBatchIngestResponse,
    tags=["Valid papers"],
    summary="Thay thế toàn bộ kho bài báo (Title + Keywords) cho 1 lĩnh vực",
)
async def ingest_valid_batch_endpoint(
    papers: list[ValidPaperIngestItem],
    id: str = Query(...),
) -> dict[str, int]:
    id = _normalize_domain_id(id)
    config = load_valid_paper_config()
    try:
        t_ingested, k_ingested = replace_valid_paper_batch(
            id,
            [(paper.title, paper.keywords) for paper in papers],
            config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Valid-batch ingestion failed.")
        raise HTTPException(status_code=500, detail="Valid-batch ingestion failed.") from exc

    logger.info(
        "Valid papers ingested: id=%s titles=%s keywords=%s",
        id,
        t_ingested,
        k_ingested,
    )
    return {
        "ingested_titles": t_ingested,
        "ingested_keywords": k_ingested,
        "total_items": len(papers),
    }


@app.post(
    "/valid-papers/match",
    response_model=ValidPaperMatchResponse,
    response_model_exclude_unset=True,
    tags=["Valid papers"],
    summary="So title + keywords bản thảo với kho bài hợp lệ",
)
async def match_valid_paper_endpoint(
    request: ValidPaperMatchRequest,
    id: str = Query(...),
) -> dict[str, Any]:
    id = _normalize_domain_id(id)
    title = request.title.strip() if request.title else None
    keywords = [keyword.strip() for keyword in request.keywords if keyword and keyword.strip()]
    if not title and not keywords:
        raise HTTPException(status_code=400, detail="Provide a title and/or at least one keyword.")

    config = load_valid_paper_config()
    matcher = get_valid_paper_matcher(id, config)
    if matcher is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Valid-paper store is empty; ingest papers via "
                "POST /valid-papers/ingest/batch."
            ),
        )

    try:
        result = matcher.match(title, keywords, explain=request.explain)
    except Exception as exc:
        logger.exception("Valid-paper match failed.")
        raise HTTPException(status_code=500, detail="Valid-paper match failed.") from exc

    return {
        "overall_score": result.overall_score,
        "title": _serialize_side(result.title, request.explain),
        "keywords": _serialize_side(result.keywords, request.explain),
    }


@app.post(
    "/reviewers/ingest",
    response_model=ReviewerIngestResponse,
    tags=["Reviewers"],
    summary="Nap kho chuyen gia phan bien theo title bai bao",
)
async def ingest_reviewers_endpoint(
    reviewers: list[ReviewerIngestItem],
    id: str = Query(...),
) -> dict[str, int]:
    id = _normalize_domain_id(id)
    profiles = [
        ReviewerProfile(
            user_id=item.user_id,
            user=item.user.strip(),
            articles=item.article,
            reviewed_articles=item.article_review,
        )
        for item in reviewers
        if item.user.strip()
    ]
    if not profiles:
        raise HTTPException(status_code=422, detail="No valid reviewer profiles found.")

    config = load_reviewer_config()
    try:
        ingested_users, total_titles = ingest_reviewers(id, profiles, config)
    except Exception as exc:
        logger.exception("Reviewer ingestion failed.")
        raise HTTPException(status_code=500, detail="Reviewer ingestion failed.") from exc

    if total_titles == 0:
        raise HTTPException(status_code=422, detail="No valid reviewer titles found.")

    article_embeddings = sum(
        len(parse_reviewer_titles(profile.articles)) for profile in profiles
    )
    article_review_embeddings = sum(
        len(parse_reviewer_titles(profile.reviewed_articles)) for profile in profiles
    )
    logger.info(
        "Reviewers ingested: id=%s users=%s articles=%s article_reviews=%s",
        id,
        len(profiles),
        article_embeddings,
        article_review_embeddings,
    )
    return {
        "ingested_users": ingested_users,
        "total_users": len(reviewers),
        "total_titles": total_titles,
    }


@app.post(
    "/reviewers/suggest",
    response_model=ReviewerSuggestResponse,
    response_model_exclude_none=True,
    tags=["Reviewers"],
    summary="Goi y chuyen gia phan bien theo title bai bao",
)
async def suggest_reviewers_endpoint(
    request: ReviewerSuggestRequest,
    id: str = Query(...),
) -> dict[str, Any]:
    id = _normalize_domain_id(id)
    if not request.title.strip():
        raise HTTPException(status_code=400, detail="Provide a manuscript title.")

    config = load_reviewer_config()
    try:
        suggestions = suggest_reviewers(
            id,
            request.title,
            config,
            explain=request.explain,
        )
    except Exception as exc:
        logger.exception("Reviewer suggestion failed.")
        raise HTTPException(status_code=500, detail="Reviewer suggestion failed.") from exc

    pools: dict[str, list[dict[str, Any]]] = {
        "pool_1": [],
        "pool_2": [],
        "pool_3": [],
    }
    for suggestion in suggestions:
        pools[f"pool_{suggestion.group}"].append(
            {
                "user_id": suggestion.user_id,
                "user": suggestion.user,
                "score": suggestion.score,
                "authored_score": suggestion.authored_score,
                "reviewed_score": suggestion.reviewed_score,
                "matched_articles": suggestion.matched_articles if request.explain else None,
                "matched_reviewed_articles": (
                    suggestion.matched_reviewed_articles if request.explain else None
                ),
            }
        )

    return {"suggestions": pools}


def _is_supported_document(filename: str) -> bool:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return suffix in set(settings.supported_extensions)


@app.post(
    "/check-structure",
    tags=["Structure"],
    summary="Phân loại cấu trúc bản thảo (DOCX/PDF)",
)
async def check_structure_endpoint(
    id: str = Query(...),
    file: UploadFile = File(...)
) -> dict[str, Any]:
    id = _normalize_domain_id(id)
    filename = file.filename or ""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if not _is_supported_document(filename):
        supported = ", ".join(settings.supported_extensions)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {supported}.",
        )

    try:
        return detect_structure_bytes(filename, data, id=id)
    except FuturesTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Structure check timed out (>{settings.structure_timeout_seconds}s).",
        ) from exc
    except Exception as exc:
        logger.exception("Structure classification failed.")
        raise HTTPException(status_code=500, detail="Structure check failed.") from exc


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port)
