# config.py
import yaml
import logging
from typing import Dict, Any, List, Set

logger = logging.getLogger(__name__)

class Config:
    """
    Loads and validates the config.yml file. It is the sole gatekeeper for configuration,
    ensuring all subsequent code deals with a valid and well-structured configuration.
    """
    def __init__(self, config_path: str):
        self.path = config_path
        logger.info(f"Loading configuration from '{self.path}'...")
        self.data = self._load_config()
        self._validate()

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.path, 'r') as f:
                config_data = yaml.safe_load(f)
                logger.debug(f"Successfully parsed YAML from '{self.path}'.")
                return config_data
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found at: {self.path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML file: {e}")

    def _validate(self):
        """Main validation method."""
        logger.info("Validating configuration structure...")
        required_keys = ['name', 'inet', 'images', 'builds']
        for key in required_keys:
            if key not in self.data:
                raise ValueError(f"Missing required top-level key: '{key}'")
        logger.debug("Top-level keys [name, inet, images, builds] are present.")
        
        defined_image_names = self._validate_images()
        self._validate_builds(defined_image_names)
        logger.info("Configuration format validation passed.")

    def _validate_images(self) -> Set[str]:
        """
        Validates the 'images' section with new inheritance-aware rules.
        Checks for unique names, valid references, and circular dependencies.
        """
        logger.debug("Starting 'images' section validation...")
        if not isinstance(self.data['images'], list):
             raise TypeError("'images' key must contain a list.")
        
        images_by_name = {}
        for idx, image_conf in enumerate(self.data['images']):
            if not isinstance(image_conf, dict):
                raise TypeError(f"Item at index {idx} in 'images' must be a dictionary.")
            if 'name' not in image_conf:
                raise ValueError(f"Image definition at index {idx} is missing required 'name' field.")
            name = image_conf['name']
            if name in images_by_name:
                raise ValueError(f"Duplicate image name found: '{name}'.")
            images_by_name[name] = image_conf
        logger.debug(f"Found {len(images_by_name)} unique image definitions: {list(images_by_name.keys())}")

        # --- Cycle Detection ---
        visiting = set()
        visited = set()

        def detect_cycle(name):
            logger.debug(f"Validating image '{name}'...")
            visiting.add(name)
            conf = images_by_name[name]
            ref = conf.get('ref')
            
            ref_name = None
            if ref and ':' not in ref:
                ref_name = ref
                logger.debug(f"Image '{name}' has a ref to another image: '{ref_name}'.")

            if ref_name:
                if ref_name not in images_by_name:
                     raise ValueError(f"Image '{name}' has a 'ref' to an undefined image: '{ref_name}'.")
                if ref_name in visiting:
                    raise ValueError(f"Circular dependency detected: '{name}' -> '{ref_name}' forms a loop.")
                if ref_name not in visited:
                    detect_cycle(ref_name)
            
            if not ref:
                logger.debug(f"Image '{name}' is a base image (no ref). Checking for 'software' key.")
                if 'software' not in conf:
                    raise ValueError(f"Image '{name}' is a base image (no 'ref') and must have a 'software' key.")

            visiting.remove(name)
            visited.add(name)
            logger.debug(f"Validation for image '{name}' passed.")

        for name in images_by_name:
            if name not in visited:
                detect_cycle(name)
        
        logger.debug("'images' section validation successful.")
        return set(images_by_name.keys())


    def _validate_builds(self, defined_image_names: Set[str]):
        """
        Validates the 'builds' section, now including reference and cycle checks.
        """
        logger.debug("Starting 'builds' section validation...")
        builds_conf = self.data['builds']
        if not isinstance(builds_conf, dict):
             raise TypeError("'builds' key must contain a dictionary.")

        for build_name, build_conf in builds_conf.items():
            if not isinstance(build_conf, dict):
                raise TypeError(f"Build definition for '{build_name}' must be a dictionary.")
            
            if 'image' not in build_conf and 'ref' not in build_conf:
                raise ValueError(f"Build '{build_name}' must have either an 'image' or a 'ref' key.")
            
            if 'image' in build_conf:
                image_ref = build_conf['image']
                logger.debug(f"Build '{build_name}' uses image '{image_ref}'.")
                if image_ref not in defined_image_names:
                    raise ValueError(f"Build '{build_name}' refers to undefined image: '{image_ref}'.")

            if 'behavior' in build_conf and not isinstance(build_conf['behavior'], str):
                raise TypeError(f"Build '{build_name}' has a 'behavior' key that is not a string.")

            # to allow for software type inference.
            ref_val = build_conf.get('ref')
            if ref_val and ref_val.startswith('std:') and 'image' not in build_conf:
                raise ValueError(f"Build '{build_name}' uses a 'std:' reference ('{ref_val}') but is missing the required 'image' key to determine the software type.")

        visiting = set()
        visited = set()
        def detect_cycle(name):
            logger.debug(f"Validating build '{name}'...")
            visiting.add(name)
            conf = builds_conf[name]
            ref_name = conf.get('ref')

            if ref_name and ":" not in ref_name:
                logger.debug(f"Build '{name}' has a ref to another build: '{ref_name}'.")
                if ref_name not in builds_conf:
                    raise ValueError(f"Build '{name}' has a 'ref' to an undefined build: '{ref_name}'.")
                if ref_name in visiting:
                    raise ValueError(f"Circular dependency detected in builds: '{name}' -> '{ref_name}' forms a loop.")
                if ref_name not in visited:
                    detect_cycle(ref_name)
            
            visiting.remove(name)
            visited.add(name)
            logger.debug(f"Validation for build '{name}' passed.")

        for name in builds_conf:
            if name not in visited:
                detect_cycle(name)
        
        logger.debug("'builds' section validation successful.")

    @property
    def name(self) -> str: return self.data['name']
    @property
    def inet(self) -> str: return self.data['inet']
    @property
    def images_config(self) -> List[Dict[str, Any]]: return self.data['images']
    @property
    def builds_config(self) -> Dict[str, Any]: return self.data['builds']