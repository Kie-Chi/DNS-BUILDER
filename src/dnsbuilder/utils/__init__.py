"""
DNS Builder Utils Module

- logger: Logging setup and configuration
- merge: Deep merge for dictionaries
- typing_compat: Type compatibility utilities
- reflection: Class discovery and reflection utilities

Usage:
    from dnsbuilder.utils import setup_logger, deep_merge, gen_exports
"""

from .logger import setup_logger
from .merge import deep_merge
from .typing_compat import override
from .util import to_pascal, to_snake, to_camel
from .reflection import (
    discover_classes,
    extract_bhv_info,
    extract_img_info,
    extract_inc_info,
    gen_exports,
)

__all__ = [
    'setup_logger',
    'deep_merge',
    'override',
    # Reflection utilities
    'discover_classes',
    'extract_bhv_info',
    'extract_img_info',
    'extract_inc_info',
    'gen_exports',
    'to_pascal',
    'to_snake',
    'to_camel',
]

