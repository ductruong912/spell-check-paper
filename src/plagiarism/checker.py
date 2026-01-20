"""Các hàm check đạo văn chính (chunk + chạy song song)."""

from __future__ import annotations

import re
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from utils.config import DEFAULT_CREATE_PAYLOAD, MAX_PARALLEL_CHECKS
from .api_client import PlagiarismSearchClient, _require_creds
from utils.config import REPORT_POLL_INTERVAL
from .chunking import (
    TextChunk,
    extract_body_chunks_from_docx,
    extract_reference_chunks_from_docx,
    get_dynamic_chunk_config,
)
from .text_extraction import _docx_paragraph_texts

logger = logging.getLogger("plagiarism_checker")


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
def _short_api_error(msg: str) -> str:
    """Rút gọn message lỗi (bỏ phần hướng dẫn đợi X giây)."""
    if not msg:
        return "Lỗi không xác định"
    msg = re.sub(r"\.?\s*Vui lòng đợi\s*\d+\s*giây.*$", ".", msg, flags=re.IGNORECASE)
    msg = re.sub(r"\.?\s*Please wait\s*\d+\s*seconds.*$", ".", msg, flags=re.IGNORECASE)
    return msg.strip()


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _web_sources_count(sources: List[dict]) -> int:
    """Đếm số nguồn web trong sources."""
    c = 0
    for s in sources or []:
        tl = (s.get("type_label") or "").lower()
        if tl == "web" or s.get("type") == 1:
            c += 1
    return c


def _pick_top_source(sources: List[dict]) -> Optional[dict]:
    """Chọn source có score cao nhất."""
    if not sources:
        return None

    def keyf(x: dict) -> float:
        return _safe_float(x.get("plagiat") or x.get("plagiarism") or 0.0, 0.0)

    return max(sources, key=keyf)


def _top_sources(sources: List[dict], k: int = 3) -> List[Dict[str, Any]]:
    """Top-K sources theo score (chuẩn hoá cho UI)."""
    if not sources:
        return []

    def score(x: dict) -> float:
        return _safe_float(x.get("plagiat") or x.get("plagiarism") or 0.0, 0.0)

    ranked = sorted((sources or []), key=score, reverse=True)

    out: List[Dict[str, Any]] = []
    for s in ranked[:k]:
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "title": (s.get("title") or "").strip() or "(Không có tiêu đề)",
                "url": (s.get("url") or "").strip(),
                "score": score(s),
                "type_label": (s.get("type_label") or "").strip(),
            }
        )
    return out


# ─────────────────────────────────────────
# Worker
# ─────────────────────────────────────────
def _process_single_chunk(
    api_user: str,
    api_key: str,
    chunk: TextChunk,
    chunk_index: int,
    docx_basename: str,
    timeout_s: int,
    section_type: str = "BODY",
    payload_extra: Optional[dict] = None,
) -> Dict[str, Any]:
    """Worker xử lý 1 chunk (mỗi worker dùng 1 Session riêng)."""
    client = PlagiarismSearchClient(api_user, api_key)

    try:
        remote_id = f"{docx_basename}#{section_type}#{chunk_index}"
        logger.debug(
            "Checking chunk=%s words=%s remote_id=%s (parallel worker)",
            chunk.label,
            chunk.words,
            remote_id,
        )

        created = client.create_report(text=chunk.text, remote_id=remote_id, payload_extra=payload_extra)
        data = client.wait_checked(created.report_id, timeout_s=timeout_s, poll_s=REPORT_POLL_INTERVAL, show_relations=-2)

        similarity = _safe_float(data.get("similarity") or 0.0, 0.0)
        try:
            checked_words = int(data.get("checked_words") or chunk.words)
        except Exception:
            checked_words = chunk.words

        sources = data.get("sources") or []
        web_sources = _web_sources_count(sources)
        top = _pick_top_source(sources)

        report_link = (data.get("link") or "").strip()
        top_url = (top or {}).get("url") or ""
        top_title = (top or {}).get("title") or ""
        top_score = _safe_float((top or {}).get("plagiat") or (top or {}).get("plagiarism") or 0.0, 0.0)

        top_sources = _top_sources(sources, k=3)

        logger.info(
            "Chunk=%s similarity=%.2f%% checked_words=%s sources=%s (parallel)",
            chunk.label,
            similarity,
            checked_words,
            len(sources),
        )

        return {
            "chunk_index": chunk_index,
            "label": chunk.label,
            "similarity": similarity,
            "checked_words": checked_words,
            "web_sources": web_sources,
            "sources_count": len(sources),
            "top_source_title": top_title,
            "top_source_url": top_url,
            "top_source_score": top_score,
            "top_sources": top_sources,
            "report_link": report_link,
            "text": (chunk.text[:500] + "...") if len(chunk.text) > 500 else chunk.text,
        }

    except Exception as e:
        raw = str(e)[:200]
        short = _short_api_error(raw)
        logger.error("Error processing chunk=%s: %s", chunk.label, raw)
        return {
            "chunk_index": chunk_index,
            "label": chunk.label,
            "similarity": 0.0,
            "checked_words": chunk.words,
            "web_sources": 0,
            "sources_count": 0,
            "top_source_title": f"ERROR: {short}",
            "top_source_url": "",
            "top_source_score": 0.0,
            "top_sources": [],
            "report_link": "",
            "text": (chunk.text[:500] + "...") if len(chunk.text) > 500 else chunk.text,
        }


