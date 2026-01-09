"""Unit tests for validation utilities."""
import unittest
import os
from utils.validation import (
    validate_openai_api_key,
    validate_plagiarism_api_credentials,
    get_user_friendly_error,
    APIValidationError
)


class TestOpenAIValidation(unittest.TestCase):
    """Test OpenAI API key validation."""
    
    def setUp(self):
        """Save original env var."""
        self.original_key = os.getenv("OPENAI_API_KEY")
    
    def tearDown(self):
        """Restore original env var."""
        if self.original_key:
            os.environ["OPENAI_API_KEY"] = self.original_key
        elif "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
    
    def test_valid_key(self):
        """Test validation with valid API key."""
        os.environ["OPENAI_API_KEY"] = "sk-" + "x" * 40
        is_valid, api_key, error_msg = validate_openai_api_key()
        
        self.assertTrue(is_valid, "Should be valid")
        self.assertIsNotNone(api_key, "Should return API key")
        self.assertIsNone(error_msg, "Should have no error message")
    
    def test_missing_key(self):
        """Test validation with missing API key."""
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
        
        is_valid, api_key, error_msg = validate_openai_api_key()
        
        self.assertFalse(is_valid, "Should be invalid")
        self.assertIsNone(api_key, "Should not return API key")
        self.assertIn("Thiếu OPENAI_API_KEY", error_msg, "Should have Vietnamese error")
    
    def test_invalid_format(self):
        """Test validation with invalid key format."""
        os.environ["OPENAI_API_KEY"] = "invalid-key"
        
        is_valid, api_key, error_msg = validate_openai_api_key()
        
        self.assertFalse(is_valid, "Should be invalid")
        self.assertIn("không hợp lệ", error_msg, "Should mention invalid format")
    
    def test_too_short(self):
        """Test validation with too short key."""
        os.environ["OPENAI_API_KEY"] = "sk-short"
        
        is_valid, api_key, error_msg = validate_openai_api_key()
        
        self.assertFalse(is_valid, "Should be invalid")
        self.assertIn("quá ngắn", error_msg, "Should mention too short")


class TestPlagiarismValidation(unittest.TestCase):
    """Test PlagiarismSearch API credentials validation."""
    
    def setUp(self):
        """Save original env vars."""
        self.original_user = os.getenv("PLAGIARISMSEARCH_API_USER")
        self.original_key = os.getenv("PLAGIARISMSEARCH_API_KEY")
    
    def tearDown(self):
        """Restore original env vars."""
        for key, value in [
            ("PLAGIARISMSEARCH_API_USER", self.original_user),
            ("PLAGIARISMSEARCH_API_KEY", self.original_key)
        ]:
            if value:
                os.environ[key] = value
            elif key in os.environ:
                del os.environ[key]
    
    def test_valid_credentials(self):
        """Test validation with valid credentials."""
        os.environ["PLAGIARISMSEARCH_API_USER"] = "test@example.com"
        os.environ["PLAGIARISMSEARCH_API_KEY"] = "x" * 40
        
        is_valid, user, key, error_msg = validate_plagiarism_api_credentials()
        
        self.assertTrue(is_valid, "Should be valid")
        self.assertEqual(user, "test@example.com")
        self.assertIsNotNone(key)
        self.assertIsNone(error_msg)
    
    def test_missing_credentials(self):
        """Test validation with missing credentials."""
        if "PLAGIARISMSEARCH_API_USER" in os.environ:
            del os.environ["PLAGIARISMSEARCH_API_USER"]
        if "PLAGIARISMSEARCH_API_KEY" in os.environ:
            del os.environ["PLAGIARISMSEARCH_API_KEY"]
        
        is_valid, user, key, error_msg = validate_plagiarism_api_credentials()
        
        self.assertFalse(is_valid, "Should be invalid")
        self.assertIsNone(user)
        self.assertIsNone(key)
        self.assertIn("Thiếu thông tin API", error_msg)
    
    def test_invalid_email_format(self):
        """Test validation with invalid email format."""
        os.environ["PLAGIARISMSEARCH_API_USER"] = "not-an-email"
        os.environ["PLAGIARISMSEARCH_API_KEY"] = "x" * 40
        
        is_valid, user, key, error_msg = validate_plagiarism_api_credentials()
        
        self.assertFalse(is_valid, "Should be invalid")
        self.assertIn("không đúng định dạng email", error_msg)
    
    def test_key_too_short(self):
        """Test validation with too short API key."""
        os.environ["PLAGIARISMSEARCH_API_USER"] = "test@example.com"
        os.environ["PLAGIARISMSEARCH_API_KEY"] = "short"
        
        is_valid, user, key, error_msg = validate_plagiarism_api_credentials()
        
        self.assertFalse(is_valid, "Should be invalid")
        self.assertIn("quá ngắn", error_msg)


class TestUserFriendlyErrors(unittest.TestCase):
    """Test user-friendly error message conversion."""
    
    def test_openai_quota_error(self):
        """Test OpenAI quota exceeded error."""
        error = Exception("429 quota exceeded")
        message = get_user_friendly_error(error)
        
        self.assertIn("vượt quá giới hạn API", message)
        self.assertIn("OpenAI", message)
    
    def test_authentication_error(self):
        """Test authentication error."""
        error = Exception("401 authentication failed")
        message = get_user_friendly_error(error)
        
        self.assertIn("Xác thực", message)
        self.assertIn("thất bại", message)
    
    def test_timeout_error(self):
        """Test timeout error."""
        error = Exception("timeout after 30 seconds")
        message = get_user_friendly_error(error)
        
        self.assertIn("Quá thời gian", message)
    
    def test_file_not_found_error(self):
        """Test file not found error."""
        error = Exception("file not found: test.docx")
        message = get_user_friendly_error(error)
        
        self.assertIn("Không tìm thấy file", message)
    
    def test_network_error(self):
        """Test network error."""
        error = Exception("connection failed")
        message = get_user_friendly_error(error)
        
        self.assertIn("kết nối mạng", message)
    
    def test_generic_error(self):
        """Test generic error fallback."""
        error = Exception("Unknown error occurred")
        message = get_user_friendly_error(error)
        
        self.assertIn("Lỗi không xác định", message)


class TestAPIValidationError(unittest.TestCase):
    """Test APIValidationError exception."""
    
    def test_exception_attributes(self):
        """Test exception has both Vietnamese and English messages."""
        error = APIValidationError("Lỗi tiếng Việt", "English error message")
        
        self.assertEqual(error.message_vi, "Lỗi tiếng Việt")
        self.assertEqual(error.message_en, "English error message")
        self.assertEqual(str(error), "English error message")


if __name__ == '__main__':
    unittest.main()
