"""Persistent disk cache for document processing results."""
import hashlib
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Optional, Any
from dataclasses import asdict

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path(__file__).parent.parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# Cache TTL (Time To Live) in seconds
DEFAULT_TTL = 7 * 24 * 3600  # 7 days


def get_file_hash(file_path: str) -> str:
    """
    Get SHA256 hash of a file for cache key.
    
    Args:
        file_path: Path to file
    
    Returns:
        Hex string of file hash
    """
    sha256 = hashlib.sha256()
    
    try:
        with open(file_path, 'rb') as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"Lỗi tính hash file {file_path}: {e}")
        # Fallback to filename + size + mtime
        p = Path(file_path)
        fallback = f"{p.name}_{p.stat().st_size}_{p.stat().st_mtime}"
        return hashlib.sha256(fallback.encode()).hexdigest()


def get_cache_path(cache_key: str, namespace: str = "default") -> Path:
    """
    Get cache file path for a given key.
    
    Args:
        cache_key: Unique cache key (usually file hash)
        namespace: Cache namespace (e.g., 'document', 'plagiarism', 'structure')
    
    Returns:
        Path to cache file
    """
    namespace_dir = CACHE_DIR / namespace
    namespace_dir.mkdir(exist_ok=True)
    return namespace_dir / f"{cache_key}.pkl"


def save_to_cache(cache_key: str, data: Any, namespace: str = "default", ttl: int = DEFAULT_TTL) -> bool:
    """
    Save data to disk cache.
    
    Args:
        cache_key: Unique cache key
        data: Data to cache (must be picklable)
        namespace: Cache namespace
        ttl: Time to live in seconds
    
    Returns:
        True if saved successfully
    """
    try:
        cache_path = get_cache_path(cache_key, namespace)
        
        cache_entry = {
            "data": data,
            "timestamp": time.time(),
            "ttl": ttl,
        }
        
        with open(cache_path, 'wb') as f:
            pickle.dump(cache_entry, f, protocol=pickle.HIGHEST_PROTOCOL)
        
        logger.debug(f"Đã lưu cache: {namespace}/{cache_key[:8]}... (TTL: {ttl}s)")
        return True
    
    except Exception as e:
        logger.error(f"Lỗi lưu cache {namespace}/{cache_key[:8]}: {e}")
        return False


def load_from_cache(cache_key: str, namespace: str = "default") -> Optional[Any]:
    """
    Load data from disk cache.
    
    Args:
        cache_key: Unique cache key
        namespace: Cache namespace
    
    Returns:
        Cached data if found and valid, None otherwise
    """
    try:
        cache_path = get_cache_path(cache_key, namespace)
        
        if not cache_path.exists():
            logger.debug(f"Cache miss: {namespace}/{cache_key[:8]}...")
            return None
        
        with open(cache_path, 'rb') as f:
            cache_entry = pickle.load(f)
        
        # Check if cache is expired
        age = time.time() - cache_entry["timestamp"]
        if age > cache_entry["ttl"]:
            logger.debug(f"Cache expired: {namespace}/{cache_key[:8]}... (age: {age:.0f}s)")
            cache_path.unlink()  # Delete expired cache
            return None
        
        logger.debug(f"Cache hit: {namespace}/{cache_key[:8]}... (age: {age:.0f}s)")
        return cache_entry["data"]
    
    except Exception as e:
        logger.error(f"Lỗi đọc cache {namespace}/{cache_key[:8]}: {e}")
        return None


def clear_cache(namespace: Optional[str] = None, older_than: Optional[int] = None):
    """
    Clear cache entries.
    
    Args:
        namespace: Clear specific namespace only (None = all)
        older_than: Clear entries older than X seconds (None = all)
    """
    try:
        if namespace:
            dirs = [CACHE_DIR / namespace]
        else:
            dirs = [d for d in CACHE_DIR.iterdir() if d.is_dir()]
        
        deleted_count = 0
        for cache_dir in dirs:
            if not cache_dir.exists():
                continue
            
            for cache_file in cache_dir.glob("*.pkl"):
                should_delete = False
                
                if older_than is None:
                    should_delete = True
                else:
                    try:
                        with open(cache_file, 'rb') as f:
                            cache_entry = pickle.load(f)
                        age = time.time() - cache_entry["timestamp"]
                        if age > older_than:
                            should_delete = True
                    except:
                        should_delete = True  # Delete corrupted cache
                
                if should_delete:
                    cache_file.unlink()
                    deleted_count += 1
        
        logger.info(f"Đã xóa {deleted_count} cache entries")
        return deleted_count
    
    except Exception as e:
        logger.error(f"Lỗi xóa cache: {e}")
        return 0


def get_cache_stats() -> dict:
    """
    Get cache statistics.
    
    Returns:
        Dict with cache stats (size, count, namespaces)
    """
    try:
        total_size = 0
        total_count = 0
        namespaces = {}
        
        for namespace_dir in CACHE_DIR.iterdir():
            if not namespace_dir.is_dir():
                continue
            
            namespace = namespace_dir.name
            ns_size = 0
            ns_count = 0
            
            for cache_file in namespace_dir.glob("*.pkl"):
                ns_size += cache_file.stat().st_size
                ns_count += 1
            
            namespaces[namespace] = {
                "count": ns_count,
                "size_mb": ns_size / (1024 * 1024),
            }
            
            total_size += ns_size
            total_count += ns_count
        
        return {
            "total_count": total_count,
            "total_size_mb": total_size / (1024 * 1024),
            "namespaces": namespaces,
        }
    
    except Exception as e:
        logger.error(f"Lỗi lấy cache stats: {e}")
        return {"total_count": 0, "total_size_mb": 0, "namespaces": {}}