# ─────────────────────────────────────────
# Public APIs
# ─────────────────────────────────────────
def check_plagiarism_body_only(
    docx_path: str,
    chunk_target_words: int = 900,
    chunk_overlap_words: int = 120,
    min_words_per_chunk: int = 80,
    timeout_s: int = 600,
    use_dynamic_chunks: bool = True,
) -> Dict[str, Any]:
    """Check đạo văn phần thân bài (chunk động + song song)."""
    api_user, api_key = _require_creds()

    full_text = "\n".join(_docx_paragraph_texts(docx_path))
    total_words = len(full_text.split())

    if use_dynamic_chunks:
        dynamic_config = get_dynamic_chunk_config(total_words)
        chunk_target_words = dynamic_config["chunk_size"]
        chunk_overlap_words = dynamic_config["overlap"]
        logger.info("Using dynamic chunking: total_words=%s config=%s", total_words, dynamic_config)

    chunks = extract_body_chunks_from_docx(
        docx_path,
        min_words_per_chunk=min_words_per_chunk,
        chunk_target_words=chunk_target_words,
        chunk_overlap_words=chunk_overlap_words,
    )
    if not chunks:
        return {
            "success": True,
            "overall_score": 0.0,
            "findings": [],
            "total_chunks": 0,
            "total_words": total_words,
        }

    findings: List[Dict[str, Any]] = []
    total_checked_words = 0
    total_weighted_similarity = 0.0

    docx_basename = os.path.basename(docx_path)
    logger.info(
        "Starting parallel plagiarism check: %d chunks, %d workers, %d total words",
        len(chunks),
        MAX_PARALLEL_CHECKS,
        total_words,
    )

    body_payload = dict(DEFAULT_CREATE_PAYLOAD)

    try:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHECKS) as executor:
            futures = {
                executor.submit(
                    _process_single_chunk,
                    api_user,
                    api_key,
                    chunk,
                    i,
                    docx_basename,
                    timeout_s,
                    "BODY",
                    body_payload,
                ): i
                for i, chunk in enumerate(chunks, start=1)
            }

            for future in as_completed(futures):
                try:
                    finding = future.result()
                    findings.append(finding)
                    cw = int(finding.get("checked_words") or 0)
                    total_checked_words += cw
                    total_weighted_similarity += _safe_float(finding.get("similarity"), 0.0) * cw
                except Exception as e:
                    logger.error("Worker error: %s", str(e))

    except Exception as e:
        logger.error("ThreadPoolExecutor error: %s", str(e))
        return {
            "success": False,
            "overall_score": 0.0,
            "findings": findings,
            "total_chunks": len(chunks),
            "total_words": total_words,
            "error": str(e),
        }

    findings.sort(key=lambda x: x.get("chunk_index", 0))

    overall_score = (total_weighted_similarity / total_checked_words / 100.0) if total_checked_words else 0.0
    logger.info(
        "Parallel plagiarism check complete: %d findings, overall=%.2f%%",
        len(findings),
        overall_score * 100.0,
    )

    return {
        "success": True,
        "overall_score": overall_score,  # 0..1
        "findings": findings,
        "total_chunks": len(chunks),
        "total_words": total_words,
    }


