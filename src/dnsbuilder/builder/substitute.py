# DNSBuilder\src\dnsbuilder\builder\substitute.py
import re
import logging
import os
from typing import Dict, Any

from ..config import Config
from ..base import Image
from ..bases.internal import InternalImage
from ..exceptions import BuildError, ReferenceNotFoundError

logger = logging.getLogger(__name__)

class VariableSubstitutor:
    """
    Handles the substitution of variables within resolved build configurations.
    """
    def __init__(self, config: Config, images: Dict[str, Image], service_ips: Dict[str, str]):
        self.config = config
        self.images = images
        self.service_ips = service_ips

    def run(self, resolved_builds: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        Executes the substitution process for all provided build configurations.
        """
        logger.info("Substituting variables in all build configurations...")
        
        substituted_builds = {}
        for service_name, service_conf in resolved_builds.items():
            # Build the variable map specific to this service
            var_map = self._build_variable_map(service_name, service_conf)
            # Perform substitution on this service's config using its map
            substituted_builds[service_name] = self._recursive_substitute(service_conf, var_map)
            logger.debug(f"Variable substitution complete for service '{service_name}'.")
        
        logger.info("All variables substituted.")
        return substituted_builds

    def _build_variable_map(self, service_name: str, service_conf: Dict) -> Dict[str, str]:
        """Constructs the dictionary of available variables for a given service."""
        var_map = {
            # Service-level
            "name": service_name,
            "ip": self.service_ips.get(service_name, ""),
            "address": self.service_ips.get(service_name, ""),
            # Project-level
            "project.name": self.config.name,
            "project.inet": self.config.inet,
        }

        # Image-level
        image_name = service_conf.get('image')
        if image_name and image_name in self.images:
            image_obj = self.images[image_name]
            var_map["image.name"] = image_obj.name
            if isinstance(image_obj, InternalImage):
                if image_obj.software: 
                    var_map["image.software"] = image_obj.software
                if image_obj.version: 
                    var_map["image.version"] = image_obj.version
            
        return var_map

    def _recursive_substitute(self, item: Any, var_map: Dict[str, str]) -> Any:
        """
        Recursively substitutes variables.
        """
        if isinstance(item, str):
            # Regex to find all types of variables we support
            var_regex = re.compile(r"\$\{(.*?)\}")

            def replacer(match):
                key = match.group(1)

                # env
                if key.startswith("env."):
                    parts = key[4:].split(':', 1) # if needed to add to environ
                    env_var_name = parts[0]
                    value = os.environ.get(env_var_name)
                    if value is not None:
                        return value
                    if len(parts) > 1: # Default value is provided
                        return parts[1]
                    raise BuildError(f"Environment variable '{env_var_name}' is not set and no default value was provided.")

                # service.ip
                if key.startswith("services.") and key.endswith(".ip"):
                    service_to_find = key[9:-3]
                    ip = self.service_ips.get(service_to_find)
                    if ip:
                        return ip
                    # Check if builable
                    if service_to_find in self.config.builds_config:
                         raise ReferenceNotFoundError(f"Cannot resolve IP for service '{service_to_find}': the service is defined but is not buildable (likely `build: false`).")
                    else:
                         raise ReferenceNotFoundError(f"Cannot resolve IP for service '{service_to_find}': service not found in builds configuration.")

                # service.other
                if key in var_map:
                    return var_map[key]
                logger.warning(f"Could not resolve variable '{match.group(0)}' for service '{var_map.get('name', 'unknown')}'. Leaving it unchanged.")
                return match.group(0)
            
            substituted_string = item
            for _ in range(5): # Limit recursion to 5, just as I like
                new_string = var_regex.sub(replacer, substituted_string)
                if new_string == substituted_string:
                    break # Not Found
                substituted_string = new_string
            else:
                 logger.warning(f"Possible circular or deeply nested variable reference in: {item}")

            return substituted_string

        elif isinstance(item, list):
            return [self._recursive_substitute(sub_item, var_map) for sub_item in item]
        elif isinstance(item, dict):
            return {key: self._recursive_substitute(value, var_map) for key, value in item.items()}
        else:
            return item