"""
DNS Builder External Image Implementations

This module contains concrete implementations of external Docker images.

Concrete classes:
- DockerImage: Images from Docker Hub or registry
- SelfDefinedImage: Images with user-provided Dockerfiles
"""

from typing import Any, Dict
import logging

from ..utils import override
from ..abstractions import ExternalImage
from ..io import DNSBPath, FileSystem
from ..exceptions import ImageDefinitionError

logger = logging.getLogger(__name__)


# ============================================================================
# DOCKER IMAGE
# ============================================================================

class DockerImage(ExternalImage):
    """
    Concrete class for Docker images from Docker Hub or registry
    """
    
    @override
    def _post_init_hook(self, config: Dict[str, Any]):
        """
        Docker images don't need any special initialization
        """
        pass
    
    @override
    def write(self, directory: DNSBPath):
        """
        Docker images don't need to write anything
        """
        logger.debug(f"[{self.name}] [DockerImage] Nothing to write")
        pass


# ============================================================================
# SELF-DEFINED IMAGE
# ============================================================================

class SelfDefinedImage(ExternalImage):
    """
    Concrete class for self-defined images with user-provided Dockerfiles
    """
    
    @override
    def _post_init_hook(self, config: Dict[str, Any]):
        """
        Validate and locate the Dockerfile for self-defined images
        """
        path = DNSBPath(self.name)
        if not self.fs.exists(path):
            raise ImageDefinitionError(f"Self-defined image path '{self.name}' does not exist")

        if self.fs.is_file(path):
            self.path = path
            return

        if self.fs.is_dir(path):
            # Look for Dockerfile first
            dockerfiles = list(self.fs.rglob(path, 'Dockerfile'))
            if dockerfiles:
                self.path = DNSBPath(dockerfiles[0])
                return

            # Then look for first file containing 'dockerfile'
            all_files = sorted(self.fs.rglob(path, '*'))
            dockerfile_path = next((p for p in all_files if 'dockerfile' in p.name.lower() and self.fs.is_file(p)), None)
            if dockerfile_path:
                self.path = DNSBPath(dockerfile_path)
                return

        raise ImageDefinitionError(f"Self-defined image path '{self.name}' is not a file, and does not contain a Dockerfile")

    @override
    def write(self, directory: DNSBPath):
        """
        Copy the user-provided Dockerfile to the build directory
        """
        logger.debug(f"[{self.name}] [SelfDefinedImage] content from {self.path} to {directory}")
        dockerfile = directory / "Dockerfile"
        self.fs.copy(self.path, dockerfile)
        pass
