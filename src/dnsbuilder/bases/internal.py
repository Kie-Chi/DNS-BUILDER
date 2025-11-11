"""
DNS Builder Internal Image Implementations

This module contains concrete implementations of internally-built Docker images.

Concrete classes:
- BindImage: BIND DNS server image
- UnboundImage: Unbound DNS server image
- PythonImage: Python application image
- JudasImage: JudasDNS image
"""

from typing import Any, Dict
import logging

from ..utils import override
from ..abstractions import InternalImage
from ..io import FileSystem

logger = logging.getLogger(__name__)


# -------------------------
#
#   BIND IMAGE
#
# -------------------------

class BindImage(InternalImage):
    """
    Concrete Image class for BIND DNS server.

    Package.parse() automatically handles python3-xxx packages,
    so no special processing is needed.
    """

    @override
    def _post_init_hook(self):
        """
        Nothing special to do
        """
        pass


# -------------------------
#
#   UNBOUND IMAGE
#
# -------------------------

class UnboundImage(InternalImage):
    """
    Concrete Image class for Unbound DNS server
    """

    @override
    def _post_init_hook(self):
        """
        Nothing to do for Unbound
        """
        pass  # Unbound has nothing to do


# ------------------------
#
#   JUDAS IMAGE
#
# ------------------------

class JudasImage(InternalImage):
    """
    Concrete Image class for JudasDNS
    """

    @override
    def _post_init_hook(self):
        """
        Handle JudasDNS's specific dependency logic after base setup.
        """
        self.os = "node"


# -------------------------
#
#   PYTHON IMAGE
#
# -------------------------

class PythonImage(InternalImage):
    """
    Concrete Image class for Python applications.
    
    Uses python:x.x base image which already has Python and pip installed.

    """

    @override
    def _load_defaults(self):
        super()._load_defaults()
        if ":" in self.name:
            # ensure the base os is 'python', not 'ubuntu'
            self.os = "python"

    @override
    def _post_init_hook(self):
        """
        Nothing to do for Python
        """
        pass


# Dynamically generate __all__
from ..utils.reflection import gen_exports

__all__ = gen_exports(
    ns=globals(),
    base_path='dnsbuilder.bases.internal',
    patterns=['Image']
)