# DNSBuilder\src\dnsbuilder\builder\substitute.py
import logging
import re
import os
from typing import Dict, Any
from functools import wraps
from ..config import Config
from .. import constants
from ..base import Image
from ..bases.internal import InternalImage
from ..exceptions import BuildError, ReferenceNotFoundError

logger = logging.getLogger(__name__)

def no_required(func):
    @wraps(func)
    def wrapper(self, key, *args, **kwargs):
        resolved_value = func(self, key, *args, **kwargs)
        if resolved_value == constants.PLACEHOLDER["REQUIRED"]:
            return f"${{{key}}}"
        return resolved_value

    return wrapper

def lenient_resolver(func):
    """Decorator that catches resolution errors and returns None with a warning."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        key = None
        if args:
            key = args[0]
        else:
            key = kwargs.get('key')
        try:
            return func(self, *args, **kwargs)
        except (ReferenceNotFoundError, BuildError) as e:
            key_repr = f"${{{key}}}" if key else "<unknown>"
            logger.warning(f"Failed to resolve {key_repr}: {e}. Returning string 'none'.")
            return "none"
    return wrapper

class VariableSubstitutor:
    """
    Handles the substitution of variables within resolved build configurations.
    """
    def __init__(self, config: Config, images: Dict[str, Image], service_ips: Dict[str, str], resolved_builds: Dict[str, Dict]):
        self.config = config
        self.images = images
        self.service_ips = service_ips
        self.resolved_builds = resolved_builds

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

    @lenient_resolver
    @no_required
    def _resolve_env_variable(self, key: str) -> str:
        """Resolve environment variables with optional default values."""
        parts = key[4:].split(':', 1)  # Remove 'env.' prefix
        env_var_name = parts[0]
        value = os.environ.get(env_var_name)
        
        if value is not None:
            return value
        if len(parts) > 1:  # Default value is provided
            return parts[1]
        
        raise BuildError(f"Environment variable '{env_var_name}' is not set and no default value was provided.")

    @lenient_resolver
    @no_required
    def _resolve_service_ip(self, key: str) -> str:
        """Resolve service IP addresses."""
        service_to_find = key[9:-3]  # Remove 'services.' prefix and '.ip' suffix
        ip = self.service_ips.get(service_to_find)
        
        if ip:
            return ip
        
        # Check if buildable
        if service_to_find in self.config.builds_config:
            raise ReferenceNotFoundError(f"Cannot resolve IP for service '{service_to_find}': the service is defined but is not buildable (likely `build: false`).")
        else:
            raise ReferenceNotFoundError(f"Cannot resolve IP for service '{service_to_find}': service not found in builds configuration.")

    @lenient_resolver
    @no_required
    def _resolve_service_image_property(self, key: str) -> str:
        """Resolve service image properties using getattr."""
        parts = key.split(".")
        if len(parts) < 4 or parts[0] != "services" or parts[2] != "image":
            raise ReferenceNotFoundError(f"Invalid service image property format: '{key}'")
        
        service_to_find = parts[1]
        image_property = parts[3]
        
        # Check if service exists in resolved builds
        if service_to_find not in self.resolved_builds:
            raise ReferenceNotFoundError(f"Cannot resolve image property for service '{service_to_find}': service not found in builds configuration.")
        
        service_conf = self.resolved_builds[service_to_find]
        image_name = service_conf.get('image')
        
        if not image_name:
            raise ReferenceNotFoundError(f"Cannot resolve image property for service '{service_to_find}': service has no 'image' key.")
        
        if image_name not in self.images:
            raise ReferenceNotFoundError(f"Cannot resolve image property for service '{service_to_find}': image '{image_name}' not found.")
        
        image_obj = self.images[image_name]
        
        # Use getattr to get the property, with None as default
        try:
            value = getattr(image_obj, image_property, None)
            if value is None:
                raise ReferenceNotFoundError(f"Cannot resolve image.{image_property} for service '{service_to_find}': property not found or is None.")
            return str(value)
        except AttributeError:
            raise ReferenceNotFoundError(f"Cannot resolve image.{image_property} for service '{service_to_find}': property does not exist.")

    @lenient_resolver
    @no_required
    def _resolve_build_conf_property(self, key: str, var_map: Dict[str, str]) -> str:
        """
        Resolves a value from a build configuration using a dot-separated path.
        Can resolve from the current service's build_conf or another service's.
        """
        parts = key.split('.')
        
        current_service_name = var_map['name']

        if parts[0] == 'services':
            # Accessing another service's build_conf
            if len(parts) < 3:
                raise ReferenceNotFoundError(f"Invalid service property format: '{key}'")
            service_name = parts[1]
            path_parts = parts[2:]
            
            if service_name not in self.resolved_builds:
                raise ReferenceNotFoundError(f"Service '{service_name}' not found in resolved builds.")
                
            target_conf = self.resolved_builds[service_name]
        else:
            # Accessing the current service's build_conf
            service_name = current_service_name
            path_parts = parts
            if service_name not in self.resolved_builds:
                raise BuildError(f"Could not find current service '{service_name}' in resolved builds.")
            target_conf = self.resolved_builds[service_name]

        value = target_conf
        for i, part in enumerate(path_parts):
            if isinstance(value, dict):
                if part not in value:
                    raise ReferenceNotFoundError(f"Property path '{'.'.join(path_parts)}' not found in build config for service '{service_name}'. Part '{part}' does not exist.")
                value = value.get(part)
            else:
                raise ReferenceNotFoundError(f"Cannot access property '{part}' on a non-dictionary value (at '{'.'.join(path_parts[:i])}') in build config for service '{service_name}'.")
        
        if isinstance(value, (dict, list)):
             raise BuildError(f"Variable '{key}' resolved to a complex type ({type(value).__name__}), which cannot be substituted into a string.")

        return str(value)

    def _resolve_variable(self, key: str, var_map: Dict[str, str]) -> str:
        """Main variable resolution dispatcher."""
        # Skip placeholders
        if f"${{{key}}}" in constants.PLACEHOLDER.values():
            return f"${{{key}}}"

        # Environment variables
        if key.startswith("env."):
            return self._resolve_env_variable(key)

        # Service IP addresses
        if key.startswith("services.") and key.endswith(".ip"):
            return self._resolve_service_ip(key)

        # Service image properties
        if key.startswith("services.") and ".image." in key:
            return self._resolve_service_image_property(key)

        # Local variables from var_map
        if key in var_map:
            return var_map[key]

        # Try to resolve from build_conf as a path
        value = self._resolve_build_conf_property(key, var_map)
        if value is not None:
            return value

        # Variable not found
        logger.warning(f"Could not resolve variable '${{{key}}}' for service '{var_map.get('name', 'unknown')}'. Returning string 'none'.")
        return "none"

    def _recursive_substitute(self, item: Any, var_map: Dict[str, str]) -> Any:
        """
        Recursively substitutes variables.
        """
        if isinstance(item, str):
            # Nested placeholder-aware substitution: resolve innermost `${...}` first
            substituted_string: Any = item

            # Replace all innermost `${...}` occurrences in a single pass.
            pattern = re.compile(r"\$\{([^{}]+)\}")

            def expand_innermost_pass(text: str) -> str:
                def _repl(m: re.Match) -> str:
                    key = m.group(1)
                    resolved = self._resolve_variable(key, var_map)
                    return str(resolved)
                return pattern.sub(_repl, text)

            for _ in range(10):  # allow deeper nesting safely
                new_string = expand_innermost_pass(substituted_string)
                if new_string == substituted_string:
                    break
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