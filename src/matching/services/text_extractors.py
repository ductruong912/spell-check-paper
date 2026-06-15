import re
from pathlib import Path

from documents import extract_text_from_bytes


SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


class UnsupportedFileTypeError(ValueError):
    pass


class TextExtractionError(ValueError):
    pass


def extract_text_from_file(filename: str, data: bytes) -> str:
    if not data:
        raise TextExtractionError("Uploaded file is empty.")

    extension = Path(filename or "").suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(f"Unsupported file type: {extension or '<none>'}")

    try:
        # File reading is shared with the structure app via the documents package.
        text = extract_text_from_bytes(filename, data)
    except Exception as exc:
        raise TextExtractionError("Could not read the uploaded file.") from exc

    if not prepare_text_for_llm(text, max_chars=len(text) if text else 0):
        raise TextExtractionError("Could not extract meaningful text from file.")
    return text


def prepare_text_for_llm(text: str, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if max_chars <= 0:
        return normalized
    return normalized[:max_chars].rstrip()
