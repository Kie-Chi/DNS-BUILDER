
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, TYPE_CHECKING
import logging

from .datacls.artifacts import BehaviorArtifact
from .datacls.volume import Pair
if TYPE_CHECKING:
    from .datacls.contexts import BuildContext
from .io.path import DNSBPath
from .io.fs import FileSystem, AppFileSystem
from .exceptions import UnsupportedFeatureError

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

    def __init__(self, config: Dict[str, Any], fs: FileSystem = AppFileSystem()):
        self.name: str = config.get("name")
        self.ref: Optional[str] = config.get("ref")
        self.fs = fs

    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges a parent Image object's attributes with a child's config dict.
        
        Args:
            child_config: The config dict of the child.
        Returns:
            The merged config dict.
        """
        logger.debug(
            f"[{self.name}] [Image] Merging parent '{self.name}' into child '{child_config['name']}'."
        )
        merged = {
            "name": child_config.get("name"),
            "ref": child_config.get("ref"),
        }
        return merged

    @abstractmethod
    def write(self, directory: DNSBPath):
        """
        Writes the image to the specified directory.
        
        Args:
            directory: The directory to write the image to.
        Returns:
            None
        """
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
    def generate(self, service_name: str, build_context: "BuildContext") -> BehaviorArtifact:
        """
        Generates the necessary configuration line and any associated files.
        
        Args:
            service_name: The name of the service this behavior is for.
            target_ips: The resolved IP addresses of the target services.
        Returns:
            A BehaviorArtifact object containing the results.
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

    def __init__(self, confs: Dict[str, Pair] = {}, fs: FileSystem = AppFileSystem()):
        self.fs = fs
        self.confs = confs
        self.contain()

    @staticmethod
    def parse_blk(pair: Pair) -> Optional[str]:
        """
        parse block name from volume name
        """
        suffixes = DNSBPath(pair.dst).suffixes
        if len(suffixes) >= 1 and suffixes[-1] == ".conf":
            return 'global'

        if len(suffixes) >= 2 and suffixes[-2] == ".conf":
            return suffixes[-1].strip(".")

        raise UnsupportedFeatureError(f"unsupported block format: {pair.dst}")


    @abstractmethod
    def include(self, pair: Pair):
        """
        write `include config_line` line into conf

        Args:
            confs (Dict[str, DNSBPath]): main configuration file paths
                If dict, keys are block names and values are paths.
            pair (Pair): volume pair to include
        Returns:
            None
        """
        pass

    @abstractmethod
    def contain(self) -> None:
        """
        contain block-main config in global-main config
        
        Args:
            confs (Dict[str, DNSBPath]): main configuration file paths
                If dict, keys are block names and values are paths.
        Returns:
            None
        """
        pass

