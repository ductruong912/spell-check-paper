import logging
import os
import sys
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from matching.services.embeddings import SbertEmbeddingProvider
from matching.config import load_matching_config
from matching.services.matching_engine import MatchingEngine
from matching.repositories.matching_index import load_articles_from_index
from matching.services.metadata_validation import build_public_metadata
from matching.services.prompt import (
    OpenAIConfigurationError,
    OpenAIResponseParseError,
    extract_metadata_with_openai,
)
from matching.services.text_extractors import (
    TextExtractionError,
    UnsupportedFileTypeError,
    extract_text_from_file,
    prepare_text_for_llm,
)

from config import settings
from services import detect_structure_bytes


load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI(title="Article Review API")


class MatchResponse(BaseModel):
    article_id: str
    title: str
    keywords: list[str]
    score: float
    semantic_score: float
    lexical_score: float


class MatchingResponse(BaseModel):
    decision: str
    score: float
    semantic_score: float
    lexical_score: float
    top_matches: list[MatchResponse] | None = None


class MetadataResponse(BaseModel):
    title: str | None
    keywords: list[str]
    matching: MatchingResponse | None = None


def get_max_input_chars() -> int:
    raw_value = os.getenv("MAX_INPUT_CHARS", "60000")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="MAX_INPUT_CHARS must be an integer.") from exc
    if value <= 0:
        raise HTTPException(status_code=500, detail="MAX_INPUT_CHARS must be greater than zero.")
    return value


def ensure_openai_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is missing.")


def build_matching_response(title: str | None, keywords: list[str], explain: bool) -> dict[str, Any] | None:
    config = load_matching_config()
    articles = load_articles_from_index(config.index_dir)
    if not articles:
        return None

    provider = SbertEmbeddingProvider(config.model_name)
    engine = MatchingEngine(articles, provider, config)
    result = engine.match(title, keywords, explain=explain)
    if result is None:
        return None

    payload: dict[str, Any] = {
        "decision": result.decision,
        "score": result.score,
        "semantic_score": result.semantic_score,
        "lexical_score": result.lexical_score,
    }
    if explain:
        payload["top_matches"] = [
            {
                "article_id": match.article_id,
                "title": match.title,
                "keywords": match.keywords,
                "score": match.score,
                "semantic_score": match.semantic_score,
                "lexical_score": match.lexical_score,
            }
            for match in result.top_matches
        ]
    return payload


@app.post(
    "/extract-metadata",
    response_model=MetadataResponse,
    response_model_exclude_unset=True,
)
async def extract_metadata(
    file: UploadFile = File(...),
    explain: bool = False,
) -> dict[str, Any]:
    filename = file.filename or ""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        extracted_text = extract_text_from_file(filename, data)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TextExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prepared_text = prepare_text_for_llm(extracted_text, get_max_input_chars())
    if not prepared_text:
        raise HTTPException(status_code=422, detail="Could not extract meaningful text from file.")

    ensure_openai_api_key()
    try:
        raw_metadata = extract_metadata_with_openai(prepared_text)
    except OpenAIConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OpenAIResponseParseError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="OpenAI request failed.") from exc

    public_metadata: dict[str, Any] = build_public_metadata(raw_metadata, prepared_text)
    try:
        public_metadata["matching"] = build_matching_response(
            public_metadata["title"],
            public_metadata["keywords"],
            explain,
        )
    except Exception:
        logger.exception("Matching failed; returning metadata without matching result.")
        public_metadata["matching"] = None
    return public_metadata


def _is_supported_document(filename: str) -> bool:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return suffix in set(settings.supported_extensions)


@app.post("/check-structure")
async def check_structure_endpoint(file: UploadFile = File(...)) -> dict[str, Any]:
    """Run the LLM structure classifier on an uploaded DOCX/PDF and return its raw JSON."""
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
