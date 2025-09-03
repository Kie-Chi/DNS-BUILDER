from abc import ABC, abstractmethod
import copy
import os
import json
from pathlib import Path
from importlib import resources
from typing import Any, Dict, List, Optional
import logging

from ..rules.rule import Rule
from ..rules.version import Version
from ..exceptions import ImageError

logger = logging.getLogger(__name__)

# Load all image defaults
IMAGE_DEFAULTS_TEXT = resources.files('dnsbuilder.resources.images').joinpath('defaults').read_text(encoding='utf-8')
IMAGE_DEFAULTS = json.loads(IMAGE_DEFAULTS_TEXT)

class Image(ABC):
    """
    Abstract class describing a Docker Image
    """
    def __init__(self, config: Dict[str, Any]):
        self.name: str = config['name']
        self.ref: Optional[str] = config.get('ref')
        self.software: Optional[str] = config.get('software')
        self.version: Optional[str] = config.get('version')
        self.util: List[str] = config.get('util', [])
        self.dependency: List[str] = config.get('dependency', [])
        self.os, self.os_version = str(config.get('from', ":")).split(":")

        self.base_image: str = ""
        self.default_deps = set()
        self.default_utils = set()

        self._load_defaults()
        self._generate_deps_from_rules()
        self._post_init_hook()

        # Final merge of default, rule-based, and user-defined dependencies
        self.dependency = sorted(list(self.default_deps.union(set(self.dependency))))
        self.util = sorted(list(self.default_utils.union(set(self.util))))

        logger.debug(f"[{self.name}] Final merged dependencies: {self.dependency}")
        logger.debug(f"[{self.name}] Final merged utilities: {self.util}")

    def _load_defaults(self):
        """Loads default settings from the 'defaults' resource."""
        if not self.software:
            logger.critical(f"[{self.name}] No SoftWare defined in Image")
            return # Likely an abstract/alias image without software type
        
        defaults = IMAGE_DEFAULTS.get(self.software)
        if not defaults:
            logger.warning(f"No defaults found for software '{self.software}' in defaults")
            return

        # Load defaults only if this is a preset image
        if ":" in self.name:
            self.os = "ubuntu" # set actually Ubuntu
            self.base_image = "" # will be modified later
            self.default_deps = set(defaults.get('default_deps', []))
            self.default_utils = set(defaults.get('default_utils', []))
            logger.debug(f"[{self.name}] Initialized with defaults for '{self.software}'.")
        else: 
            # User-defined image with 'from'
            self.base_image = f"{self.os}:{self.os_version}"


    def _generate_deps_from_rules(self):
        """
        Parses the rule set for the given software version to determine
        the base OS version and additional dependencies.
        """
        if not self.software or not self.version:
            logger.critical(f"[{self.name}] No SoftWare or No Version defined in Image")
            return # Not a buildable image

        try:
            rules_text = resources.files('dnsbuilder.resources.images.rules').joinpath(f'{self.software}').read_text(encoding='utf-8')
            ruleset = json.loads(rules_text)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ImageError(f"Failed to load rules for '{self.software}': {e}")
        
        version_obj = Version(self.version)
        is_valid = False
        os_version_from_rule = None
        
        for raw_rule, dep in ruleset.items():
            rule = Rule(raw_rule)
            if version_obj not in rule:
                continue

            if dep is None:
                # Version Validation
                is_valid = True
            elif "." in dep:
                # OS Version Fetch
                if not os_version_from_rule:
                    os_version_from_rule = dep
            else: 
                # Added Dependency
                logger.debug(f"[{self.name}] Rule '{raw_rule}' met, adding dependency '{dep}'.")
                self.default_deps.add(dep)
        
        if not is_valid:
            raise ImageError(f"[{self.name}] Version '{self.version}' is not valid according to the ruleset.")

        if os_version_from_rule:
            self.os_version = os_version_from_rule
            self.base_image = f"{self.os}:{self.os_version}"
            logger.debug(f"[{self.name}] OS version set to '{os_version_from_rule}' by rule.")
        elif ":" in self.name and not self.os_version:
             raise ImageError(f"[{self.name}] Failed to determine OS version from rules for version '{self.version}'.")


    def _generate_dockerfile_content(self) -> str:
        """
        Loads the appropriate Dockerfile template and formats it with instance variables.
        Subclasses can override this to provide additional template variables.
        """
        try:
            template = resources.files('dnsbuilder.resources.images.templates').joinpath(f'{self.software}').read_text(encoding='utf-8')
        except FileNotFoundError:
            raise ImageError(f"Dockerfile template for '{self.software}' not found.")

        template_vars = self._get_template_vars()
        return template.format(**template_vars)

    def _get_template_vars(self) -> Dict[str, Any]:
        """Provides a dictionary of variables for formatting the Dockerfile template."""
        dep_packages = " ".join(self.dependency)
        util_packages = " ".join(self.util)
        
        return {
            "name": self.name,
            "version": self.version,
            "base_image": self.base_image,
            "dep_packages": dep_packages,
            "util_packages": util_packages or "''",
        }

    @abstractmethod
    def _post_init_hook(self):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
        """
        pass

    def write(self, directory: Path):
        if not self.software or not self.version:
            logger.debug(f"Image '{self.name}' is not buildable (likely an alias), skipping Dockerfile generation.")
            return
        
        content = self._generate_dockerfile_content()
        dockerfile_path = directory / "Dockerfile"
        dockerfile_path.write_text(content, encoding='utf-8')
        logger.info(f"Dockerfile for '{self.name}' written to {dockerfile_path}")

    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges a parent Image object's attributes with a child's config dict.
        Child's config takes precedence. Lists are merged (union).
        """
        logger.debug(f"[{self.name}] [Image] Merging parent '{self.name}' into child '{child_config['name']}'.")
        merged = {
            'from': f"{self.os}:{self.os_version}",
            'name': child_config['name'], 'ref': child_config.get('ref'),
            'software': self.software, 'version': self.version,
            'dependency': copy.deepcopy(self.dependency), 
            'util': copy.deepcopy(self.util),
        }
        merged['software'] = child_config.get('software', merged['software'])
        merged['version'] = child_config.get('version', merged['version'])
        
        child_deps = set(child_config.get('dependency', []))
        child_utils = set(child_config.get('util', []))
        merged['dependency'] = sorted(list(set(merged['dependency']).union(child_deps)))
        merged['util'] = sorted(list(set(merged['util']).union(child_utils)))
        logger.debug(f"[{self.version}] [Image] Merge result for '{child_config['name']}': {merged}")
        return merged