"""
Cache Management for AI Drive FUSE

Implements metadata and data caching to improve performance and reduce API calls.
"""

import os
import time
import shutil
import tempfile
import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path
from threading import RLock
from collections import OrderedDict
import json


logger = logging.getLogger(__name__)


class MetadataCache:
    """Cache for file metadata and directory listings."""

    def __init__(self, ttl: int = 300):
        """Initialize metadata cache.

        Args:
            ttl: Time-to-live for cache entries in seconds
        """
        self.ttl = ttl
        self._file_attrs: Dict[str, Tuple[Any, float]] = {}
        self._dir_listings: Dict[str, Tuple[List[str], float]] = {}
        self._lock = RLock()

    def _is_expired(self, timestamp: float) -> bool:
        """Check if cache entry is expired."""
        return (time.time() - timestamp) > self.ttl

    def get_file_attrs(self, path: str) -> Optional[Any]:
        """Get cached file attributes."""
        with self._lock:
            if path in self._file_attrs:
                attrs, timestamp = self._file_attrs[path]
                if not self._is_expired(timestamp):
                    logger.debug(f"Cache hit for file attrs: {path}")
                    return attrs
                else:
                    # Remove expired entry
                    del self._file_attrs[path]
        return None

    def cache_file_attrs(self, path: str, attrs: Any) -> None:
        """Cache file attributes."""
        with self._lock:
            self._file_attrs[path] = (attrs, time.time())
            logger.debug(f"Cached file attrs: {path}")

    def get_dir_listing(self, path: str) -> Optional[List[str]]:
        """Get cached directory listing."""
        with self._lock:
            if path in self._dir_listings:
                listing, timestamp = self._dir_listings[path]
                if not self._is_expired(timestamp):
                    logger.debug(f"Cache hit for dir listing: {path}")
                    return listing
                else:
                    # Remove expired entry
                    del self._dir_listings[path]
        return None

    def cache_dir_listing(self, path: str, entries: List[str]) -> None:
        """Cache directory listing."""
        with self._lock:
            self._dir_listings[path] = (entries, time.time())
            logger.debug(f"Cached dir listing: {path} ({len(entries)} entries)")

    def invalidate(self, path: str) -> None:
        """Invalidate cache entry for specific path."""
        with self._lock:
            if path in self._file_attrs:
                del self._file_attrs[path]
                logger.debug(f"Invalidated file attrs cache: {path}")

    def invalidate_dir_listing(self, path: str) -> None:
        """Invalidate directory listing cache."""
        with self._lock:
            if path in self._dir_listings:
                del self._dir_listings[path]
                logger.debug(f"Invalidated dir listing cache: {path}")

    def cleanup_expired(self) -> int:
        """Clean up expired cache entries and return count of cleaned items."""
        current_time = time.time()
        total_cleaned = 0

        with self._lock:
            # Clean file attributes
            expired_files = [
                path for path, (_, timestamp) in self._file_attrs.items()
                if (current_time - timestamp) > self.ttl
            ]
            for path in expired_files:
                del self._file_attrs[path]
            total_cleaned += len(expired_files)

            # Clean directory listings
            expired_dirs = [
                path for path, (_, timestamp) in self._dir_listings.items()
                if (current_time - timestamp) > self.ttl
            ]
            for path in expired_dirs:
                del self._dir_listings[path]
            total_cleaned += len(expired_dirs)

            if expired_files or expired_dirs:
                logger.debug(f"Cleaned up {len(expired_files)} file attrs, {len(expired_dirs)} dir listings")
                
        return total_cleaned


