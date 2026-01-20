"""Client PlagiarismSearch: gửi text và lấy báo cáo đạo văn."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

from utils.config import (
    BASE_URL,
    CREATE_URL,
    DEFAULT_CREATE_PAYLOAD,
    MAX_WORDS_PER_SUBMISSION,
)
from utils.validation import validate_plagiarism_api_credentials, APIValidationError
from utils.rate_limiter import rate_limit, retry_with_backoff, plagiarism_limiter

logger = logging.getLogger("plagiarism_checker")


def _require_creds() -> Tuple[str, str]:
    """Validate creds và trả (user, key)."""
    is_valid, api_user, api_key, error_msg = validate_plagiarism_api_credentials()
    if not is_valid:
        raise APIValidationError(error_msg, f"PlagiarismSearch API validation failed: {error_msg}")
    return api_user, api_key


@dataclass
class CreateResult:
    """Kết quả create report (report_id + raw response)."""
    report_id: int
    raw: dict


class PlagiarismSearchClient:
    """Client gọi PlagiarismSearch API (mỗi worker nên dùng 1 Session)."""

    def __init__(self, user: str, key: str, session: Optional[requests.Session] = None) -> None:
        self.auth = HTTPBasicAuth(user, key)
        self.sess = session or requests.Session()

    @rate_limit(plagiarism_limiter)
    @retry_with_backoff(max_retries=3, initial_delay=2.0)
    def create_report(self, text: str, remote_id: str, payload_extra: Optional[dict] = None) -> CreateResult:
        """Tạo report mới từ text."""
        word_count = len(text.split()) if text else 0
        if word_count > MAX_WORDS_PER_SUBMISSION:
            raise ValueError(
                f"Text exceeds API limit: {word_count} words > {MAX_WORDS_PER_SUBMISSION} words. "
                f"Consider reducing chunk size or splitting further."
            )

        payload = dict(DEFAULT_CREATE_PAYLOAD)
        if payload_extra:
            payload.update(payload_extra)

        payload["text"] = text
        payload["remote_id"] = remote_id

        logger.debug(
            "Creating report with payload: %s",
            [(k, v) for k, v in payload.items() if k != "text"],
        )

        try:
            r = self.sess.post(CREATE_URL, data=payload, auth=self.auth, timeout=120)
            r.raise_for_status()
            j = r.json()
        except requests.RequestException as e:
            body = getattr(getattr(e, "response", None), "text", "")
            logger.error("Create report failed: %s", e)
            if body:
                logger.error("Response body (head): %s", body[:2000])
            raise

        report_id = (j.get("data") or {}).get("id")
        if not report_id:
            raise RuntimeError(f"API did not return report id. Response: {j}")

        return CreateResult(report_id=int(report_id), raw=j)

    @rate_limit(plagiarism_limiter)
    @retry_with_backoff(max_retries=3, initial_delay=2.0)
    def get_report(self, report_id: int, show_relations: int = -2) -> dict:
        """Lấy report theo id."""
        url = f"{BASE_URL}/reports/{report_id}"
        params = {"show_relations": show_relations}
        r = self.sess.get(url, params=params, auth=self.auth, timeout=60)
        r.raise_for_status()
        return r.json()

    def wait_checked(
        self,
        report_id: int,
        timeout_s: int = 600,
        poll_s: float = 5.0,
        show_relations: int = -2,
    ) -> dict:
        """Poll đến khi status=checked hoặc timeout."""
        t0 = time.time()
        poll_count = 0
        last_status = None
        last_progress = None

        while True:
            last = self.get_report(report_id, show_relations=show_relations)
            data = last.get("data") or {}

            status_label = (data.get("status_label") or data.get("status_ex") or "").strip()
            progress = data.get("progress")
            poll_count += 1

            status_changed = (status_label != last_status) or (progress != last_progress)
            if status_changed or poll_count % 10 == 0:
                elapsed = int(time.time() - t0)
                logger.info(
                    "POLL id=%s status=%s progress=%s (poll=%d, elapsed=%ds)",
                    report_id,
                    status_label,
                    progress,
                    poll_count,
                    elapsed,
                )
                last_status = status_label
                last_progress = progress

            if status_label == "checked":
                sources = data.get("sources") or []
                links = data.get("links") or []
                logger.info("Checked report id=%s sources=%s links=%s", report_id, len(sources), len(links))
                return data

            if time.time() - t0 > timeout_s:
                raise TimeoutError(f"Report {report_id} not checked after {timeout_s}s")

            time.sleep(poll_s)
