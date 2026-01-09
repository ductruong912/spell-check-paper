"""Unit tests for disk cache functionality."""
import unittest
import tempfile
import shutil
import time
from pathlib import Path
from utils.disk_cache import (
    get_file_hash,
    save_to_cache,
    load_from_cache,
    clear_cache,
    get_cache_stats,
    CACHE_DIR
)


class TestDiskCache(unittest.TestCase):
    """Test disk cache functionality."""
    
    def setUp(self):
        """Create temporary cache directory for tests."""
        self.test_cache_dir = Path(tempfile.mkdtemp())
        # Monkey-patch CACHE_DIR for tests
        import utils.disk_cache as cache_module
        self.original_cache_dir = cache_module.CACHE_DIR
        cache_module.CACHE_DIR = self.test_cache_dir
    
    def tearDown(self):
        """Clean up temporary cache directory."""
        import utils.disk_cache as cache_module
        cache_module.CACHE_DIR = self.original_cache_dir
        if self.test_cache_dir.exists():
            shutil.rmtree(self.test_cache_dir)
    
    def test_save_and_load_cache(self):
        """Test saving and loading data from cache."""
        test_data = {"key": "value", "number": 42, "list": [1, 2, 3]}
        cache_key = "test_key_123"
        
        # Save to cache
        success = save_to_cache(cache_key, test_data, namespace="test")
        self.assertTrue(success, "Save should succeed")
        
        # Load from cache
        loaded_data = load_from_cache(cache_key, namespace="test")
        self.assertIsNotNone(loaded_data, "Should load cached data")
        self.assertEqual(loaded_data, test_data, "Loaded data should match saved data")
    
    def test_cache_expiration(self):
        """Test cache entries expire after TTL."""
        test_data = {"expired": True}
        cache_key = "expiring_key"
        
        # Save with 1 second TTL
        save_to_cache(cache_key, test_data, namespace="test", ttl=1)
        
        # Should be available immediately
        loaded = load_from_cache(cache_key, namespace="test")
        self.assertIsNotNone(loaded, "Cache should be available immediately")
        
        # Wait for expiration
        time.sleep(1.5)
        
        # Should be expired now
        loaded = load_from_cache(cache_key, namespace="test")
        self.assertIsNone(loaded, "Cache should be expired")
    
    def test_cache_miss(self):
        """Test loading non-existent cache returns None."""
        loaded = load_from_cache("nonexistent_key", namespace="test")
        self.assertIsNone(loaded, "Loading non-existent cache should return None")
    
    def test_namespace_isolation(self):
        """Test different namespaces are isolated."""
        data1 = {"namespace": "first"}
        data2 = {"namespace": "second"}
        cache_key = "same_key"
        
        # Save to different namespaces
        save_to_cache(cache_key, data1, namespace="ns1")
        save_to_cache(cache_key, data2, namespace="ns2")
        
        # Load from each namespace
        loaded1 = load_from_cache(cache_key, namespace="ns1")
        loaded2 = load_from_cache(cache_key, namespace="ns2")
        
        self.assertEqual(loaded1, data1, "Should load data from ns1")
        self.assertEqual(loaded2, data2, "Should load data from ns2")
        self.assertNotEqual(loaded1, loaded2, "Namespaces should be isolated")
    
    def test_clear_cache_all(self):
        """Test clearing all cache entries."""
        # Save some entries
        save_to_cache("key1", "data1", namespace="ns1")
        save_to_cache("key2", "data2", namespace="ns2")
        
        # Clear all
        deleted = clear_cache()
        self.assertEqual(deleted, 2, "Should delete 2 entries")
        
        # Verify deleted
        self.assertIsNone(load_from_cache("key1", namespace="ns1"))
        self.assertIsNone(load_from_cache("key2", namespace="ns2"))
    
    def test_clear_cache_namespace(self):
        """Test clearing specific namespace only."""
        # Save to multiple namespaces
        save_to_cache("key1", "data1", namespace="ns1")
        save_to_cache("key2", "data2", namespace="ns2")
        
        # Clear only ns1
        deleted = clear_cache(namespace="ns1")
        self.assertEqual(deleted, 1, "Should delete 1 entry from ns1")
        
        # Verify ns1 deleted, ns2 remains
        self.assertIsNone(load_from_cache("key1", namespace="ns1"))
        self.assertIsNotNone(load_from_cache("key2", namespace="ns2"))
    
    def test_clear_old_entries(self):
        """Test clearing entries older than specific age."""
        # Save entry with short TTL
        save_to_cache("old_key", "old_data", namespace="test", ttl=10)
        time.sleep(0.5)
        save_to_cache("new_key", "new_data", namespace="test", ttl=10)
        
        # Clear entries older than 0.3 seconds
        deleted = clear_cache(older_than=0.3)
        self.assertEqual(deleted, 1, "Should delete only old entry")
        
        # Verify old deleted, new remains
        self.assertIsNone(load_from_cache("old_key", namespace="test"))
        self.assertIsNotNone(load_from_cache("new_key", namespace="test"))
    
    def test_cache_stats(self):
        """Test getting cache statistics."""
        # Save some entries
        save_to_cache("key1", "x" * 1000, namespace="ns1")
        save_to_cache("key2", "y" * 2000, namespace="ns2")
        
        stats = get_cache_stats()
        
        self.assertEqual(stats["total_count"], 2, "Should count 2 entries")
        self.assertGreater(stats["total_size_mb"], 0, "Should have non-zero size")
        self.assertIn("ns1", stats["namespaces"])
        self.assertIn("ns2", stats["namespaces"])


class TestFileHash(unittest.TestCase):
    """Test file hashing functionality."""
    
    def test_file_hash_consistency(self):
        """Test same file produces same hash."""
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("test content")
            temp_path = f.name
        
        try:
            # Hash twice
            hash1 = get_file_hash(temp_path)
            hash2 = get_file_hash(temp_path)
            
            self.assertEqual(hash1, hash2, "Same file should produce same hash")
            self.assertEqual(len(hash1), 64, "SHA256 hash should be 64 chars")
        finally:
            Path(temp_path).unlink()
    
    def test_different_files_different_hash(self):
        """Test different files produce different hashes."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f1:
            f1.write("content 1")
            path1 = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f2:
            f2.write("content 2")
            path2 = f2.name
        
        try:
            hash1 = get_file_hash(path1)
            hash2 = get_file_hash(path2)
            
            self.assertNotEqual(hash1, hash2, "Different files should have different hashes")
        finally:
            Path(path1).unlink()
            Path(path2).unlink()


if __name__ == '__main__':
    unittest.main()
