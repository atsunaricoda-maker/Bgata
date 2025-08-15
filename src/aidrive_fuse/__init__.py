"""
AI Drive FUSE Filesystem Implementation

This package provides a FUSE-based filesystem interface for GenSpark AI Drive,
allowing POSIX filesystem operations to be transparently mapped to AI Drive API calls.
"""

__version__ = "v1.0.16"
__author__ = "GenSpark"

from .fuse_driver import AIDriveFUSE
from .cache_manager import MetadataCache, DataCache
from .operation_queue import OperationQueue
from .config import Config

__all__ = [
    "AIDriveFUSE",
    "MetadataCache",
    "DataCache",
    "OperationQueue",
    "Config"
]
