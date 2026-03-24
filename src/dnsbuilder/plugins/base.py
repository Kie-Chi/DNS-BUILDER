"""
DNS Builder Plugin System - Base Classes

This module provides the core abstractions for the plugin system:
- Plugin: Base class for all plugins
- PluginRegistry: Registry for plugin extensions (Image, Behavior, Includer, Resources)
- PluginInfo: Data class for plugin metadata
"""

from abc import ABC, abstractmethod
from typing import Dict, Type, Set, Any, Optional, List
from dataclasses import dataclass, field
import logging

from ..protocols import ImageProtocol, BehaviorProtocol, IncluderProtocol, ZoneGeneratorProtocol

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """
    Plugin metadata container.
    """
    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"PluginInfo(name={self.name!r}, version={self.version!r})"


# Global registry for plugin resources
# Maps: resource_subpath -> list of package_names
# e.g., "builder/templates" -> ["dnsb_coredns.resources", "dnsb_powerdns.resources"]
# Multiple plugins can register the same path, all will be included.
_PLUGIN_RESOURCES: Dict[str, List[str]] = {}


def get_plugin_resource_packages(path: str) -> List[str]:
    """
    Get all packages that provide a resource path.

    Args:
        path: Resource path (e.g., "builder/templates")
    """
    # Check for exact match first
    if path in _PLUGIN_RESOURCES:
        return _PLUGIN_RESOURCES[path].copy()

    # Check for parent directory match
    parts = path.split("/")
    for i in range(len(parts), 0, -1):
        parent = "/".join(parts[:i])
        if parent in _PLUGIN_RESOURCES:
            return _PLUGIN_RESOURCES[parent].copy()

    return []


def get_plugin_resource_package(path: str) -> Optional[str]:
    """
    Get the first package that provides a resource path.
    Deprecated: Use get_plugin_resource_packages() to get all packages.
    
    Args:
        path: Resource path (e.g., "images/templates/coredns")
    """
    packages = get_plugin_resource_packages(path)
    return packages[0] if packages else None


def register_plugin_resource(path: str, package: str) -> None:
    """
    Register a plugin's resource package.
    Multiple plugins can register the same path; all will be included
    when listing directory contents.

    """
    if path not in _PLUGIN_RESOURCES:
        _PLUGIN_RESOURCES[path] = []

    if package not in _PLUGIN_RESOURCES[path]:
        _PLUGIN_RESOURCES[path].append(package)
        logger.debug(f"Registered plugin resource: {path} -> {package}")


