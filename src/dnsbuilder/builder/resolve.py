from pathlib import Path
import copy
import logging
from typing import Dict, Any

from .. import constants
from ..config import Config
from ..images.image import Image
from ..exceptions import BuildError, ConfigError, CircularDependencyError

logger = logging.getLogger(__name__)

class Resolver:
    """
    Resolves the complete, flattened build configuration for each service
    """
    def __init__(self, config: Config, images: Dict[str, Image], predefined_builds: Dict):
        self.config = config
        self.images = images
        self.predefined_builds = predefined_builds
        self.resolved_builds: Dict[str, Dict] = {}
        self.resolving_stack: set = set()

    def resolve_all(self) -> Dict[str, Dict]:
        """The main entry point to resolve all services."""
        logger.info("Resolving all build configurations...")
        for service_name in self.config.builds_config.keys():
            self._resolve_service(service_name)
        logger.info("All build configurations resolved.")
        return self.resolved_builds

    def _resolve_service(self, service_name: str) -> Dict[str, Any]:
        if service_name in self.resolved_builds:
            logger.debug(f"[Resolver] Service '{service_name}' already resolved. Returning cached config.")
            return self.resolved_builds[service_name]
        
        if service_name in self.resolving_stack: raise CircularDependencyError(f"Circular dependency in builds: '{service_name}'")
        
        logger.debug(f"[Resolver] Starting resolution for service '{service_name}'...")
        self.resolving_stack.add(service_name)
        
        if service_name not in self.config.builds_config:
            raise ConfigError(f"Build configuration for '{service_name}' not found.")
        
        service_conf = self.config.builds_config[service_name]
        ref = service_conf.get('ref')
        parent_conf = {}
        
        if ref:
            logger.debug(f"[Resolver] Service '{service_name}' has ref: '{ref}'.")
            if ':' in ref:
                software_type, role = None, None
                predefined_ref = ref
                if ref.startswith(constants.STD_BUILD_PREFIX):
                    role = ref.split(':', 1)[1]
                    image_name = service_conf.get('image')
                    if not image_name: raise ConfigError(f"Ref '{ref}' requires 'image' key for service '{service_name}'.")
                    image_obj = self.images[image_name]
                    software_type = image_obj.software
                    if not software_type: raise ConfigError(f"Image '{image_name}' has no 'software' type for ref '{ref}'.")
                    predefined_ref = f"{software_type}:{role}"
                    logger.debug(f"[Resolver] Interpreted '{ref}' as standard build '{predefined_ref}'.")
                else:
                    software_type, role = ref.split(':', 1)

                if software_type not in self.predefined_builds or role not in self.predefined_builds.get(software_type, {}):
                    raise BuildError(f"Unknown predefined build: '{predefined_ref}'.")
                parent_conf = self.predefined_builds[software_type][role]
                logger.debug(f"[Resolver] Loaded parent config from predefined build '{predefined_ref}'.")
            else:
                # Reference to another user-defined build
                logger.debug(f"[Resolver] Following reference to user-defined build '{ref}'...")
                parent_conf = self._resolve_service(ref)
                logger.debug(f"[Resolver] Parent '{ref}' resolved.")

        logger.debug(f"[Resolver] Merging parent config with child config for '{service_name}'.")
        final_conf = self._merge_configs(parent_conf, service_conf)
        if 'ref' in final_conf: del final_conf['ref']
        
        self.resolving_stack.remove(service_name)
        self.resolved_builds[service_name] = final_conf
        logger.debug(f"[Resolver] Successfully resolved service '{service_name}'. Final config: {final_conf}")
        return final_conf

    def _merge_configs(self, parent: Dict, child: Dict) -> Dict:
        merged = copy.deepcopy(parent)
        for key, value in child.items():
            if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                merged_set = set(merged[key])
                original_len = len(merged[key])
                merged[key].extend([item for item in value if item not in merged_set])
                logger.debug(f"[Merge] Merged list for key '{key}': {original_len} parent items, {len(value)} child items -> {len(merged[key])} total unique items.")
            else:
                if key in merged:
                    logger.debug(f"[Merge] Overriding key '{key}': from '{merged[key]}' to '{value}'.")
                else:
                    logger.debug(f"[Merge] Adding new key '{key}': '{value}'.")
                merged[key] = value
        return merged