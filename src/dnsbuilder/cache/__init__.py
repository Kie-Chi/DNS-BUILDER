"""
DNS Builder Cache Module


The cache system consists of three main components:
- FileCacheView: Caches metadata for individual files
- ServiceCacheView: Caches metadata for services and their files
- ProjectCacheView: Caches metadata for entire projects
- CacheManager: Manages cache storage, loading, and consistency checking
"""

from .view import (
    CacheView,
    FileCacheView,
    ServiceCacheView,
    ProjectCacheView,
    DEFAULT_IGNORE_PATTERNS
)
from .manager import CacheManager
from .build import CachedBuilder

__all__ = [
    'CacheView',
    'CachedBuilder',
    'FileCacheView',
    'ServiceCacheView',
    'ProjectCacheView',
    'CacheManager',
    'DEFAULT_IGNORE_PATTERNS'
]