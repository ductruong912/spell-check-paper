from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from docx import Document
from dotenv import load_dotenv

root_dir = Path(__file__).parent.parent
load_dotenv(root_dir / ".env", override=True)

logger = logging.getLogger("document_backend")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def extract_text_from_docx(path: str) -> str:
    """Extract non-empty paragraphs from a DOCX file."""
    try:
        if not path or not isinstance(path, str):
            logger.error("Invalid path: %s", path)
            return ""

        docx_path = Path(path)
        if not docx_path.exists():
            logger.error("File not found: %s", path)
            return ""

        logger.debug("Extracting text from: %s", path)
        doc = Document(path)
        parts: List[str] = []
        for paragraph in doc.paragraphs:
            text = (paragraph.text or "").strip()
            if text:
                parts.append(text)

        result = "\n".join(parts)
        logger.debug("Extracted %d chars from %s", len(result), docx_path.name)
        return result

    except FileNotFoundError as exc:
        logger.error("File not found: %s: %s", path, exc)
        return ""
    except Exception as exc:
        logger.error("Error extracting text from %s: %s", path, exc, exc_info=True)
        return ""
