"""
CoreDNS Plugin Resources

This package contains resources for the CoreDNS plugin:
- Dockerfile templates
- Default configurations
- Control files
"""

from . import images
from . import builder

__all__ = ['images', 'builder']