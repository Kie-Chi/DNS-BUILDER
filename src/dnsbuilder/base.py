
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import logging

from .datacls.artifacts import BehaviorArtifact
from .utils.path import DNSBPath

logger = logging.getLogger(__name__)

# -------------------------
#
#   BASE ABC Image
#
# -------------------------

class Image(ABC):
    """
    Abstract class describing a Docker Image
    """

    def __init__(self, config: Dict[str, Any]):
        self.name: str = config.get("name")
        self.ref: Optional[str] = config.get("ref")

    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges a parent Image object's attributes with a child's config dict.
        Child's config takes precedence. Lists are merged (union).
        """
        logger.debug(
            f"[{self.name}] [Image] Merging parent '{self.name}' into child '{child_config['name']}'."
        )
        merged = {
            "name": child_config["name"],
            "ref": child_config.get("ref"),
        }
        return merged

    @abstractmethod
    def write(self, directory: DNSBPath):
        pass


# -------------------------
#
#   BASE ABC Behavior
#
# -------------------------

class Behavior(ABC):
    """
    Abstract Class for a DNS server behavior
    Each behavior can generate its own configuration artifact
    """

    def __init__(self, zone: str, targets: List[str]):
        self.zone = zone
        self.targets = targets

    @abstractmethod
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        """
        Generates the necessary configuration line and any associated files.
        :param service_name: The name of the service this behavior is for.
        :param target_ips: The resolved IP addresses of the target services.
        :return: A BehaviorArtifact object containing the results.
        """
        pass

# -------------------------
#
#   BASE ABC Includer
#
# -------------------------

class Includer(ABC):
    """
    Abstract Class describe the `include config` line used in software config-file
    """

    def __init__(self, config_line: str):
        self.config_line = config_line

    @abstractmethod
    def write(self, conf: str):
        """
        write `include: config` line into conf

        Args:
            conf (str): main configuration file path

        Returns:
            None
        """
        pass

