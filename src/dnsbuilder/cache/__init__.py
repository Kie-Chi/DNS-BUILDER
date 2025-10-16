"""
DNS Builder Cache Module

This module provides caching functionality for DNS Builder projects to enable
incremental builds and improve build performance.

The cache system consists of three main components:
- FileCacheView: Caches metadata for individual files
- ServiceCacheView: Caches metadata for services and their files
- ProjectCacheView: Caches metadata for entire projects
- CacheManager: Manages cache storage, loading, and consistency checking
"""

from .cache_view import (
    CacheView,
    FileCacheView,
    ServiceCacheView,
    ProjectCacheView,
    DEFAULT_IGNORE_PATTERNS
)
from .cache_manager import CacheManager

__all__ = [
    'CacheView',
    'FileCacheView',
    'ServiceCacheView',
    'ProjectCacheView',
    'CacheManager',
    'DEFAULT_IGNORE_PATTERNS'
]