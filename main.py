import logging
import os
import re
import sys
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, field_validator

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from matching.config import load_valid_paper_config
from matching.services.valid_paper_match import (
    get_valid_paper_matcher,
    ingest_valid_titles,
    ingest_valid_keywords,
)

from config import settings
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
]

app = FastAPI(title="Article Review API", openapi_tags=TAGS_METADATA)


def _split_keywords(value: Any) -> Any:
    # Cho phép nạp keywords dạng chuỗi phân tách bằng "," hoặc ";"
    # (khớp với data nguồn lưu keywords trong một ô) ngoài dạng mảng.
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
    return value


class ValidTitleIngestRequest(BaseModel):
    titles: list[str]

class KeywordCluster(BaseModel):
    keywords: list[str] = []

    @field_validator("keywords", mode="before")
    @classmethod
    def split_keyword_string(cls, value: Any) -> Any:
        return _split_keywords(value)

class ValidKeywordIngestRequest(BaseModel):
    clusters: list[KeywordCluster]

class ValidIngestResponse(BaseModel):
    ingested_items: int
    total_items: int


class ValidPaperMatchRequest(BaseModel):
    title: str | None = None
    keywords: list[str] = []
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
    "/valid-papers/ingest/titles",
    response_model=ValidIngestResponse,
    tags=["Valid papers"],
    summary="Nạp danh sách các tiêu đề hợp lệ vào kho vector",
)
async def ingest_valid_titles_endpoint(request: ValidTitleIngestRequest) -> dict[str, int]:
    config = load_valid_paper_config()
    try:
        ingested, total = ingest_valid_titles(request.titles, config)
    except Exception as exc:
        logger.exception("Valid-title ingestion failed.")
        raise HTTPException(status_code=500, detail="Valid-title ingestion failed.") from exc

    if ingested == 0:
        raise HTTPException(status_code=422, detail="No valid titles found.")
    return {"ingested_items": ingested, "total_items": total}

@app.post(
    "/valid-papers/ingest/keywords",
    response_model=ValidIngestResponse,
    tags=["Valid papers"],
    summary="Nạp danh sách các cụm từ khóa hợp lệ vào kho vector",
)
async def ingest_valid_keywords_endpoint(request: ValidKeywordIngestRequest) -> dict[str, int]:
    config = load_valid_paper_config()
    keywords_list = [cluster.keywords for cluster in request.clusters]
    try:
        ingested, total = ingest_valid_keywords(keywords_list, config)
    except Exception as exc:
        logger.exception("Valid-keyword ingestion failed.")
        raise HTTPException(status_code=500, detail="Valid-keyword ingestion failed.") from exc

    if ingested == 0:
        raise HTTPException(status_code=422, detail="No valid keywords found.")
    return {"ingested_items": ingested, "total_items": total}


@app.post(
    "/valid-papers/match",
    response_model=ValidPaperMatchResponse,
    response_model_exclude_unset=True,
    tags=["Valid papers"],
    summary="So title + keywords bản thảo với kho bài hợp lệ (0.7 semantic + 0.3 BM25, top-5)",
)
async def match_valid_paper_endpoint(request: ValidPaperMatchRequest) -> dict[str, Any]:
    title = request.title.strip() if request.title else None
    keywords = [keyword.strip() for keyword in request.keywords if keyword and keyword.strip()]
    if not title and not keywords:
        raise HTTPException(status_code=400, detail="Provide a title and/or at least one keyword.")

    config = load_valid_paper_config()
    matcher = get_valid_paper_matcher(config)
    if matcher is None:
        raise HTTPException(
            status_code=503,
            detail="Valid-paper store is empty; ingest papers via POST /valid-papers/ingest.",
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


def _is_supported_document(filename: str) -> bool:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return suffix in set(settings.supported_extensions)


@app.post(
    "/check-structure",
    tags=["Structure"],
    summary="Phân loại cấu trúc bản thảo (DOCX/PDF)",
)
async def check_structure_endpoint(file: UploadFile = File(...)) -> dict[str, Any]:
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
        return detect_structure_bytes(filename, data)
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
