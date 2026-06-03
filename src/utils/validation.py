"""Xác thực API và map lỗi kỹ thuật -> thông báo tiếng Việt."""

import logging
from typing import Optional, Tuple

from .config import OPENAI_API_KEY

logger = logging.getLogger(__name__)


class APIValidationError(Exception):
    """Lỗi cấu hình API (kèm message VI/EN)."""

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
    """Map lỗi phổ biến sang thông báo dễ hiểu (best-effort)."""
    error_str = str(exception).lower()

    # OpenAI errors
    if "429" in error_str or "quota" in error_str or "rate limit" in error_str:
        logger.warning(f"OpenAI quota/rate limit exceeded: {exception}")
        return "Đã vượt quá giới hạn API của OpenAI (hạn ngạch hoặc tốc độ). Vui lòng thử lại sau."

    if "401" in error_str or "authentication" in error_str or "invalid_api_key" in error_str:
        logger.warning(f"OpenAI authentication failed: {exception}")
        return "Xác thực OpenAI thất bại. Vui lòng kiểm tra OPENAI_API_KEY trong .env"

    if "openai" in error_str and "timeout" in error_str:
        logger.warning(f"OpenAI timeout: {exception}")
        return "Kết nối OpenAI bị timeout. Vui lòng kiểm tra kết nối mạng."

    # File I/O
    if "file not found" in error_str or "no such file" in error_str:
        logger.error(f"File not found: {exception}")
        return "Không tìm thấy file. Vui lòng kiểm tra lại đường dẫn."

    if "permission" in error_str or "access denied" in error_str:
        logger.error(f"Permission denied: {exception}")
        return "Không có quyền truy cập file. Vui lòng kiểm tra quyền."

    # DOCX/format
    if "docx" in error_str or "corrupt" in error_str:
        logger.error(f"Document format error: {exception}")
        return "File DOCX bị lỗi hoặc không hợp lệ. Vui lòng thử file khác."

    # Generic timeout/network
    if "timeout" in error_str:
        logger.warning(f"Timeout error: {exception}")
        return "Quá thời gian xử lý. Vui lòng thử lại hoặc sử dụng file nhỏ hơn."

    if "connection" in error_str or "network" in error_str:
        logger.error(f"Network error: {exception}")
        return "Lỗi kết nối mạng. Vui lòng kiểm tra Internet."

    logger.error(f"Unhandled error: {exception}")
    return f"Lỗi không xác định: {str(exception)[:100]}"
