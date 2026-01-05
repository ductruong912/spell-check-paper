from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import requests
from docx import Document
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

# ----------------------------
# Config & Logging
# ----------------------------
root_dir = Path(__file__).parent.parent
load_dotenv(root_dir / ".env", override=True)

logger = logging.getLogger("plagiarism_checker")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

API_USER = os.getenv("PLAGIARISMSEARCH_API_USER")
API_KEY = os.getenv("PLAGIARISMSEARCH_API_KEY")

BASE_URL = "https://plagiarismsearch.com/api/v3"
CREATE_URL = f"{BASE_URL}/reports/create"

DEFAULT_CREATE_PAYLOAD = {
    "search_web": 1,
    "search_ai": 0,
    "search_storage": 0,
    "neural": 0,  # Disable AI-based similarity detection
    "filter_references": 1,
    "filter_quotes": 1,
}

# ----------------------------
# Heading detection (robust-ish)
# ----------------------------
_HEADING_PATTERNS: Dict[str, re.Pattern] = {
    "abstract": re.compile(r"^\s*(\d+(\.\d+)*)?\s*[:.\-]?\s*(abstract|summary|tóm tắt)\s*[:.\-]?\s*$", re.I),
    "introduction": re.compile(r"^\s*(\d+(\.\d+)*)?\s*[:.\-]?\s*(introduction|giới thiệu|đặt vấn đề)\s*[:.\-]?\s*$", re.I),
    "methods": re.compile(r"^\s*(\d+(\.\d+)*)?\s*[:.\-]?\s*(methods?|methodology|phương pháp|vật liệu|phương pháp nghiên cứu)\s*[:.\-]?\s*$", re.I),
    "results": re.compile(r"^\s*(\d+(\.\d+)*)?\s*[:.\-]?\s*(results?|kết quả)\s*[:.\-]?\s*$", re.I),
    "discussion": re.compile(r"^\s*(\d+(\.\d+)*)?\s*[:.\-]?\s*(discussion|thảo luận)\s*[:.\-]?\s*$", re.I),
    "conclusion": re.compile(r"^\s*(\d+(\.\d+)*)?\s*[:.\-]?\s*(conclusion|kết luận)\s*[:.\-]?\s*$", re.I),
    "references": re.compile(r"^\s*(\d+(\.\d+)*)?\s*[:.\-]?\s*(references|bibliography|tài liệu tham khảo)\s*[:.\-]?\s*$", re.I),
}


def _require_creds() -> None:
    if not API_USER or not API_KEY:
        raise RuntimeError("Missing PLAGIARISMSEARCH_API_USER / PLAGIARISMSEARCH_API_KEY in .env")


def _norm_text(s: str) -> str:
    return (s or "").strip()


# ----------------------------
# 1) Extract sections from DOCX
# ----------------------------
def extract_sections_from_docx(path: str) -> Dict[str, str]:
    doc = Document(path)
    sections: Dict[str, str] = {}
    current: Optional[str] = None

    for p in doc.paragraphs:
        text = _norm_text(p.text)
        if not text:
            continue

        matched = None
        for sec_key, pat in _HEADING_PATTERNS.items():
            if pat.match(text):
                matched = sec_key
                break

        if matched:
            current = matched
            sections.setdefault(current, "")
            continue

        if current:
            sections[current] = (sections[current] + "\n" + text).strip() if sections[current] else text

    return sections


# ----------------------------
# API client
# ----------------------------
@dataclass
class CreateResult:
    report_id: int
    raw: dict


