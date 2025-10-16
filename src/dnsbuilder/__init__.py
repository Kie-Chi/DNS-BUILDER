"""
DNSB (DNS Builder) Framework

A flexible DNS configuration management framework with dynamic behavior discovery.
"""

from .registry import initialize_registries

__version__ = "0.8.0"
__all__ = ["initialize_registries"]