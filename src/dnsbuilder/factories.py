from typing import Dict, Set, Tuple, List, Any, Type
import logging

from .bases.internal import InternalImage, BindImage, UnboundImage, PythonImage
from .bases.behaviors import BindForwardBehavior, BindHintBehavior, BindStubBehavior
from .bases.behaviors import UnboundForwardBehavior, UnboundHintBehavior, UnboundStubBehavior
from .bases.includers import BindIncluder, UnboundIncluder
from .base import Image, Behavior, Includer
from .exceptions import ImageError

logger = logging.getLogger(__name__)

# -------------------------
#
#   IMAGE FACTORY
#
# -------------------------

class ImageFactory:
    """
    Factory Resolves internal image inheritance and creates final, materialized Image objects.
    """

    def __init__(self, images_config: List[Dict[str, Any]]):
        self.configs = {conf["name"]: conf for conf in images_config}
        self.resolved_images: Dict[str, InternalImage] = {}
        self.resolving_stack: Set[str] = set()
        self.software_map: Dict[str, Type[InternalImage]] = {
            "bind": BindImage,
            "unbound": UnboundImage,
            "python": PythonImage,
        }
        logger.debug("ImageFactory initialized.")

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
            raise ImageError(f"Circular dependency detected involving image '{name}'")

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
            raise ImageError(
                f"Cannot instantiate image '{config['name']}': missing 'software' type for an internal image."
            )

        image_class = self.software_map.get(software_type)
        if not image_class:
            raise ImageError(
                f"Image '{config['name']}' has an unknown 'software' type: {software_type}"
            )

        logger.debug(
            f"Instantiating '{config['name']}' using class {image_class.__name__}."
        )
        return image_class(config)


# -------------------------
#
#   BEHAVIOR FACTORY
#
# -------------------------


class BehaviorFactory:
    """
    Factory Creates the appropriate Behavior object based on software type
    """
    def __init__(self):
        self._behaviors = {
            # BIND Implementations
            ("bind", "hint"): BindHintBehavior,
            ("bind", "stub"): BindStubBehavior,
            ("bind", "forward"): BindForwardBehavior,
            # Unbound Implementations
            ("unbound", "hint"): UnboundHintBehavior,
            ("unbound", "stub"): UnboundStubBehavior,
            ("unbound", "forward"): UnboundForwardBehavior,
            # To add more SoftWare Implementations
        }

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
        if len(parts) != 3:
            raise ValueError(
                f"Invalid behavior format: '{line}'. Expected '<zone> <type> <target1>,<target2>...'."
            )

        zone, behavior_type, targets_str = parts
        targets = [t.strip() for t in targets_str.split(",")]

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

        key = (software_type, behavior_type)
        behavior_class = self._behaviors.get(key)

        if not behavior_class:
            raise NotImplementedError(
                f"Behavior '{behavior_type}' is not supported for software '{software_type}'."
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

    def __init__(self):
        self._includers = {
            "bind": BindIncluder,
            "unbound": UnboundIncluder,
            # other like PowerDNS etc...
        }

    def create(self, path: str, software_type: str) -> Includer:
        includer_class = self._includers.get(software_type)

        if not includer_class:
            raise NotImplementedError(
                f"Includer '{software_type}' is not supported for software '{software_type}'."
            )

        return includer_class(path)