class Plugin(ABC):
    """
    Base class for all DNS Builder plugins.

    Plugins can extend DNS Builder by registering custom:
    - Image implementations (new DNS server types)
    - Behavior implementations (how DNS servers behave)
    - Includer implementations (config file include patterns)
    - Constants overrides (via attributes class attribute)
    """

    # Plugin metadata - subclasses MUST override these
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    author: str = ""

    # Priority for load order (lower = earlier)
    priority: int = 100

    # Constants to override/extend when plugin loads
    # Uses same merge logic as .dnsbattribute
    # Example:
    #   attributes = {
    #       "DNS_SOFTWARE_BLOCKS": {
    #           "coredns": {"global"}
    #       },
    #       "RECOGNIZED_PATTERNS": {
    #           "coredns": [r"\bcoredns\b"]
    #       }
    #   }
    attributes: Dict[str, Any] = {}

    @abstractmethod
    def on_load(self, registry: "PluginRegistry") -> None:
        """
        Called when the plugin is loaded.
        Implement this method to register your extensions with the registry.
        Args:
            registry: The plugin registry for registering extensions

        Example:
            def on_load(self, registry):
                registry.register_image("mydns", MyDNSImage)
                registry.register_behavior("mydns", "forward", MyDNSForwardBehavior)
        """
        pass

    def on_unload(self) -> None:
        """
        Called when the plugin is unloaded.

        Override this to clean up resources when the plugin is unloaded.
        Default implementation does nothing.
        """
        pass

    def on_config_load(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hook called when configuration is loaded.
        Override this to modify or validate the configuration.
        Args:
            config: The raw configuration dictionary
        """
        return config

    def get_info(self) -> PluginInfo:
        """
        Get plugin metadata.
        """
        return PluginInfo(
            name=self.name,
            version=self.version,
            description=self.description,
            author=self.author,
        )


class PluginRegistry:
    """
    Registry for plugin extensions.
    """

    # Class variable to track current loading plugin context
    _current_plugin: Optional[str] = None

    def __init__(
        self,
        image_registry: "ImageRegistry",
        behavior_registry: "BehaviorRegistry",
        includer_registry: "IncluderRegistry",
        zone_generator_registry: "ZoneGeneratorRegistry" = None
    ):
        """
        Initialize the plugin registry.

        Args:
            image_registry: The core image registry
            behavior_registry: The core behavior registry
            includer_registry: The core includer registry
            zone_generator_registry: The core zone generator registry
        """
        self._images = image_registry
        self._behaviors = behavior_registry
        self._includers = includer_registry
        self._zone_generators = zone_generator_registry
        # Maps: software -> plugin_name
        self._plugin_images: Dict[str, str] = {}
        # Maps: (software, behavior_type) -> plugin_name
        self._plugin_behaviors: Dict[tuple, str] = {}
        # Maps: software -> plugin_name
        self._plugin_includers: Dict[str, str] = {}
        # Maps: software -> plugin_name
        self._plugin_zone_generators: Dict[str, str] = {}
        # Maps: plugin_name -> Plugin instance
        self._loaded_plugins: Dict[str, Plugin] = {}

    # =========================================================================
    #
    # Image Registration
    #
    # =========================================================================

    def register_image(
        self,
        software: str,
        image_class: Type[ImageProtocol],
        override: bool = False
    ) -> None:
        """
        Register an Image implementation.

        Args:
            software: Software identifier (e.g., "coredns", "dnsmasq")
            image_class: The Image class to register
            override: If True, replace existing registration; if False, raise error on conflict
        """
        if software in self._images.registry and not override:
            existing_plugin = self._plugin_images.get(software, "built-in")
            raise ValueError(
                f"Image '{software}' already registered by '{existing_plugin}'. "
                f"Use override=True to replace."
            )

        self._images.register(software, image_class)
        self._plugin_images[software] = self._current_plugin or "unknown"

        logger.debug(
            f"Registered image '{software}' from plugin '{self._current_plugin or 'unknown'}'"
        )

    def unregister_image(self, software: str) -> bool:
        """
        Unregister an Image implementation.
        Only plugins can unregister their own registrations.

        Args:
            software: Software identifier to unregister
        """
        if software in self._plugin_images:
            if software in self._images._registry:
                del self._images._registry[software]
            del self._plugin_images[software]
            logger.debug(f"Unregistered image '{software}'")
            return True
        return False

    # =========================================================================
    #
    # Behavior Registration
    #
    # =========================================================================

    def register_behavior(
        self,
        software: str,
        behavior_type: str,
        behavior_class: Type[BehaviorProtocol],
        override: bool = False
    ) -> None:
        """
        Register a Behavior implementation.

        Args:
            software: Software identifier (e.g., "coredns")
            behavior_type: Behavior type (e.g., "forward", "stub", "hint", "master")
            behavior_class: The Behavior class to register
            override: If True, replace existing registration
        """
        key = (software, behavior_type)

        if key in self._behaviors.registry and not override:
            existing_plugin = self._plugin_behaviors.get(key, "built-in")
            raise ValueError(
                f"Behavior ({software}, {behavior_type}) already registered by '{existing_plugin}'. "
                f"Use override=True to replace."
            )

        self._behaviors.register(key, behavior_class)
        self._plugin_behaviors[key] = self._current_plugin or "unknown"

        logger.debug(
            f"Registered behavior ({software}, {behavior_type}) from plugin '{self._current_plugin or 'unknown'}'"
        )

    def unregister_behavior(self, software: str, behavior_type: str) -> bool:
        """
        Unregister a Behavior implementation.

        Args:
            software: Software identifier
            behavior_type: Behavior type to unregister
        """
        key = (software, behavior_type)
        if key in self._plugin_behaviors:
            if key in self._behaviors._registry:
                del self._behaviors._registry[key]
            del self._plugin_behaviors[key]
            logger.debug(f"Unregistered behavior ({software}, {behavior_type})")
            return True
        return False

    # =========================================================================
    #
    # Includer Registration
    #
    # =========================================================================

    def register_includer(
        self,
        software: str,
        includer_class: Type[IncluderProtocol],
        override: bool = False
    ) -> None:
        """
        Register an Includer implementation.

        Args:
            software: Software identifier
            includer_class: The Includer class to register
            override: If True, replace existing registration
        """
        if software in self._includers.registry and not override:
            existing_plugin = self._plugin_includers.get(software, "built-in")
            raise ValueError(
                f"Includer '{software}' already registered by '{existing_plugin}'. "
                f"Use override=True to replace."
            )

        self._includers.register(software, includer_class)
        self._plugin_includers[software] = self._current_plugin or "unknown"

        logger.debug(
            f"Registered includer '{software}' from plugin '{self._current_plugin or 'unknown'}'"
        )

    def unregister_includer(self, software: str) -> bool:
        """
        Unregister an Includer implementation.

        Args:
            software: Software identifier to unregister
        """
        if software in self._plugin_includers:
            if software in self._includers._registry:
                del self._includers._registry[software]
            del self._plugin_includers[software]
            logger.debug(f"Unregistered includer '{software}'")
            return True
        return False

    # =========================================================================
    #
    # Zone Generator Registration
    #
    # =========================================================================

    def register_zone_generator(
        self,
        software: str,
        generator_class: Type[ZoneGeneratorProtocol],
        override: bool = False
    ) -> None:
        """
        Register a ZoneGenerator implementation.

        This allows plugins to provide custom zone file formats for different
        DNS software. If no generator is registered for a software, the default
        BIND-style ZoneGenerator is used.

        Args:
            software: Software identifier (e.g., "coredns", "mydns")
            generator_class: The ZoneGenerator class to register
            override: If True, replace existing registration
        """
        if self._zone_generators is None:
            logger.warning(
                f"ZoneGeneratorRegistry not available, cannot register generator for '{software}'"
            )
            return

        if software in self._zone_generators.registry and not override:
            existing_plugin = self._plugin_zone_generators.get(software, "built-in")
            raise ValueError(
                f"ZoneGenerator '{software}' already registered by '{existing_plugin}'. "
                f"Use override=True to replace."
            )

        self._zone_generators.register(software, generator_class)
        self._plugin_zone_generators[software] = self._current_plugin or "unknown"

        logger.debug(
            f"Registered zone_generator '{software}' from plugin '{self._current_plugin or 'unknown'}'"
        )

    def unregister_zone_generator(self, software: str) -> bool:
        """
        Unregister a ZoneGenerator implementation.

        Args:
            software: Software identifier to unregister
        """
        if self._zone_generators is None:
            return False

        if software in self._plugin_zone_generators:
            if software in self._zone_generators._registry:
                del self._zone_generators._registry[software]
            del self._plugin_zone_generators[software]
            logger.debug(f"Unregistered zone_generator '{software}'")
            return True
        return False

    def get_zone_generator(self, software: str) -> Optional[Type[ZoneGeneratorProtocol]]:
        """
        Get a ZoneGenerator class by software type.

        Args:
            software: Software identifier

        Returns:
            ZoneGenerator class or None if not found
        """
        if self._zone_generators is None:
            return None
        return self._zone_generators.generator(software)

    # =========================================================================
    #
    # Resource Registration
    #
    # =========================================================================

    def register_resources(
        self,
        software: str,
        package: str,
        templates: bool = False,
        defaults: bool = True,
        image_templates: bool = True,
        build_templates: bool = True,
        rules: bool = False,
        controls: bool = True,
        scripts: bool = False,
        configs: bool = True
    ) -> None:
        """
        Register plugin resources for a software type.

        This allows plugins to provide their own templates, defaults, and
        control files that will be loaded by the ResourceFileSystem.

        Args:
            software: Software identifier (e.g., "coredns")
            package: Python package containing resources (e.g., "dnsb_coredns.resources")
            templates: Whether to register all templates path
            image_templates: Whether to register image templates path
            build_templates: Whether to register builder templates path
            defaults: Whether to register defaults path
            controls: Whether to register controls path
            scripts: Whether to register scripts path
            configs: Whether to register configs path (for base config files)

        Example:
            def on_load(self, registry):
                registry.register_resources("coredns", "dnsb_coredns.resources")
        """
        plugin_name = self._current_plugin or "unknown"

        if templates or image_templates:
            path = f"images/templates/{software}"
            register_plugin_resource(path, package)
            logger.debug(
                f"Registered templates resource: {path} -> {package} (from {plugin_name})"
            )

        if rules:
            path = f"images/rules/{software}"
            register_plugin_resource(path, package)
            logger.debug(
                f"Registered rules resource: {path} -> {package} (from {plugin_name})"
            )

        if defaults:
            path = f"images/defaults/{software}"
            register_plugin_resource(path, package)
            logger.debug(
                f"Registered defaults resource: {path} -> {package} (from {plugin_name})"
            )

        if controls:
            path = f"images/controls/{software}"
            register_plugin_resource(path, package)
            logger.debug(
                f"Registered controls resource: {path} -> {package} (from {plugin_name})"
            )

        if scripts:
            path = f"scripts/{software}"
            register_plugin_resource(path, package)
            logger.debug(
                f"Registered scripts resource: {path} -> {package} (from {plugin_name})"
            )

        if configs:
            # Register configs path for base configuration files
            # This allows resource:/configs/coredns_xxx_base.conf to work
            path = "configs"
            register_plugin_resource(path, package)
            logger.debug(
                f"Registered configs resource: {path} -> {package} (from {plugin_name})"
            )

        if templates or build_templates:
            # Register builder templates for this software
            # This allows resource:/builder/templates.d/coredns to work
            path = "builder/templates"
            register_plugin_resource(path, package)
            logger.debug(
                f"Registered builder templates resource: {path} -> {package} (from {plugin_name})"
            )

        logger.info(
            f"Registered resources for '{software}' from plugin '{plugin_name}'"
        )

    # =========================================================================
    #
    # Plugin Management
    #
    # =========================================================================

    def register_plugin_instance(self, plugin: Plugin) -> None:
        """Register a loaded plugin instance."""
        self._loaded_plugins[plugin.name] = plugin

    def unregister_plugin_instance(self, name: str) -> bool:
        """Unregister a plugin instance."""
        if name in self._loaded_plugins:
            del self._loaded_plugins[name]
            return True
        return False

    def get_loaded_plugins(self) -> Dict[str, PluginInfo]:
        """
        Get information about all loaded plugins.
        """
        return {name: plugin.get_info() for name, plugin in self._loaded_plugins.items()}

    def get_plugin_instance(self, name: str) -> Optional[Plugin]:
        """
        Get a loaded plugin instance by name.

        Args:
            name: Plugin name
        """
        return self._loaded_plugins.get(name)

    # =========================================================================
    #
    # Introspection
    #
    # =========================================================================

    def get_images_by_plugin(self, plugin_name: str) -> Set[str]:
        """Get all image software types registered by a specific plugin."""
        return {sw for sw, pn in self._plugin_images.items() if pn == plugin_name}

    def get_behaviors_by_plugin(self, plugin_name: str) -> Set[tuple]:
        """Get all behaviors registered by a specific plugin."""
        return {key for key, pn in self._plugin_behaviors.items() if pn == plugin_name}

    def get_includers_by_plugin(self, plugin_name: str) -> Set[str]:
        """Get all includers registered by a specific plugin."""
        return {sw for sw, pn in self._plugin_includers.items() if pn == plugin_name}

    def get_zone_generators_by_plugin(self, plugin_name: str) -> Set[str]:
        """Get all zone generators registered by a specific plugin."""
        return {sw for sw, pn in self._plugin_zone_generators.items() if pn == plugin_name}