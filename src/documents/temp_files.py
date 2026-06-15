"""Temporary document file helpers."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Iterable, List


def write_temp_document(content: bytes, file_name: str) -> str:
    """Write uploaded document bytes to a named temporary file and return its path."""
    suffix = Path(file_name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        return tmp.name


def cleanup_old_tmp_files(paths: Iterable[str], ttl_seconds: int) -> List[str]:
    """Remove existing temp files older than ttl_seconds and return paths kept."""
    now = time.time()
    kept: List[str] = []
    for path in paths:
        try:
            if os.path.exists(path):
                age = now - os.path.getmtime(path)
                if age > ttl_seconds:
                    os.remove(path)
                else:
                    kept.append(path)
        except Exception:
            kept.append(path)
    return kept