def check_plagiarism_full(
    docx_path: str,
    check_body: bool = True,
    check_references: bool = True,
    body_chunk_target_words: int = 900,
    body_chunk_overlap_words: int = 120,
    min_body_words_per_chunk: int = 50,
    timeout_s: int = 600,
    use_dynamic_chunks: bool = True,
) -> Dict[str, Any]:
    """Check đạo văn thân bài + tham khảo (chunk động + song song)."""
    api_user, api_key = _require_creds()

    full_text = "\n".join(_docx_paragraph_texts(docx_path))
    total_words = len(full_text.split())

    result: Dict[str, Any] = {
        "success": True,
        "overall_score": 0.0,
        "body_findings": [],
        "reference_findings": [],
        "total_chunks": 0,
        "reference_chunks": 0,
        "total_words": total_words,
    }

    total_checked_words = 0
    total_weighted_similarity = 0.0

    docx_basename = os.path.basename(docx_path)

    # BODY
    if check_body:
        if use_dynamic_chunks:
            dynamic_config = get_dynamic_chunk_config(total_words)
            body_chunk_target_words = dynamic_config["chunk_size"]
            body_chunk_overlap_words = dynamic_config["overlap"]
            logger.debug("Body: using dynamic chunking: total_words=%s config=%s", total_words, dynamic_config)

        body_chunks = extract_body_chunks_from_docx(
            docx_path,
            min_words_per_chunk=min_body_words_per_chunk,
            chunk_target_words=body_chunk_target_words,
            chunk_overlap_words=body_chunk_overlap_words,
        )

        logger.info("Body: starting parallel check: %d chunks, %d workers", len(body_chunks), MAX_PARALLEL_CHECKS)

        body_payload = dict(DEFAULT_CREATE_PAYLOAD)
        body_findings: List[Dict[str, Any]] = []

        try:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHECKS) as executor:
                futures = {
                    executor.submit(
                        _process_single_chunk,
                        api_user,
                        api_key,
                        chunk,
                        i,
                        docx_basename,
                        timeout_s,
                        "BODY",
                        body_payload,
                    ): i
                    for i, chunk in enumerate(body_chunks, start=1)
                }

                for future in as_completed(futures):
                    finding = future.result()
                    body_findings.append(finding)
                    cw = int(finding.get("checked_words") or 0)
                    total_checked_words += cw
                    total_weighted_similarity += _safe_float(finding.get("similarity"), 0.0) * cw

        except Exception as e:
            logger.error("Body parallel executor error: %s", str(e))
            result["success"] = False
            result["error"] = f"Body check error: {str(e)}"
            return result

        body_findings.sort(key=lambda x: x.get("chunk_index", 0))
        result["body_findings"] = body_findings
        result["total_chunks"] = len(body_chunks)

    # REFERENCES
    if check_references:
        ref_chunks = extract_reference_chunks_from_docx(docx_path)
        logger.info("References: starting parallel check: %d chunks, %d workers", len(ref_chunks), MAX_PARALLEL_CHECKS)

        ref_payload = dict(DEFAULT_CREATE_PAYLOAD)
        ref_payload["filter_references"] = 0
        ref_payload["filter_quotes"] = 0

        ref_findings: List[Dict[str, Any]] = []

        try:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHECKS) as executor:
                futures = {
                    executor.submit(
                        _process_single_chunk,
                        api_user,
                        api_key,
                        chunk,
                        i,
                        docx_basename,
                        timeout_s,
                        "REF",
                        ref_payload,
                    ): i
                    for i, chunk in enumerate(ref_chunks, start=1)
                }

                for future in as_completed(futures):
                    finding = future.result()
                    finding["chunk"] = finding.pop("label", "")
                    ref_findings.append(finding)

        except Exception as e:
            logger.error("Reference parallel executor error: %s", str(e))
            logger.warning("Reference check failed, continuing with body results")

        ref_findings.sort(key=lambda x: x.get("chunk_index", 0))
        result["reference_findings"] = ref_findings
        result["reference_chunks"] = len(ref_chunks)

    # OVERALL
    if total_checked_words > 0:
        result["overall_score"] = total_weighted_similarity / total_checked_words / 100.0

    logger.info(
        "Full plagiarism check complete: body=%d chunks, ref=%d chunks, overall=%.2f%%",
        len(result["body_findings"]),
        len(result["reference_findings"]),
        result["overall_score"] * 100.0,
    )

    return result