class PlagiarismSearchClient:
    def __init__(self, user: str, key: str, session: Optional[requests.Session] = None) -> None:
        self.auth = HTTPBasicAuth(user, key)
        self.sess = session or requests.Session()

    def create_report(self, text: str, remote_id: str, payload_extra: Optional[dict] = None) -> CreateResult:
        payload = dict(DEFAULT_CREATE_PAYLOAD)
        payload.update(payload_extra or {})
        payload["text"] = text
        payload["remote_id"] = remote_id

        logger.info(
            "Creating report with payload: %s",
            [(k, v) for k, v in payload.items() if k != "text"],
        )

        r = self.sess.post(CREATE_URL, data=payload, auth=self.auth, timeout=120)
        r.raise_for_status()
        j = r.json()

        report_id = (j.get("data") or {}).get("id")
        if not report_id:
            raise RuntimeError(f"API did not return report id. Response: {j}")

        return CreateResult(report_id=int(report_id), raw=j)

    def get_report(self, report_id: int, show_relations: int = -2) -> dict:
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
        t0 = time.time()
        while True:
            last = self.get_report(report_id, show_relations=show_relations)
            data = last.get("data") or {}
            status_label = data.get("status_label") or data.get("status_ex") or ""
            progress = data.get("progress")

            logger.info("POLL id=%s status=%s progress=%s", report_id, status_label, progress)

            if status_label == "checked":
                # Helpful debug (not too heavy)
                keys = sorted(list(data.keys()))
                logger.info("Checked report id=%s keys=%s", report_id, keys)

                sources = data.get("sources") or []
                links = data.get("links") or []
                logger.info("Checked report id=%s sources=%s links=%s", report_id, len(sources), len(links))
                return data

            if time.time() - t0 > timeout_s:
                raise TimeoutError(f"Report {report_id} not checked after {timeout_s}s")

            time.sleep(poll_s)


# ----------------------------
# 3) Main plagiarism check
# ----------------------------
def is_plagiarized_docx(
    docx_path: str,
    threshold_similarity: float = 25.0,
    min_words_per_section: int = 80,
    timeout_s: int = 600,
) -> bool:
    _require_creds()
    client = PlagiarismSearchClient(API_USER, API_KEY)

    sections = extract_sections_from_docx(docx_path)
    if not sections:
        logger.warning("No sections detected. doc=%s", docx_path)
        return False

    for name, text in sections.items():
        if name == "references":
            continue

        words = len(text.split())
        if words < min_words_per_section:
            logger.info("Skip section=%s (too short: %s words)", name, words)
            continue

        remote_id = f"{os.path.basename(docx_path)}#{name}"
        logger.info("Checking section=%s words=%s remote_id=%s", name, words, remote_id)

        created = client.create_report(text=text, remote_id=remote_id)
        logger.info("Created report id=%s", created.report_id)

        data = client.wait_checked(created.report_id, timeout_s=timeout_s, poll_s=5.0, show_relations=-2)

        similarity = data.get("similarity")
        originality = data.get("originality")
        link = data.get("link")
        report_id = data.get("id") or created.report_id

        sources = data.get("sources") or []
        links = data.get("links") or []

        logger.info(
            "RESULT id=%s similarity=%s originality=%s sources=%s links=%s",
            report_id,
            similarity,
            originality,
            len(sources),
            len(links),
        )
        if link:
            logger.info("REPORT %s", link)

        # Primary decision
        if isinstance(similarity, (int, float)) and similarity >= threshold_similarity:
            logger.warning("PLAGIARISM DETECTED section=%s similarity=%s%%", name, similarity)
            return True

        # Fallback: similarity missing but we do have matches returned
        if similarity is None and (len(sources) > 0 or len(links) > 0):
            logger.warning("MATCHES DETECTED but similarity missing. section=%s", name)
            return True

    return False


# ----------------------------
# Optional CLI
# ----------------------------
def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Plagiarism check DOCX via PlagiarismSearch API (section-wise).")
    ap.add_argument("docx_path", help="Path to .docx")
    ap.add_argument("--threshold", type=float, default=25.0, help="Similarity threshold to flag plagiarism")
    ap.add_argument("--min-words", type=int, default=80, help="Min words per section to submit")
    ap.add_argument("--timeout", type=int, default=600, help="Max seconds to wait for a report")
    args = ap.parse_args()

    flagged = is_plagiarized_docx(
        args.docx_path,
        threshold_similarity=args.threshold,
        min_words_per_section=args.min_words,
        timeout_s=args.timeout,
    )
    print("PLAGIARIZED" if flagged else "OK")


if __name__ == "__main__":
    main()
