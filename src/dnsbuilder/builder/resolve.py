import logging
from typing import Dict, Any

from ..abstractions import Image
from .. import constants
from ..config import Config
from ..utils import deep_merge
from ..exceptions import (
    BuildDefinitionError,
    ReferenceNotFoundError,
    CircularDependencyError,
    ImageDefinitionError,
    UnsupportedFeatureError
)

logger = logging.getLogger(__name__)

class Resolver:
    """
    Resolves the complete, flattened build configuration for each service
    """
    def __init__(self, config: Config, images: Dict[str, Image], pr_blds: Dict):
        self.config = config
        self.images = images
        self.pr_blds = pr_blds
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
        
        if service_name in self.resolving_stack: 
            raise CircularDependencyError(f"Circular dependency in builds: '{service_name}'")
        
        logger.debug(f"[Resolver] Starting resolution for service '{service_name}'...")
        self.resolving_stack.add(service_name)
        
        if service_name not in self.config.builds_config:
            raise BuildDefinitionError(f"Build configuration for '{service_name}' not found.")
        
        service_conf = self.config.builds_config[service_name]
        ref = service_conf.get('ref')
        parent_conf = {}
        
        # Merge Ref
        if ref:
            logger.debug(f"[Resolver] Service '{service_name}' has ref: '{ref}'.")
            if ref.startswith(constants.STD_BUILD_PREFIX):
                role = ref.split(':', 1)[1]
                image_name = service_conf.get('image')
                if not image_name:
                    raise BuildDefinitionError(f"A build using a '{constants.STD_BUILD_PREFIX}' reference requires the 'image' key in service '{service_name}'.")
                
                image_obj = self.images.get(image_name)
                if not image_obj:
                    raise ReferenceNotFoundError(f"Image '{image_name}' referenced by service '{service_name}' not found.")

                software_type = getattr(image_obj, 'software', None)
                if not software_type:
                    raise ImageDefinitionError(f"Image '{image_name}' (used by service '{service_name}') has no 'software' type, which is required for the ref '{ref}'.")
                
                predefined_ref = f"{software_type}:{role}"
                logger.debug(f"[Resolver] Interpreted '{ref}' as standard build '{predefined_ref}'.")
                if software_type not in self.pr_blds or role not in self.pr_blds.get(software_type, {}):
                    raise ReferenceNotFoundError(f"Unknown predefined build for '{predefined_ref}'.")
                
                parent_conf = self.pr_blds[software_type][role]
                logger.debug(f"[Resolver] Loaded parent config from predefined build '{predefined_ref}'.")

            elif ':' in ref:
                software_type, role = ref.split(':', 1)
                if software_type not in self.pr_blds or role not in self.pr_blds.get(software_type, {}):
                    raise ReferenceNotFoundError(f"Unknown predefined build: '{ref}'.")
                parent_conf = self.pr_blds[software_type][role]
                logger.debug(f"[Resolver] Loaded parent config from predefined build '{ref}'.")
            else:
                logger.debug(f"[Resolver] Following reference to user-defined build '{ref}'...")
                parent_conf = self._resolve_service(ref)
                logger.debug(f"[Resolver] Parent '{ref}' resolved.")

        # MERGE MIXINS
        mixins = service_conf.get('mixins', [])
        if mixins:
            logger.debug(f"[Resolver] Service '{service_name}' has mixins: {mixins}. Merging them.")
            for mixin_ref in mixins:
                if mixin_ref.startswith(constants.STD_BUILD_PREFIX):
                    mixin_name = mixin_ref.split(':', 1)[1]
                    mixin_conf = self.pr_blds.get('_std', {}).get(mixin_name)
                    if not mixin_conf:
                        raise ReferenceNotFoundError(f"Unknown standard mixin '{mixin_ref}' for service '{service_name}'.")
                    
                    logger.debug(f"[Resolver] Merging mixin '{mixin_ref}' into '{service_name}'.")
                    parent_conf = deep_merge(parent_conf, mixin_conf)
                else:
                    raise UnsupportedFeatureError(f"Unsupported mixin format '{mixin_ref}'.")

        logger.debug(f"[Resolver] Merging parent/mixin config with child config for '{service_name}'.")
        final_conf = deep_merge(parent_conf, service_conf)
        
        if 'ref' in final_conf: 
            del final_conf['ref']
        if 'mixins' in final_conf: 
            del final_conf['mixins']
        
        self.resolving_stack.remove(service_name)
        self.resolved_builds[service_name] = final_conf
        logger.debug(f"[Resolver] Successfully resolved service '{service_name}'. Final config: {final_conf}")
        return final_conf

