from abc import ABC, abstractmethod
from typing import Any, Dict, override
import shutil
import logging
from ..base import Image
from ..utils.path import DNSBPath
from ..exceptions import ImageDefinitionError

logger = logging.getLogger(__name__)

# -------------------------
#
#   EXTERNAL IMAGE
#
# -------------------------

class ExternalImage(Image, ABC):
    """
    Class describing a Docker Image from build-conf
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._post_init_hook(config)

    @abstractmethod
    def _post_init_hook(self, config: Dict[str, Any]):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
        """
        pass

    @abstractmethod
    def write(self, directory: DNSBPath):
        logger.debug(
            f"[{self.name}] [ExternalImage] Image '{self.name}' is an external image, skipping Dockerfile generation."
        )
        return

# -------------------------
#
#   REMOTE IMAGE
#
# -------------------------

class RemoteImage(ExternalImage):
    """
    Class describing a Docker Image from remote
    """
    @override
    def _post_init_hook(self, config: Dict[str, Any]):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
        """
        pass
    
    @override
    def write(self, directory: DNSBPath):
        """
        Write the remote image to the specified directory.
        """
        logger.debug(f"[{self.name}] [RemoteImage] Nothing to write")
        pass

# -------------------------
#
#   LOCAL IMAGE
#
# -------------------------

class LocalImage(ExternalImage):
    """
    Class describing a Docker Image from local
    """
    @override
    def _post_init_hook(self, config: Dict[str, Any]):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
        """
        path = DNSBPath(self.name)
        if not path.exists():
            raise ImageDefinitionError(f"Local image path '{self.name}' does not exist")

        if path.is_file():
            self.path = path
            return

        if path.is_dir():
            # Look for Dockerfile first
            dockerfiles = list(path.rglob('Dockerfile'))
            if dockerfiles:
                self.path = dockerfiles[0]
                return

            # Then look for first file containing 'dockerfile'
            all_files = sorted(path.rglob('*'))
            dockerfile_path = next((p for p in all_files if 'dockerfile' in p.name.lower() and p.is_file()), None)
            if dockerfile_path:
                self.path = dockerfile_path
                return

        raise ImageDefinitionError(f"Local image path '{self.image_name}' is not a file, and does not contain a Dockerfile")

    @override
    def write(self, directory: DNSBPath):
        """
        Write the local image to the specified directory.
        """
        logger.debug(f"[{self.name}] [LocalImage] content from {self.path} to {directory}")
        dockerfile = directory / "Dockerfile"
        shutil.copy(self.path, dockerfile)
        pass
