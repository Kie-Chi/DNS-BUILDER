from typing import Dict, Set, Tuple, List, Any
import logging

from .bases.internal import InternalImage
from .base import Image, Behavior, Includer
from .io.fs import FileSystem, AppFileSystem
from .datacls.volume import Pair
from .exceptions import ImageDefinitionError, CircularDependencyError, UnsupportedFeatureError
from .registry import behavior_registry, image_registry, includer_registry, initialize_registries

logger = logging.getLogger(__name__)

# -------------------------
#
#   IMAGE FACTORY
#
# -------------------------

class ImageFactory:
    """
    Factory Resolves internal image inheritance and creates final, materialized Image objects.
    Uses reflection-based registry for dynamic image discovery.
    """

    def __init__(self, images_config: Dict[str, Dict[str, Any]], fs: FileSystem = AppFileSystem()):
        self.configs = {name: ({"name": name} | conf) for name, conf in images_config.items()}
        self.resolved_images: Dict[str, InternalImage] = {}
        self.resolving_stack: Set[str] = set()
        self.fs = fs
        
        # Initialize registries if not already done
        if not image_registry._images:
            initialize_registries()
            
        logger.debug("ImageFactory initialized with reflection-based registry.")

    def create_all(self) -> Dict[str, Image]:
        """Creates all defined images, resolving their references."""
        logger.info("Resolving and creating all defined images...")
        all_image_names = set(self.configs.keys())
        for name in all_image_names:
            if name not in self.resolved_images:
                self._resolve(name)
        logger.info(f"All {len(self.resolved_images)} images created successfully.")
        return self.resolved_images

    def _resolve(self, name: str) -> InternalImage:
        """Recursively resolves an image and its parents, returning the final object."""
        if name in self.resolved_images:
            return self.resolved_images[name]

        if name in self.resolving_stack:
            raise CircularDependencyError(f"Circular dependency detected involving image '{name}'")

        logger.debug(f"Resolving image '{name}'...")
        self.resolving_stack.add(name)

        config = self.configs.get(name, {})
        ref = config.get("ref")

        if ":" in name and name not in self.configs:
            # It's a preset image like "bind:9.18.18" not explicitly defined
            ref = None
            sw, version = name.split(":", 1)
            config = {"name": name, "software": sw, "version": version}

        if not ref:
            logger.debug(f"Image '{name}' is a base. Instantiating.")
            final_image = self._instantiate_from_config(config)
        else:
            logger.debug(f"Image '{name}' references '{ref}'. Resolving parent first.")
            parent_image = self._resolve(ref)
            merged_config = parent_image.merge(config)
            final_image = self._instantiate_from_config(merged_config)

        self.resolving_stack.remove(name)
        self.resolved_images[name] = final_image
        logger.debug(f"Successfully resolved and cached image '{name}'.")
        return final_image

    def _instantiate_from_config(self, config: Dict[str, Any]) -> InternalImage:
        """Helper to create a concrete Image instance from a resolved config."""
        software_type = config.get("software")
        if not software_type:
            raise ImageDefinitionError(
                f"Cannot instantiate image '{config['name']}': missing 'software' type for an internal image."
            )

        image_class = image_registry.get_image_class(software_type)
        if not image_class:
            supported_software = image_registry.get_supported_software()
            raise ImageDefinitionError(
                f"Image '{config['name']}' has an unknown 'software' type: {software_type}. "
                f"Supported types: {sorted(supported_software)}"
            )

        logger.debug(
            f"Instantiating '{config['name']}' using class {image_class.__name__}."
        )
        return image_class(config, fs=self.fs)


# -------------------------
#
#   BEHAVIOR FACTORY
#
# -------------------------


class BehaviorFactory:
    """
    Factory Creates the appropriate Behavior object based on software type.
    Uses reflection-based registry for dynamic behavior discovery.
    """
    def __init__(self):
        # Initialize registries if not already done
        if not behavior_registry._behaviors:
            initialize_registries()
        
        logger.debug("BehaviorFactory initialized with reflection-based registry.")

    def _parse_behavior(self, line: str) -> Tuple[str, List[Any]]:
        """
        parse a behavior
        Args:
            line (str): A line from behavior config

        Returns:
            Tuple[str, List[Any]]
            behavior_type, args used for init behavior (zone, targets)
        """
        parts = line.strip().split(maxsplit=2)
        if len(parts) < 2:  # At least <zone> <type>
            raise UnsupportedFeatureError(
                f"Invalid behavior format: '{line}'. Expected at least '<zone> <type> ...'."
            )

        zone, behavior_type = parts[0], parts[1]
        args_str = parts[2] if len(parts) > 2 else ""

        if behavior_type == "master":
            return (behavior_type, [zone, args_str])

        if not args_str:
            raise UnsupportedFeatureError(
                f"Invalid behavior format: '{line}'. Expected '<zone> <type> <target1>,<target2>...'."
            )

        targets = [t.strip() for t in args_str.split(",")]
        return (behavior_type, [zone, targets])
 
    def create(self, line: str, software_type: str) -> Behavior:
        """
        Parses a behavior line and returns the correct Behavior instance
        Args:
            line (str): A line from the 'behavior' config, e.g., ". forward root-server,8.8.8.8"
            software_type (str): The software of the service, e.g., "bind"

        Returns:
            behavior(Behavior): An instance of a Behavior subclass
        """
        behavior_type, args = self._parse_behavior(line)

        behavior_class = behavior_registry.get_behavior_class(software_type, behavior_type)

        if not behavior_class:
            supported_behaviors = behavior_registry.get_supported_behaviors(software_type)
            supported_software = behavior_registry.get_supported_software()
            raise UnsupportedFeatureError(
                f"Behavior '{behavior_type}' is not supported for software '{software_type}'. "
                f"Supported behaviors for {software_type}: {sorted(supported_behaviors)}. "
                f"Supported software types: {sorted(supported_software)}"
            )

        return behavior_class(*args)


# -------------------------
#
#   INCLUDE FACTORY
#
# -------------------------


class IncluderFactory:
    """
    Factory Creates the appropriate Includer object based on software type
    """

    def __init__(self, fs: FileSystem = AppFileSystem()):
        self.fs = fs

    def create(self, confs: Dict[str, Pair], software_type: str) -> Includer:
        includer_class = includer_registry.get_includer_class(software_type)

        if not includer_class:
            supported_software = includer_registry.get_supported_software()
            raise ImageDefinitionError(
                f"Includer for software '{software_type}' is not supported. "
                f"Supported software types: {sorted(supported_software)}"
            )

        return includer_class(confs=confs, fs=self.fs)
