"""API validation utilities and consistent error messages in Vietnamese."""
import os
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class APIValidationError(Exception):
    """Exception raised for API configuration errors."""
    def __init__(self, message_vi: str, message_en: str):
        self.message_vi = message_vi  # User-facing Vietnamese message
        self.message_en = message_en  # Log message in English
        super().__init__(message_en)


def validate_openai_api_key() -> Tuple[bool, Optional[str], Optional[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        logger.error("OPENAI_API_KEY not found in environment")
        return False, None, "Thiếu OPENAI_API_KEY trong file .env"
    
    if not api_key.startswith("sk-"):
        logger.error("OPENAI_API_KEY has invalid format (should start with 'sk-')")
        return False, None, "OPENAI_API_KEY không hợp lệ (phải bắt đầu với 'sk-')"
    
    if len(api_key) < 20:
        logger.error("OPENAI_API_KEY is too short (invalid format)")
        return False, None, "OPENAI_API_KEY quá ngắn (không hợp lệ)"
    
    logger.debug("OPENAI_API_KEY validated successfully")  # Changed to DEBUG
    return True, api_key, None


def validate_plagiarism_api_credentials() -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    api_user = os.getenv("PLAGIARISMSEARCH_API_USER")
    api_key = os.getenv("PLAGIARISMSEARCH_API_KEY")
    
    if not api_user or not api_key:
        missing = []
        if not api_user:
            missing.append("PLAGIARISMSEARCH_API_USER")
        if not api_key:
            missing.append("PLAGIARISMSEARCH_API_KEY")
        
        logger.error(f"Missing PlagiarismSearch credentials: {', '.join(missing)}")
        return False, None, None, f"Thiếu thông tin API trong .env: {', '.join(missing)}"
    
    # Basic email validation for API_USER
    if "@" not in api_user or "." not in api_user:
        logger.error(f"PLAGIARISMSEARCH_API_USER has invalid email format: {api_user}")
        return False, None, None, "PLAGIARISMSEARCH_API_USER không đúng định dạng email"
    
    # Basic length check for API_KEY
    if len(api_key) < 30:
        logger.error("PLAGIARISMSEARCH_API_KEY is too short (likely invalid)")
        return False, None, None, "PLAGIARISMSEARCH_API_KEY quá ngắn (không hợp lệ)"
    
    logger.debug(f"PlagiarismSearch API credentials validated for user: {api_user}")  # Changed to DEBUG
    return True, api_user, api_key, None


def get_user_friendly_error(exception: Exception) -> str:
    error_str = str(exception).lower()
    
    # OpenAI API errors
    if "429" in error_str or "quota" in error_str or "rate limit" in error_str:
        logger.warning(f"OpenAI quota/rate limit exceeded: {exception}")
        return "Đã vượt quá giới hạn API của OpenAI (hạn ngạch hoặc tốc độ). Vui lòng thử lại sau."
    
    if "401" in error_str or "authentication" in error_str or "invalid_api_key" in error_str:
        logger.warning(f"OpenAI authentication failed: {exception}")
        return "Xác thực OpenAI thất bại. Vui lòng kiểm tra OPENAI_API_KEY trong .env"
    
    if "openai" in error_str and "timeout" in error_str:
        logger.warning(f"OpenAI timeout: {exception}")
        return "Kết nối OpenAI bị timeout. Vui lòng kiểm tra kết nối mạng."
    
    # PlagiarismSearch API errors
    if "plagiarism" in error_str and ("401" in error_str or "authentication" in error_str):
        logger.warning(f"PlagiarismSearch authentication failed: {exception}")
        return "Xác thực PlagiarismSearch thất bại. Vui lòng kiểm tra API credentials trong .env"
    
    if "plagiarism" in error_str and "timeout" in error_str:
        logger.warning(f"PlagiarismSearch timeout: {exception}")
        return "Kết nối PlagiarismSearch bị timeout. Vui lòng thử lại sau."
    
    # Word COM errors
    if "com" in error_str or "word" in error_str:
        logger.warning(f"Microsoft Word COM error: {exception}")
        return "Lỗi kết nối Microsoft Word. Vui lòng đảm bảo Word đã được cài đặt."
    
    # File errors
    if "file not found" in error_str or "no such file" in error_str:
        logger.error(f"File not found: {exception}")
        return "Không tìm thấy file. Vui lòng kiểm tra lại đường dẫn."
    
    if "permission" in error_str or "access denied" in error_str:
        logger.error(f"Permission denied: {exception}")
        return "Không có quyền truy cập file. Vui lòng kiểm tra quyền."
    
    # Document format errors
    if "docx" in error_str or "corrupt" in error_str:
        logger.error(f"Document format error: {exception}")
        return "File DOCX bị lỗi hoặc không hợp lệ. Vui lòng thử file khác."
    
    # Generic timeout
    if "timeout" in error_str:
        logger.warning(f"Timeout error: {exception}")
        return "Quá thời gian xử lý. Vui lòng thử lại hoặc sử dụng file nhỏ hơn."
    
    # Generic network errors
    if "connection" in error_str or "network" in error_str:
        logger.error(f"Network error: {exception}")
        return "Lỗi kết nối mạng. Vui lòng kiểm tra Internet."
    
    # Default fallback
    logger.error(f"Unhandled error: {exception}")
    return f"Lỗi không xác định: {str(exception)[:100]}"
