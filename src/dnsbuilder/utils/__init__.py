"""
DNS Builder Utils Module

- logger: Logging setup and configuration
- merge: Deep merge for dictionaries
- typing_compat: Type compatibility utilities

Usage:
    from dnsbuilder.utils import setup_logger, deep_merge
"""

from .logger import setup_logger
from .merge import deep_merge
from .typing_compat import override

__all__ = [
    'setup_logger',
    'deep_merge',
    'override',
]

