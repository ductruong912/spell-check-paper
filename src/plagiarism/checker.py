"""Main plagiarism checking functions with parallel processing."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from utils.config import (
    DEFAULT_CREATE_PAYLOAD,
    MAX_PARALLEL_CHECKS,
)
from .api_client import PlagiarismSearchClient, _require_creds
from .chunking import TextChunk, extract_body_chunks_from_docx, extract_reference_chunks_from_docx, get_dynamic_chunk_config
from .text_extraction import _docx_paragraph_texts

logger = logging.getLogger("plagiarism_checker")


def _web_sources_count(sources: List[dict]) -> int:
    """Count web sources from sources list."""
    c = 0
    for s in sources or []:
        tl = (s.get("type_label") or "").lower()
        if tl == "web":
            c += 1
        elif s.get("type") == 1:
            c += 1
    return c


def _pick_top_source(sources: List[dict]) -> Optional[dict]:
    """Pick the top source by plagiarism percentage."""
    if not sources:
        return None

    def keyf(x: dict) -> float:
        try:
            return float(x.get("plagiat") or x.get("plagiarism") or 0.0)
        except Exception:
            return 0.0

    return max(sources, key=keyf)


def _process_single_chunk(
    client: PlagiarismSearchClient,
    chunk: TextChunk,
    chunk_index: int,
    docx_basename: str,
    timeout_s: int,
    section_type: str = "BODY",
) -> Dict[str, Any]:
    """Process a single chunk in parallel and return finding dict."""
    try:
        remote_id = f"{docx_basename}#{section_type}#{chunk_index}"
        logger.debug(
            "Checking chunk=%s words=%s remote_id=%s (parallel worker)",
            chunk.label,
            chunk.words,
            remote_id,
        )

        # Create report and wait for results
        created = client.create_report(text=chunk.text, remote_id=remote_id)
        data = client.wait_checked(
            created.report_id, timeout_s=timeout_s, poll_s=5.0, show_relations=-2
        )

        # Extract metrics
        similarity = float(data.get("similarity") or 0.0)
        checked_words = int(data.get("checked_words") or chunk.words)
        sources = data.get("sources") or []
        web_sources = _web_sources_count(sources)
        top = _pick_top_source(sources)
        report_link = data.get("link")
        top_url = (top or {}).get("url") or ""
        top_title = (top or {}).get("title") or ""
        top_score = float((top or {}).get("plagiat") or (top or {}).get("plagiarism") or 0.0)

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
            "report_link": report_link,
            "text": (chunk.text[:500] + "...") if len(chunk.text) > 500 else chunk.text,
        }
    except Exception as e:
        logger.error("Error processing chunk=%s: %s", chunk.label, str(e))
        # Return error finding
        return {
            "chunk_index": chunk_index,
            "label": chunk.label,
            "similarity": 0.0,
            "checked_words": chunk.words,
            "web_sources": 0,
            "sources_count": 0,
            "top_source_title": f"ERROR: {str(e)[:100]}",
            "top_source_url": "",
            "top_source_score": 0.0,
            "report_link": "",
            "text": (chunk.text[:500] + "...") if len(chunk.text) > 500 else chunk.text,
        }


def check_plagiarism_body_only(
    docx_path: str,
    chunk_target_words: int = 900,
    chunk_overlap_words: int = 120,
    min_words_per_chunk: int = 80,
    timeout_s: int = 600,
    use_dynamic_chunks: bool = True,
) -> Dict[str, Any]:
    """Check plagiarism in document body with dynamic chunking and parallel processing."""
    api_user, api_key = _require_creds()
    client = PlagiarismSearchClient(api_user, api_key)

    full_text = "\n".join(_docx_paragraph_texts(docx_path))
    total_words = len(full_text.split())

    # PHASE 2: Use dynamic chunking if enabled (default ON)
    if use_dynamic_chunks:
        dynamic_config = get_dynamic_chunk_config(total_words)
        chunk_target_words = dynamic_config["chunk_size"]
        chunk_overlap_words = dynamic_config["overlap"]
        logger.info(
            "Using dynamic chunking: total_words=%s config=%s",
            total_words,
            dynamic_config,
        )

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

    # PHASE 2: Parallel chunk processing instead of sequential
    docx_basename = os.path.basename(docx_path)
    logger.info(
        "Starting parallel plagiarism check: %d chunks, %d workers, %d total words",
        len(chunks),
        MAX_PARALLEL_CHECKS,
        total_words,
    )

    try:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHECKS) as executor:
            # Submit all chunk tasks
            futures = {
                executor.submit(
                    _process_single_chunk,
                    client,
                    chunk,
                    i,
                    docx_basename,
                    timeout_s,
                    "BODY",
                ): i
                for i, chunk in enumerate(chunks, start=1)
            }

            # Collect results as they complete
            for future in as_completed(futures):
                chunk_index = futures[future]
                try:
                    finding = future.result()
                    findings.append(finding)
                    total_checked_words += finding["checked_words"]
                    total_weighted_similarity += (
                        finding["similarity"] * finding["checked_words"]
                    )
                except Exception as e:
                    logger.error(
                        "Worker error for chunk %d: %s", chunk_index, str(e)
                    )

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

    # Sort findings by chunk_index for consistent output
    findings.sort(key=lambda x: x["chunk_index"])

    overall_score = (
        (total_weighted_similarity / total_checked_words / 100.0)
        if total_checked_words
        else 0.0
    )

    logger.info(
        "Parallel plagiarism check complete: %d findings, overall_score=%.2f%%",
        len(findings),
        overall_score,
    )

    return {
        "success": True,
        "overall_score": overall_score,
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
    """Check plagiarism for both body and references with dynamic chunking and parallel processing."""
    api_user, api_key = _require_creds()
    client = PlagiarismSearchClient(api_user, api_key)

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

    # Check body content
    if check_body:
        # PHASE 2: Use dynamic chunking if enabled (default ON)
        if use_dynamic_chunks:
            dynamic_config = get_dynamic_chunk_config(total_words)
            body_chunk_target_words = dynamic_config["chunk_size"]
            body_chunk_overlap_words = dynamic_config["overlap"]
            logger.debug(
                "Body: using dynamic chunking: total_words=%s config=%s",
                total_words,
                dynamic_config,
            )

        body_chunks = extract_body_chunks_from_docx(
            docx_path,
            min_words_per_chunk=min_body_words_per_chunk,
            chunk_target_words=body_chunk_target_words,
            chunk_overlap_words=body_chunk_overlap_words,
        )

        body_findings: List[Dict[str, Any]] = []
        docx_basename = os.path.basename(docx_path)

        # PHASE 2: Parallel chunk processing for body
        logger.info(
            "Body: starting parallel check: %d chunks, %d workers",
            len(body_chunks),
            MAX_PARALLEL_CHECKS,
        )

        try:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHECKS) as executor:
                futures = {
                    executor.submit(
                        _process_single_chunk,
                        client,
                        chunk,
                        i,
                        docx_basename,
                        timeout_s,
                        "BODY",
                    ): i
                    for i, chunk in enumerate(body_chunks, start=1)
                }

                for future in as_completed(futures):
                    try:
                        finding = future.result()
                        body_findings.append(finding)
                        total_checked_words += finding["checked_words"]
                        total_weighted_similarity += (
                            finding["similarity"] * finding["checked_words"]
                        )
                    except Exception as e:
                        logger.error("Body worker error: %s", str(e))

        except Exception as e:
            logger.error("Body parallel executor error: %s", str(e))
            result["success"] = False
            result["error"] = f"Body check error: {str(e)}"
            return result

        body_findings.sort(key=lambda x: x["chunk_index"])
        result["body_findings"] = body_findings
        result["total_chunks"] = len(body_chunks)

    # Check references (WITHOUT filter_references to catch plagiarism in citations)
    if check_references:
        ref_chunks = extract_reference_chunks_from_docx(docx_path)
        ref_findings: List[Dict[str, Any]] = []

        # Use custom payload that doesn't filter references
        ref_payload = dict(DEFAULT_CREATE_PAYLOAD)
        ref_payload["filter_references"] = 0  # Enable checking references
        ref_payload["filter_quotes"] = 0  # Be strict on quotes too

        # PHASE 2: Parallel processing for references too
        logger.info(
            "References: starting parallel check: %d chunks, %d workers",
            len(ref_chunks),
            MAX_PARALLEL_CHECKS,
        )

        try:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHECKS) as executor:
                futures = {}
                for i, chunk in enumerate(ref_chunks, start=1):
                    future = executor.submit(
                        _process_single_chunk,
                        client,
                        chunk,
                        i,
                        os.path.basename(docx_path),
                        timeout_s,
                        "REF",
                    )
                    futures[future] = i

                for future in as_completed(futures):
                    try:
                        finding = future.result()
                        # Rename field to match reference context
                        finding["chunk"] = finding.pop("label", "")
                        ref_findings.append(finding)
                    except Exception as e:
                        logger.error("Reference worker error: %s", str(e))

        except Exception as e:
            logger.error("Reference parallel executor error: %s", str(e))
            # Don't fail entire result if references fail
            logger.warning("Reference check failed, continuing with body results")

        ref_findings.sort(key=lambda x: x["chunk_index"])
        result["reference_findings"] = ref_findings
        result["reference_chunks"] = len(ref_chunks)

    # Calculate overall score
    if total_checked_words > 0:
        result["overall_score"] = (
            total_weighted_similarity / total_checked_words / 100.0
        )

    logger.info(
        "Full plagiarism check complete: body=%d chunks, ref=%d chunks, overall=%.2f%%",
        len(result["body_findings"]),
        len(result["reference_findings"]),
        result["overall_score"],
    )

    return result
