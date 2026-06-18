"""Plain-text extraction helpers shared across the project.

The structure app parses documents into a rich :class:`DocumentView`; the
journal-matching code only needs the flat text. Both now go through the same
parser so PDF/DOCX reading lives in one place.
"""

from __future__ import annotations

import os

from .parser import build_document_view
from .temp_files import write_temp_document


def extract_text(path: str) -> str:
    """Return the normalized full text of a document on disk."""
    return build_document_view(path).raw_text


def extract_text_from_bytes(file_name: str, content: bytes) -> str:
    """Return the normalized full text of in-memory document bytes."""
    tmp_path = write_temp_document(content, file_name)
    try:
        return extract_text(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
