from typing import List, Optional, Dict, Any, Set, Type
import copy
from .image import Image
from .bind import BindImage
from .unbound import UnboundImage
from ..exceptions import ImageError
import logging
logger = logging.getLogger(__name__)

class ImageFactory:
    """
    Factory Resolves image inheritance and creates final, materialized Image objects.
    """
    def __init__(self, images_config: List[Dict[str, Any]]):
        self.configs = {conf['name']: conf for conf in images_config}
        self.resolved_images: Dict[str, Image] = {}
        self.resolving_stack: Set[str] = set()
        self.software_map: Dict[str, Type[Image]] = {
            "bind": BindImage,
            "unbound": UnboundImage,
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

    def _resolve(self, name: str) -> Image:
        """Recursively resolves an image and its parents, returning the final object."""
        if name in self.resolved_images:
            return self.resolved_images[name]

        if name in self.resolving_stack:
            raise ImageError(f"Circular dependency detected involving image '{name}'")
        
        logger.debug(f"Resolving image '{name}'...")
        self.resolving_stack.add(name)
        
        config = self.configs.get(name, {})
        ref = config.get('ref')

        if ":" in name and name not in self.configs:
            # It's a preset image like "bind:9.18.18" not explicitly defined
            ref = None
            sw, version = name.split(':', 1)
            config = {'name': name, 'software': sw, 'version': version}

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
        
    def _instantiate_from_config(self, config: Dict[str, Any]) -> Image:
        """Helper to create a concrete Image instance from a resolved config."""
        software_type = config.get('software')
        if not software_type:
            raise ImageError(f"Cannot instantiate image '{config['name']}': missing 'software' type.")
        
        image_class = self.software_map.get(software_type)
        if not image_class:
            raise ImageError(f"Image '{config['name']}' has an unknown 'software' type: {software_type}")
            
        logger.debug(f"Instantiating '{config['name']}' using class {image_class.__name__}.")
        return image_class(config)