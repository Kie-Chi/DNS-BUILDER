"""
DNS Builder Rules Module

- Rule: Rule for version constraint handling
- Version: Version constraint handling

Usage:
    from dnsbuilder.rules import Rule, Version
"""

from .rule import Rule
from .version import Version

__all__ = [
    'Rule',
    'Version',
]

