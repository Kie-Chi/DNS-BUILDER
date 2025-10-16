from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, override
import logging
import re

from ..base import Image
from .. import constants
from ..io.path import DNSBPath
from ..io.fs import FileSystem, AppFileSystem
from ..registry import image_registry
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

    def __init__(self, config: Dict[str, Any], fs: FileSystem = AppFileSystem()):
        super().__init__(config, fs)
        self.fs = fs
        self.software: Optional[str] = None
        self.original_name = self.name
        
        # Parse software type from placeholder in name and clean the name
        self._parse_software()
        self._post_init_hook(config)

    def _parse_software(self):
        """
        Parse software type from placeholder in name and clean the name.
        Falls back to regex recognition and finally to 'NAS' if no supported type is found.
        """
        if not self.name:
            self.software = "NaS"
            logger.debug(f"[{self.original_name}] No name provided, defaulting to Not a Service")
            return
        
        placeholder_pattern = r'\$\{([^\}]+)\}'
        matches = re.findall(placeholder_pattern, self.name)
        supported_software = image_registry.get_supported_software()
        
        if matches:
            placeholder_content = matches[0].strip()
            
            # Check if the placeholder content is a supported software type
            if placeholder_content in supported_software:
                self.software = placeholder_content
                logger.debug(f"[{self.original_name}] Software type extracted from placeholder: {self.software}")
            else:
                logger.debug(f"[{self.original_name}] Placeholder '{placeholder_content}' is not a supported software type")
                # Fall back to regex recognition on the placeholder content
                self.software = self._rec_software_from_name(placeholder_content)
                if self.software == "NaS":
                    self.software = self._rec_software_from_name(self.name)
            
            cleaned_name = re.sub(placeholder_pattern, "", self.name)
            if cleaned_name:
                self.name = cleaned_name
                logger.debug(
                    f"[{self.original_name}] Name cleaned from '{self.original_name}' to '{self.name}'"
                )
            else:
                # If cleaning results in empty name, use a default name
                self.name = "external"
                logger.debug(
                    f"[{self.original_name}] Name cleaned to '{self.name}' (default name used)"
                )
        else:
            # No placeholder found, try regex recognition on the full name
            self.software = self._rec_software_from_name(self.name)
            logger.debug(f"[{self.original_name}] No placeholder found, software type from regex: {self.software}")
        
        # Final fallback to NaS if still not determined
        if not self.software or self.software == "NaS":
            self.software = "NaS"
            logger.debug(f"[{self.original_name}] Final fallback to Not a Service")

    def _rec_software_from_name(self, name: str) -> str:
        """
        Use regex patterns to recognize software type from image name.
        
        Args:
            name: The image name to analyze
            
        Returns:
            Recognized software type or 'NaS' if not found
        """
        supported_software = image_registry.get_supported_software()
        name_lower = name.lower()
        for software in supported_software:
            if software in constants.RECOGNIZED_PATTERNS:
                for pattern in constants.RECOGNIZED_PATTERNS[software]:
                    if re.search(pattern, name_lower):
                        return software
        
        return "NaS"

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
#   DOCKER IMAGE
#
# -------------------------

class DockerImage(ExternalImage):
    """
    Class describing a Docker Image from Docker Hub or registry
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
        Write the Docker image to the specified directory.
        """
        logger.debug(f"[{self.name}] [DockerImage] Nothing to write")
        pass

# -------------------------
#
#   SELF-DEFINED IMAGE
#
# -------------------------

class SelfDefinedImage(ExternalImage):
    """
    Class describing a Docker Image from self-defined source
    """
    @override
    def _post_init_hook(self, config: Dict[str, Any]):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
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
        Write the self-defined image to the specified directory.
        """
        logger.debug(f"[{self.name}] [SelfDefinedImage] content from {self.path} to {directory}")
        dockerfile = directory / "Dockerfile"
        self.fs.copy(self.path, dockerfile)
        pass