class DataCache:
    """Enhanced cache with dynamic size management and intelligent eviction."""

    def __init__(self, cache_dir: str, max_size: int, min_size: Optional[int] = None, 
                 auto_adjust: bool = True):
        """Initialize data cache with dynamic sizing capabilities.

        Args:
            cache_dir: Directory for cached files
            max_size: Maximum cache size in bytes
            min_size: Minimum cache size in bytes (defaults to 25% of max_size)
            auto_adjust: Enable automatic cache size adjustment based on usage patterns
        """
        self.cache_dir = Path(cache_dir)
        self.max_size = max_size
        self.min_size = min_size or (max_size // 4)  # Default to 25% of max
        self.auto_adjust = auto_adjust
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Track cached files with LRU ordering
        self._cached_files: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._dirty_files: Set[str] = set()
        self._lock = RLock()
        
        # Dynamic sizing metrics
        self._size_history: List[Tuple[float, int]] = []  # (timestamp, size) pairs
        self._eviction_history: List[float] = []  # Timestamps of evictions
        self._last_adjustment_time = time.time()
        self._adjustment_interval = 300  # 5 minutes
        
        # Performance metrics
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_evictions = 0

        # Load existing cache state
        self._load_cache_state()

    def _get_cache_path(self, remote_path: str) -> Path:
        """Get local cache path for remote file."""
        # Use hash of remote path to avoid filesystem issues
        path_hash = hashlib.sha256(remote_path.encode()).hexdigest()
        return self.cache_dir / f"{path_hash}.cache"

    def _get_metadata_path(self, remote_path: str) -> Path:
        """Get metadata file path for cached file."""
        path_hash = hashlib.sha256(remote_path.encode()).hexdigest()
        return self.cache_dir / f"{path_hash}.meta"

    def _load_cache_state(self) -> None:
        """Load cache state from disk."""
        try:
            for meta_file in self.cache_dir.glob("*.meta"):
                try:
                    with open(meta_file, 'r') as f:
                        metadata = json.load(f)

                    remote_path = metadata['remote_path']
                    cache_path = self._get_cache_path(remote_path)

                    if cache_path.exists():
                        self._cached_files[remote_path] = {
                            'cache_path': cache_path,
                            'size': cache_path.stat().st_size,
                            'cached_time': metadata.get('cached_time', time.time()),
                            'access_time': time.time()
                        }

                        if metadata.get('dirty', False):
                            self._dirty_files.add(remote_path)
                    else:
                        # Remove orphaned metadata
                        meta_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to load cache metadata {meta_file}: {e}")

            logger.info(f"Loaded {len(self._cached_files)} cached files")
        except Exception as e:
            logger.error(f"Failed to load cache state: {e}")

    def _save_metadata(self, remote_path: str) -> None:
        """Save metadata for cached file."""
        try:
            metadata_path = self._get_metadata_path(remote_path)
            file_info = self._cached_files[remote_path]

            metadata = {
                'remote_path': remote_path,
                'cached_time': file_info['cached_time'],
                'size': file_info['size'],
                'dirty': remote_path in self._dirty_files
            }

            with open(metadata_path, 'w') as f:
                json.dump(metadata, f)
        except Exception as e:
            logger.error(f"Failed to save metadata for {remote_path}: {e}")

    def _update_access_time(self, remote_path: str) -> None:
        """Update access time for LRU tracking."""
        if remote_path in self._cached_files:
            self._cached_files[remote_path]['access_time'] = time.time()
            # Move to end for LRU
            self._cached_files.move_to_end(remote_path)

    def set_max_size(self, new_max_size: int) -> None:
        """Dynamically update maximum cache size."""
        with self._lock:
            old_max_size = self.max_size
            self.max_size = max(new_max_size, self.min_size)
            
            logger.info(f"Cache size adjusted: {old_max_size} -> {self.max_size} bytes")
            
            # If new size is smaller, trigger eviction
            if new_max_size < old_max_size:
                self._evict_if_needed()
    
    def get_optimal_cache_size(self) -> int:
        """Calculate optimal cache size based on usage patterns."""
        current_time = time.time()
        
        # Clean old history data (keep last 24 hours)
        cutoff_time = current_time - 86400  # 24 hours
        self._size_history = [(t, s) for t, s in self._size_history if t > cutoff_time]
        self._eviction_history = [t for t in self._eviction_history if t > cutoff_time]
        
        if not self._size_history:
            return self.max_size
        
        # Calculate average size usage
        recent_sizes = [size for _, size in self._size_history[-20:]]  # Last 20 measurements
        avg_size = sum(recent_sizes) / len(recent_sizes)
        
        # Calculate eviction pressure (evictions per hour)
        recent_evictions = len([t for t in self._eviction_history if t > current_time - 3600])
        eviction_pressure = recent_evictions / 1.0  # per hour
        
        # Calculate cache efficiency
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0
        
        # Adjust size based on patterns
        optimal_size = self.max_size
        
        # If high eviction pressure and good hit rate, increase cache
        if eviction_pressure > 5 and hit_rate > 0.7:
            optimal_size = min(self.max_size * 1.2, self.max_size * 2)
        
        # If low utilization, decrease cache
        elif avg_size < self.max_size * 0.3 and eviction_pressure < 1:
            optimal_size = max(avg_size * 1.5, self.min_size)
        
        # If very high hit rate but high pressure, moderate increase
        elif hit_rate > 0.9 and eviction_pressure > 2:
            optimal_size = min(self.max_size * 1.1, self.max_size * 1.5)
        
        return int(optimal_size)
    
    def auto_adjust_size(self) -> bool:
        """Automatically adjust cache size based on usage patterns."""
        if not self.auto_adjust:
            return False
            
        current_time = time.time()
        
        # Only adjust periodically
        if current_time - self._last_adjustment_time < self._adjustment_interval:
            return False
        
        optimal_size = self.get_optimal_cache_size()
        
        # Only adjust if significant difference (>10%)
        size_diff_ratio = abs(optimal_size - self.max_size) / self.max_size
        if size_diff_ratio > 0.1:
            self.set_max_size(optimal_size)
            self._last_adjustment_time = current_time
            return True
            
        return False
    
    def _record_size_sample(self) -> None:
        """Record current cache size for analysis."""
        current_size = sum(info['size'] for info in self._cached_files.values())
        current_time = time.time()
        
        self._size_history.append((current_time, current_size))
        
        # Keep only recent history (last 100 samples)
        if len(self._size_history) > 100:
            self._size_history = self._size_history[-100:]
    
    def _evict_if_needed(self, required_size: int = 0) -> None:
        """Evict files if cache is too full with intelligent selection."""
        current_size = sum(info['size'] for info in self._cached_files.values())
        target_size = self.max_size - required_size
        
        if current_size <= target_size:
            return
        
        logger.debug(f"Cache eviction needed: current={current_size}, target={target_size}")

        evicted_count = 0
        
        while current_size > target_size and self._cached_files:
            # Intelligent eviction: score files by multiple factors
            candidate = self._select_eviction_candidate()
            
            if candidate is None:
                logger.warning("Cannot evict: no suitable candidates found. "
                              "All files may be dirty or in use.")
                break

            # Get file size before eviction
            file_size = self._cached_files[candidate]['size']
            self._evict_file(candidate)
            current_size -= file_size  # Incremental update instead of recalculation
            evicted_count += 1
            
            # Record eviction for analysis
            self._eviction_history.append(time.time())
            self._total_evictions += 1
        
        if evicted_count > 0:
            logger.info(f"Evicted {evicted_count} files, freed ~{(target_size - current_size) // 1024}KB")
    
    def _select_eviction_candidate(self) -> Optional[str]:
        """Intelligently select the best file to evict based on multiple factors."""
        if not self._cached_files:
            return None
        
        # Don't evict dirty files
        clean_files = [path for path in self._cached_files if path not in self._dirty_files]
        if not clean_files:
            return None
        
        current_time = time.time()
        best_candidate = None
        best_score = -1
        
        for path in clean_files:
            info = self._cached_files[path]
            
            # Calculate eviction score (higher = better candidate)
            score = 0
            
            # Age factor (older access = higher score)
            age_minutes = (current_time - info['access_time']) / 60.0
            score += min(age_minutes * 2, 100)  # Up to 100 points for age
            
            # Size factor (larger files get slight preference for eviction)
            size_mb = info['size'] / (1024 * 1024)
            if size_mb > 10:  # Files larger than 10MB
                score += min(size_mb * 0.5, 20)  # Up to 20 points
            
            # Cache time factor (files cached longer ago get preference)
            cache_age_hours = (current_time - info.get('cached_time', current_time)) / 3600.0
            score += min(cache_age_hours * 1, 10)  # Up to 10 points
            
            # Frequency factor (files accessed less frequently get preference)
            # This would require tracking access frequency - simplified for now
            
            if score > best_score:
                best_score = score
                best_candidate = path
        
        return best_candidate

    def _evict_file(self, remote_path: str) -> None:
        """Evict specific file from cache."""
        if remote_path not in self._cached_files:
            return

        file_info = self._cached_files[remote_path]
        cache_path = file_info['cache_path']

        try:
            # Remove cached file
            if cache_path.exists():
                cache_path.unlink()

            # Remove metadata
            metadata_path = self._get_metadata_path(remote_path)
            if metadata_path.exists():
                metadata_path.unlink()

            # Remove from tracking
            del self._cached_files[remote_path]
            self._dirty_files.discard(remote_path)

            logger.debug(f"Evicted from cache: {remote_path}")
        except Exception as e:
            logger.error(f"Failed to evict {remote_path}: {e}")

    def get_cached_path(self, remote_path: str) -> Optional[str]:
        """Get local path for cached file with metrics tracking."""
        with self._lock:
            if remote_path in self._cached_files:
                self._update_access_time(remote_path)
                cache_path = self._cached_files[remote_path]['cache_path']
                if cache_path.exists():
                    # Update size to reflect current file size
                    actual_size = cache_path.stat().st_size
                    self._cached_files[remote_path]['size'] = actual_size
                    self._cache_hits += 1
                    logger.debug(f"Cache hit: {remote_path}")
                    
                    # Record size sample periodically
                    if self._cache_hits % 10 == 0:  # Every 10 hits
                        self._record_size_sample()
                    
                    # Try auto-adjustment periodically
                    if self._cache_hits % 50 == 0:  # Every 50 hits
                        self.auto_adjust_size()
                    
                    return str(cache_path)
                else:
                    # File missing from cache, remove entry
                    del self._cached_files[remote_path]
                    self._cache_misses += 1
            else:
                self._cache_misses += 1
        return None

    def download_to_cache(self, remote_path: str, client: Any) -> str:
        """Download file to cache."""
        with self._lock:
            cache_path = self._get_cache_path(remote_path)

            # Check if already cached
            if remote_path in self._cached_files and cache_path.exists():
                self._update_access_time(remote_path)
                return str(cache_path)

            # Download file
            logger.debug(f"Downloading to cache: {remote_path}")

            final_cache_path = None
            try:
                # Use a more secure approach to avoid TOCTOU race condition
                # Create a temporary directory and download file there
                with tempfile.TemporaryDirectory(dir=self.cache_dir) as temp_dir:
                    temp_filename = f"download_{hash(remote_path) & 0x7FFFFFFF}.tmp"
                    temp_path = os.path.join(temp_dir, temp_filename)

                    # Download to temporary file in secure directory
                    client.download_file(remote_path, temp_path)

                    # Get file size
                    file_size = Path(temp_path).stat().st_size

                    # Ensure cache has space
                    self._evict_if_needed(file_size)

                    # Move to final cache location (temp_dir will be cleaned up automatically)
                    shutil.move(temp_path, cache_path)
                    final_cache_path = cache_path

                # Track in cache (only if download was successful)
                if final_cache_path:
                    self._cached_files[remote_path] = {
                        'cache_path': final_cache_path,
                        'size': file_size,
                        'cached_time': time.time(),
                        'access_time': time.time()
                    }

                    # Save metadata
                    self._save_metadata(remote_path)

                    logger.info(f"Downloaded to cache: {remote_path} ({file_size} bytes)")
                    return str(final_cache_path)
                else:
                    # This should not happen, but provide a fallback
                    raise RuntimeError("Download completed but final cache path is not set")

            except Exception as e:
                # Cleanup on error - temporary directory is automatically cleaned up
                # Only need to clean final cache path if it was created
                if final_cache_path and Path(final_cache_path).exists():
                    Path(final_cache_path).unlink()
                raise e

    def create_cached_file(self, remote_path: str) -> str:
        """Create empty cached file for new files."""
        with self._lock:
            cache_path = self._get_cache_path(remote_path)

            # Create empty file
            cache_path.touch()

            # Track in cache
            self._cached_files[remote_path] = {
                'cache_path': cache_path,
                'size': 0,
                'cached_time': time.time(),
                'access_time': time.time()
            }

            # Mark as dirty (needs upload)
            self._dirty_files.add(remote_path)
            self._save_metadata(remote_path)

            logger.debug(f"Created cached file: {remote_path}")
            return str(cache_path)

    def mark_dirty(self, remote_path: str) -> None:
        """Mark cached file as dirty (needs upload)."""
        with self._lock:
            self._dirty_files.add(remote_path)
            if remote_path in self._cached_files:
                # Update file size when marking dirty
                cache_path = self._cached_files[remote_path]['cache_path']
                if cache_path.exists():
                    actual_size = cache_path.stat().st_size
                    self._cached_files[remote_path]['size'] = actual_size
                    logger.debug(f"Updated cached file size: {remote_path} -> {actual_size} bytes")
                self._save_metadata(remote_path)
            logger.debug(f"Marked dirty: {remote_path}")

    def mark_clean(self, remote_path: str) -> None:
        """Mark cached file as clean (uploaded)."""
        with self._lock:
            self._dirty_files.discard(remote_path)
            if remote_path in self._cached_files:
                self._save_metadata(remote_path)
            logger.debug(f"Marked clean: {remote_path}")

    def get_dirty_files(self) -> List[Tuple[str, str]]:
        """Get list of dirty files needing upload."""
        with self._lock:
            dirty_list = []
            for remote_path in self._dirty_files:
                if remote_path in self._cached_files:
                    cache_path = self._cached_files[remote_path]['cache_path']
                    if cache_path.exists():
                        dirty_list.append((str(cache_path), remote_path))
            return dirty_list

    def get_cached_files_in_dir(self, dir_path: str) -> List[str]:
        """Get list of cached files in a directory."""
        with self._lock:
            # Normalize directory path
            dir_path = dir_path.rstrip('/') if dir_path != '/' else '/'

            cached_files = []
            for remote_path in self._cached_files:
                # Check if this file is in the specified directory
                file_dir = '/'.join(remote_path.split('/')[:-1]) or '/'
                if file_dir == dir_path:
                    cache_info = self._cached_files[remote_path]
                    if cache_info['cache_path'].exists():
                        cached_files.append(remote_path)

            return cached_files

    def get_cached_file_size(self, remote_path: str) -> Optional[int]:
        """Get current size of cached file."""
        with self._lock:
            if remote_path in self._cached_files:
                cache_path = self._cached_files[remote_path]['cache_path']
                if cache_path.exists():
                    actual_size = cache_path.stat().st_size
                    # Update our cached size info
                    self._cached_files[remote_path]['size'] = actual_size
                    return int(actual_size)
            return None

    def invalidate(self, remote_path: str) -> None:
        """Remove file from cache."""
        with self._lock:
            if remote_path in self._cached_files:
                self._evict_file(remote_path)

    def cleanup_expired(self) -> int:
        """Clean up old cached files and return count of cleaned files."""
        with self._lock:
            current_time = time.time()
            expired_threshold = 24 * 3600  # 24 hours

            expired_files = [
                path for path, info in self._cached_files.items()
                if (current_time - info['access_time']) > expired_threshold
                and path not in self._dirty_files  # Don't remove dirty files
            ]

            for path in expired_files:
                self._evict_file(path)

            if expired_files:
                logger.info(f"Cleaned up {len(expired_files)} expired cache files")
                
            return len(expired_files)

    def cleanup(self) -> None:
        """Full cleanup on shutdown."""
        logger.info("Cleaning up data cache")

        # Upload any remaining dirty files (best effort)
        dirty_count = len(self._dirty_files)
        if dirty_count > 0:
            logger.warning(f"Shutting down with {dirty_count} dirty files - data may be lost")

        # Optional: Could implement emergency sync here

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        with self._lock:
            total_size = sum(info['size'] for info in self._cached_files.values())
            total_requests = self._cache_hits + self._cache_misses
            
            # Calculate recent eviction rate (last hour)
            current_time = time.time()
            recent_evictions = len([t for t in self._eviction_history if t > current_time - 3600])
            
            stats = {
                'cached_files': len(self._cached_files),
                'dirty_files': len(self._dirty_files),
                'total_size': total_size,
                'max_size': self.max_size,
                'min_size': self.min_size,
                'usage_percentage': (total_size / self.max_size) * 100 if self.max_size > 0 else 0,
                'cache_hits': self._cache_hits,
                'cache_misses': self._cache_misses,
                'hit_rate': (self._cache_hits / total_requests * 100) if total_requests > 0 else 0,
                'total_evictions': self._total_evictions,
                'recent_evictions_per_hour': recent_evictions,
                'auto_adjust_enabled': self.auto_adjust,
            }
            
            # Add optimal size recommendation
            if self.auto_adjust:
                stats['optimal_size'] = self.get_optimal_cache_size()
                stats['size_efficiency'] = (stats['optimal_size'] / self.max_size * 100) if self.max_size > 0 else 100
            
            return stats
