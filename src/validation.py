"""OpenAI API access: validate configuration, build the client, map errors."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from config import OPENAI_API_KEY, settings

logger = logging.getLogger(__name__)


class APIValidationError(Exception):
    """API configuration error with Vietnamese and English messages."""

    def __init__(self, message_vi: str, message_en: str):
        self.message_vi = message_vi
        self.message_en = message_en
        super().__init__(message_en)


def validate_openai_api_key() -> Tuple[bool, Optional[str], Optional[str]]:
    api_key = OPENAI_API_KEY

    if not api_key:
        logger.error("OPENAI_API_KEY not found in .env")
        return False, None, "Thiếu OPENAI_API_KEY trong file .env"

    if not api_key.startswith("sk-"):
        logger.error("OPENAI_API_KEY has invalid format (should start with 'sk-')")
        return False, None, "OPENAI_API_KEY không hợp lệ (phải bắt đầu với 'sk-')"

    if len(api_key) < 20:
        logger.error("OPENAI_API_KEY is too short (invalid format)")
        return False, None, "OPENAI_API_KEY quá ngắn (không hợp lệ)"

    logger.debug("OPENAI_API_KEY validated successfully")
    return True, api_key, None


def get_user_friendly_error(exception: Exception) -> str:
    """Map common technical errors to a Vietnamese message."""
    error_str = str(exception).lower()

    if "429" in error_str or "quota" in error_str or "rate limit" in error_str:
        logger.warning("OpenAI quota/rate limit exceeded: %s", exception)
        return "Đã vượt quá giới hạn API của OpenAI. Vui lòng thử lại sau."

    if "401" in error_str or "authentication" in error_str or "invalid_api_key" in error_str:
        logger.warning("OpenAI authentication failed: %s", exception)
        return "Xác thực OpenAI thất bại. Vui lòng kiểm tra OPENAI_API_KEY trong .env."

    if "openai" in error_str and "timeout" in error_str:
        logger.warning("OpenAI timeout: %s", exception)
        return "Kết nối OpenAI bị timeout. Vui lòng kiểm tra kết nối mạng."

    if "file not found" in error_str or "no such file" in error_str:
        logger.error("File not found: %s", exception)
        return "Không tìm thấy file. Vui lòng kiểm tra lại đường dẫn."

    if "permission" in error_str or "access denied" in error_str:
        logger.error("Permission denied: %s", exception)
        return "Không có quyền truy cập file. Vui lòng kiểm tra quyền."

    if "docx" in error_str or "pdf" in error_str or "corrupt" in error_str:
        logger.error("Document format error: %s", exception)
        return "File tài liệu bị lỗi hoặc không hợp lệ. Vui lòng thử file khác."

    if "timeout" in error_str:
        logger.warning("Timeout error: %s", exception)
        return "Quá thời gian xử lý. Vui lòng thử lại hoặc sử dụng file nhỏ hơn."

    if "connection" in error_str or "network" in error_str:
        logger.error("Network error: %s", exception)
        return "Lỗi kết nối mạng. Vui lòng kiểm tra Internet."

    logger.error("Unhandled error: %s", exception)
    return f"Lỗi không xác định: {str(exception)[:100]}"


def create_openai_client():
    """Validate the configured API key and return an OpenAI client."""
    from openai import OpenAI

    is_valid, api_key, error_msg = validate_openai_api_key()
    if not is_valid:
        raise APIValidationError(error_msg, f"OpenAI API validation failed: {error_msg}")
    return OpenAI(api_key=api_key)


def resolve_model(model: Optional[str] = None) -> str:
    """Return the explicit model if given, otherwise the configured default."""
    if model and model.strip():
        return model.strip()
    return settings.default_llm_model
