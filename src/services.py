"""Application service layer for the structure-review workflow."""

from __future__ import annotations

import hashlib
import logging
import os
import httpx
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Tuple

from config import Settings, settings
from documents import DocumentPreview, DocumentView, build_document_preview, build_document_view
from documents.temp_files import write_temp_document
from structure.checker import check_structure_document
from structure.classifier import llm_detect_structure
from structure.models import StructureReport
from validation import get_user_friendly_error
from matching.config import load_valid_paper_config
from matching.services.valid_paper_match import get_valid_paper_matcher

logger = logging.getLogger(__name__)


@dataclass
class PreparedDocument:
    file_name: str
    file_size: int
    file_content: bytes
    file_signature: Tuple[str, int, str]
    source_type: str
    document_view: DocumentView
    preview: DocumentPreview
    word_count: int


def file_signature(name: str, content: bytes) -> Tuple[str, int, str]:
    digest = hashlib.sha256(content).hexdigest()
    return name, len(content), digest


def prepare_document(
    file_name: str,
    content: bytes,
    app_settings: Settings = settings,
) -> PreparedDocument:
    """Parse and preview an uploaded document without depending on Streamlit."""
    tmp_path = write_temp_document(content, file_name)
    try:
        document_view = build_document_view(tmp_path)
        try:
            preview = build_document_preview(tmp_path, content)
        except Exception as exc:
            logger.warning("Document preview failed: %s", exc, exc_info=True)
            preview = DocumentPreview(
                kind="unavailable",
                content=None,
                warning="Không thể tạo bản xem trước tài liệu.",
            )

        return PreparedDocument(
            file_name=file_name,
            file_size=len(content),
            file_content=content,
            file_signature=file_signature(file_name, content),
            source_type=document_view.source_type,
            document_view=document_view,
            preview=preview,
            word_count=len(document_view.raw_text.split()),
        )
    finally:
        try:
            os.remove(tmp_path)
        except Exception as exc:
            logger.warning("Could not remove temp file %s: %s", tmp_path, exc)


def _error_report(error: str, *, deferred_tmp_path: str | None = None) -> StructureReport:
    debug_info: dict[str, Any] = {"notes": [error]}
    if deferred_tmp_path:
        debug_info["deferred_tmp_path"] = deferred_tmp_path
    return StructureReport(
        ok=False,
        sections={},
        template_name="",
        template_version=0,
        required_ids=set(),
        debug_info=debug_info,
        error=error,
    )


def check_structure(
    prepared_document: PreparedDocument,
    app_settings: Settings = settings,
    *,
    timeout_seconds: int | None = None,
) -> StructureReport:
    """Run a structure check by calling the backend API."""
    timeout = timeout_seconds or app_settings.structure_timeout_seconds
    api_url = f"{app_settings.api_base_url.rstrip('/')}/check-structure"
    
    try:
        with httpx.Client(timeout=timeout) as client:
            files = {
                "file": (prepared_document.file_name, prepared_document.file_content)
            }
            response = client.post(api_url, files=files)
            response.raise_for_status()
            api_result = response.json()
    except httpx.TimeoutException:
        error = f"Quá thời gian xử lý (>{timeout}s)"
        return _error_report(error)
    except Exception as exc:
        logger.error("API structure check failed: %s", exc, exc_info=True)
        return _error_report(get_user_friendly_error(exc))

    # Parse response into StructureReport
    from structure.checker import _build_report, _init_hits
    from structure.template import TARGETS, REQUIRED, REQUIRED_IDS
    from structure.models import SectionHit
    
    sections = api_result.get("sections") or {}
    hits = _init_hits()
    min_confidence = app_settings.default_min_confidence

    for key, _label in TARGETS:
        item = sections.get(key) or {}
        present = bool(item.get("present", False))
        try:
            confidence = float(item.get("confidence", 0.0))
        except Exception:
            confidence = 0.0

        evidence = str(item.get("evidence") or "")
        reason = str(item.get("reason") or "")

        if present and confidence >= min_confidence:
            hits[key] = SectionHit(
                status="ok",
                evidence=evidence,
                llm_confidence=confidence,
                notes=reason,
            )
        else:
            hits[key] = SectionHit(
                status="missing",
                evidence=evidence if present else "",
                llm_confidence=confidence,
                notes=reason,
            )

    required_ids = [key for key, required in REQUIRED.items() if required]
    ok = all(hits.get(key, SectionHit(status="missing")).status == "ok" for key in required_ids)

    notes = [
        f"API check successful",
        f"file={prepared_document.file_name}"
    ]

    report = _build_report(file=prepared_document.file_name, ok=ok, sections=hits, notes=notes)
    
    # Check for domain_match in the API response
    domain_match = api_result.get("domain_match")
    if domain_match:
        report.domain_match_suitable = bool(domain_match.get("suitable", False))
        
    return report


def detect_structure_bytes(
    file_name: str,
    content: bytes,
    app_settings: Settings = settings,
    *,
    timeout_seconds: int | None = None,
) -> dict:
    """Return the raw LLM structure-classifier JSON for uploaded bytes."""
    timeout = timeout_seconds or app_settings.structure_timeout_seconds
    tmp_path = write_temp_document(content, file_name)
    executor: ThreadPoolExecutor | None = None
    try:
        document_view = build_document_view(tmp_path)
        executor = ThreadPoolExecutor(max_workers=app_settings.max_workers)
        future = executor.submit(
            llm_detect_structure,
            view_text=document_view.structured_text,
            openai_model=app_settings.default_llm_model,
        )
        result = future.result(timeout=timeout)
        
        # Thêm check domain match
        metadata = result.get("metadata", {})
        title = metadata.get("title")
        keywords = metadata.get("keywords") or []
        
        try:
            config = load_valid_paper_config()
            matcher = get_valid_paper_matcher(config)
            if matcher is not None:
                match_result = matcher.match(title, keywords, explain=False)
                domain_match_dict = {
                    "overall_score": match_result.overall_score,
                    "suitable": match_result.suitable,
                    "title": {"score": match_result.title.score} if match_result.title else None,
                    "keywords": {"score": match_result.keywords.score} if match_result.keywords else None,
                }
                result["domain_match"] = domain_match_dict
            else:
                result["domain_match"] = None
        except Exception as e:
            logger.warning("Domain match check failed: %s", e, exc_info=True)
            result["domain_match"] = None
            
        return result
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception as exc:
                logger.warning("Could not remove temp file %s: %s", tmp_path, exc)

        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
