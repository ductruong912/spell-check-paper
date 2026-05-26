"""Turnitin/iThenticate API client.

The exact customer API contract may vary, so this client keeps the request
surface small and lets `plagiarism.checker` normalize report responses for UI.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

from utils.config import BASE_URL, CREATE_URL, DEFAULT_CREATE_PAYLOAD, MAX_WORDS_PER_SUBMISSION
from utils.validation import APIValidationError, validate_plagiarism_api_credentials

logger = logging.getLogger("plagiarism_checker")


def _require_creds() -> Tuple[str, str]:
    """Validate credentials and return (api_key, api_secret)."""
    is_valid, api_key, api_secret, error_msg = validate_plagiarism_api_credentials()
    if not is_valid:
        raise APIValidationError(error_msg, f"Turnitin API validation failed: {error_msg}")
    return str(api_key), str(api_secret)


@dataclass
class CreateResult:
    """Submission creation result."""

    report_id: str
    raw: dict


def _extract_submission_id(payload: Dict) -> str:
    report_id = (
        payload.get("id")
        or payload.get("submission_id")
        or payload.get("report_id")
        or (payload.get("data") or {}).get("id")
        or (payload.get("data") or {}).get("submission_id")
    )
    if not report_id:
        raise RuntimeError(f"API did not return submission id. Response: {payload}")
    return str(report_id)


class TurnitinClient:
    """Small wrapper around the Turnitin/iThenticate submission and report APIs."""

    def __init__(self, api_key: str, api_secret: str, session: Optional[requests.Session] = None) -> None:
        self.auth = HTTPBasicAuth(api_key, api_secret)
        self.sess = session or requests.Session()
        self.sess.headers.update({"Authorization": f"Bearer {api_key}"})

    def create_report(
        self,
        file_path: Optional[str] = None,
        text: Optional[str] = None,
        remote_id: str = "",
        payload_extra: Optional[dict] = None,
    ) -> CreateResult:
        """Create a Turnitin submission from a DOCX file or text fallback."""
        payload = dict(DEFAULT_CREATE_PAYLOAD)
        if payload_extra:
            payload.update(payload_extra)
        if remote_id:
            payload["title"] = remote_id

        if file_path:
            path = Path(file_path)
            with path.open("rb") as fh:
                files = {
                    "file": (
                        path.name,
                        fh,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                }
                response = self.sess.post(CREATE_URL, data=payload, files=files, auth=self.auth, timeout=300)
                response.raise_for_status()
                data = response.json()
            return CreateResult(report_id=_extract_submission_id(data), raw=data)

        if text is None:
            raise ValueError("Either file_path or text must be provided to create_report")

        word_count = len(text.split()) if text else 0
        if word_count > MAX_WORDS_PER_SUBMISSION:
            raise ValueError(
                f"Text exceeds API limit: {word_count} words > {MAX_WORDS_PER_SUBMISSION} words."
            )

        payload["text"] = text
        response = self.sess.post(CREATE_URL, json=payload, auth=self.auth, timeout=120)
        response.raise_for_status()
        data = response.json()
        return CreateResult(report_id=_extract_submission_id(data), raw=data)

    def get_report(self, report_id: str, show_relations: int = -2) -> dict:
        """Fetch a Turnitin originality/similarity report."""
        url = f"{BASE_URL}/submissions/{report_id}/originality"
        response = self.sess.get(
            url,
            auth=self.auth,
            params={"show_relations": show_relations},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def wait_checked(
        self,
        report_id: str,
        timeout_s: int = 600,
        poll_s: float = 5.0,
        show_relations: int = -2,
    ) -> dict:
        """Poll until the report is complete or raises on timeout/failure."""
        started_at = time.time()
        poll_count = 0
        last_status = None

        while True:
            report = self.get_report(report_id, show_relations=show_relations)
            status = str(report.get("status") or "COMPLETE").upper()
            poll_count += 1

            if status != last_status or poll_count % 10 == 0:
                elapsed = int(time.time() - started_at)
                logger.info(
                    "POLL Turnitin id=%s status=%s (poll=%d, elapsed=%ds)",
                    report_id,
                    status,
                    poll_count,
                    elapsed,
                )
                last_status = status

            if status in {"COMPLETE", "COMPLETED", "PROCESSED", "CHECKED"}:
                return report
            if status in {"ERROR", "FAILED", "FAILURE"}:
                raise RuntimeError(f"Turnitin report {report_id} failed: {report}")
            if time.time() - started_at > timeout_s:
                raise TimeoutError(f"Report {report_id} not checked after {timeout_s}s")

            time.sleep(poll_s)
