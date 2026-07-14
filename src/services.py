"""Application service layer for the structure-review workflow."""

from __future__ import annotations

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Tuple

from config import Settings, load_valid_paper_config, settings
from documents import DocumentPreview, DocumentView, build_document_preview, build_document_view
from documents.temp_files import write_temp_document
from structure.checker import check_structure_document
from structure.classifier import llm_detect_structure
from structure.models import StructureReport
from validation import get_user_friendly_error
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


def _run_structure_check(
    tmp_path: str,
    *,
    paragraphs,
    source_type: str,
    app_settings: Settings,
    timeout_seconds: int | None,
) -> StructureReport:
    """Run the (timed) structure check on an existing temp file and clean it up."""
    timeout = timeout_seconds or app_settings.structure_timeout_seconds
    keep_tmp_for_timeout = False
    executor: ThreadPoolExecutor | None = None
    try:
        executor = ThreadPoolExecutor(max_workers=app_settings.max_workers)
        future = executor.submit(
            check_structure_document,
            tmp_path,
            openai_model=app_settings.default_llm_model,
            min_confidence=app_settings.default_min_confidence,
            parsed_paras=paragraphs,
            source_type=source_type,
        )
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            keep_tmp_for_timeout = True
            future.cancel()
            error = f"Quá thời gian xử lý (>{timeout}s)"
            return _error_report(error, deferred_tmp_path=tmp_path)
    except Exception as exc:
        logger.error("Structure service failed: %s", exc, exc_info=True)
        return _error_report(get_user_friendly_error(exc))
    finally:
        if tmp_path and not keep_tmp_for_timeout:
            try:
                os.remove(tmp_path)
            except Exception as exc:
                logger.warning("Could not remove temp file %s: %s", tmp_path, exc)

        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass


def check_structure(
    prepared_document: PreparedDocument,
    app_settings: Settings = settings,
    *,
    timeout_seconds: int | None = None,
) -> StructureReport:
    """Run a structure check for a prepared document."""
    tmp_path = write_temp_document(
        prepared_document.file_content,
        prepared_document.file_name,
    )
    return _run_structure_check(
        tmp_path,
        paragraphs=prepared_document.document_view.paragraphs,
        source_type=prepared_document.source_type,
        app_settings=app_settings,
        timeout_seconds=timeout_seconds,
    )


def detect_structure_bytes(
    file_name: str,
    content: bytes,
    app_settings: Settings = settings,
    *,
    id: str,
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
            matcher = get_valid_paper_matcher(id, config)
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
