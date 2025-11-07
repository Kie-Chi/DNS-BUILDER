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
    Concrete Image class for BIND DNS server
    """

    def __init__(self, config: Dict[str, Any], fs: FileSystem = None):
        self.py3_deps = []  # will init in hook
        super().__init__(config, fs=fs)

    @override
    def _post_init_hook(self):
        """
        Handle BIND's specific python3 dependency logic after base setup.
        """
        py3_pkg_names = [
            dep.split("python3-")[-1] for dep in self.dependency if "python3-" in dep
        ]

        if "pip" in py3_pkg_names:
            py3_pkg_names.remove("pip")

        self.py3_deps = sorted(list(set(py3_pkg_names)))

        if self.py3_deps:
            self.dependency = [dep for dep in self.dependency if "python3-" not in dep]
            self.dependency.extend(["python3", "python3-pip"])
            logger.debug(
                f"[{self.name}] Processed Python dependencies: {self.py3_deps}"
            )

    @override
    def _get_template_vars(self) -> Dict[str, Any]:
        """
        Extend base template variables with BIND-specific ones.
        """
        base_vars = super()._get_template_vars()
        py3_packages = " ".join(self.py3_deps)
        base_vars["py3_packages"] = (
            f"RUN pip3 install {py3_packages}" if py3_packages else ""
        )
        return base_vars

    @override
    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure python3 dependencies from the parent are correctly carried over.
        """
        merged = super().merge(child_config)
        # Re-add the python3- prefixed deps for accurate merging with child deps
        merged["dependency"].extend([f"python3-{dep}" for dep in self.py3_deps])
        merged["dependency"] = sorted(list(set(merged["dependency"])))
        logger.debug(f"[{self.name}] [BindImage] Fully Merged Result : {merged}")
        return merged


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
    Concrete Image class for Python applications
    """

    def __init__(self, config: Dict[str, Any], fs: FileSystem = None):
        self.pip_deps = []
        super().__init__(config, fs=fs)

    @override
    def _load_defaults(self):
        super()._load_defaults()
        if ":" in self.name:
            # ensure the base os is 'python', not 'ubuntu'
            self.os = "python"

    @override
    def _post_init_hook(self):
        """
        Handle Python's specific dependency logic.
        """
        self.dependency = []

        pip_pkg_names = [
            dep.split("python3-")[-1] for dep in self.util if dep.startswith("python3-")
        ]

        self.pip_deps = sorted(list(set(pip_pkg_names)))

        if self.pip_deps:
            # Filter out pip packages from the system utility list
            self.util = [dep for dep in self.util if not dep.startswith("python3-")]
            logger.debug(
                f"[{self.name}] Processed Python pip dependencies: {self.pip_deps}"
            )

    @override
    def _get_template_vars(self) -> Dict[str, Any]:
        """
        Extend base template variables with Python-specific ones.
        """
        base_vars = super()._get_template_vars()
        pip_packages = " ".join(self.pip_deps)
        base_vars["pip_packages"] = (
            f"RUN pip install --no-cache-dir {pip_packages}" if pip_packages else ""
        )
        # Ensure dep_packages is empty for the template
        base_vars["dep_packages"] = ""
        return base_vars

    @override
    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure python dependencies from the parent are correctly carried over.
        """
        merged = super().merge(child_config)
        # Re-add the python3- prefixed deps to the 'util' list for accurate merging
        merged["util"].extend([f"python3-{dep}" for dep in self.pip_deps])
        merged["util"] = sorted(list(set(merged["util"])))
        logger.debug(f"[{self.name}] [PythonImage] Fully Merged Result : {merged}")
        return merged
