"""
DNS Builder Plugin Manager

This module provides the PluginManager class that orchestrates plugin
discovery, loading, and lifecycle management.

Usage:
    from dnsbuilder.plugins import get_plugin_manager, init_plugins

    # Initialize plugins (usually called once at startup)
    init_plugins()

    # Or with config-specified plugins
    init_plugins(["my_plugin.module:MyPlugin"])

    # Access the manager
    manager = get_plugin_manager()
    print(manager.list_plugins())
"""

import logging
from typing import List, Optional, Dict, Any

from .base import Plugin, PluginRegistry
from .discovery import PluginDiscovery

logger = logging.getLogger(__name__)

# Type hints for registries (avoid circular imports)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..registry import ImageRegistry, BehaviorRegistry, IncluderRegistry, ZoneGeneratorRegistry


class PluginManager:
    """
    Singleton plugin manager for DNS Builder.

    Responsibilities:
    - Discover and load plugins
    - Manage plugin lifecycle
    - Provide access to the plugin registry

    Example:
        manager = PluginManager.get_instance()
        loaded = manager.load_plugins()
        print(f"Loaded plugins: {loaded}")
    """

    _instance: Optional["PluginManager"] = None

    def __new__(cls) -> "PluginManager":
        """Singleton pattern - ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the plugin manager (only once)."""
        if self._initialized:
            return

        # Import registries here to avoid circular imports
        from ..registry import (
            behavior_registry,
            image_registry,
            includer_registry,
            zone_generator_registry,
            section_registry
        )

        self._registry = PluginRegistry(
            image_registry=image_registry,
            behavior_registry=behavior_registry,
            includer_registry=includer_registry,
            zone_generator_registry=zone_generator_registry,
            section_registry=section_registry
        )
        self._plugins: Dict[str, Plugin] = {}
        self._loaded = False
        self._initialized = True

        logger.debug("PluginManager initialized")

    @classmethod
    def get_instance(cls) -> "PluginManager":
        """
        Get the singleton PluginManager instance.

        Returns:
            The PluginManager instance
        """
        return cls()

    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance.

        Useful for testing or when you need to reinitialize the plugin system.
        """
        if cls._instance is not None:
            cls._instance._loaded = False
            cls._instance._plugins.clear()
        cls._instance = None

    def load_plugins(
        self,
        config_plugins: Optional[List[str]] = None,
        force_reload: bool = False
    ) -> List[str]:
        """
        Discover and load all plugins.

        Args:
            config_plugins: List of plugin specs from configuration file
            force_reload: If True, reload even if already loaded

        Returns:
            List of successfully loaded plugin names
        """
        if self._loaded and not force_reload:
            logger.debug("Plugins already loaded, returning cached list")
            return list(self._plugins.keys())

        logger.info("Discovering and loading plugins...")

        # Discover plugin classes
        plugin_classes = PluginDiscovery.discover_all(config_plugins)
        logger.debug(f"Discovered {len(plugin_classes)} plugin class(es)")

        loaded: List[str] = []

        for plugin_cls in plugin_classes:
            try:
                # Instantiate the plugin
                plugin = plugin_cls()

                # Validate plugin has a name
                if not plugin.name:
                    logger.warning(
                        f"Plugin class {plugin_cls.__name__} has no name, skipping"
                    )
                    continue

                # Load the plugin
                self._load_plugin(plugin)
                loaded.append(plugin.name)

                logger.info(
                    f"Loaded plugin: {plugin.name} v{plugin.version}"
                    + (f" - {plugin.description}" if plugin.description else "")
                )

            except Exception as e:
                logger.error(
                    f"Failed to load plugin {plugin_cls.__name__}: {e}"
                )

        self._loaded = True
        return loaded

    def _load_plugin(self, plugin: Plugin) -> None:
        """
        Load a single plugin instance.

        Sets the plugin context and calls on_load, then applies
        any constants overrides defined in plugin.attributes.

        Args:
            plugin: The plugin instance to load
        """
        # Set context for tracking registrations
        PluginRegistry._current_plugin = plugin.name

        try:
            # Call the plugin's on_load method
            plugin.on_load(self._registry)

            # Register the plugin instance
            self._registry.register_plugin_instance(plugin)
            self._plugins[plugin.name] = plugin

            # Apply plugin attributes (constants overrides)
            if plugin.attributes:
                self._apply_plugin_attributes(plugin)

        finally:
            # Always clear context
            PluginRegistry._current_plugin = None

    def _apply_plugin_attributes(self, plugin: Plugin) -> None:
        """
        Apply plugin's attributes to constants module.

        Uses the same merge logic as .dnsbattribute file.

        Args:
            plugin: The plugin whose attributes to apply
        """
        from .. import constants
        from ..attribute import AttributeLoader

        logger.debug(
            f"[PluginManager] Applying attributes from plugin '{plugin.name}': "
            f"{list(plugin.attributes.keys())}"
        )

        AttributeLoader.apply(constants, plugin.attributes)

    def unload_plugin(self, name: str) -> bool:
        """
        Unload a specific plugin.

        Args:
            name: Name of the plugin to unload

        Returns:
            True if plugin was unloaded, False if not found
        """
        if name not in self._plugins:
            logger.warning(f"Plugin '{name}' not found, cannot unload")
            return False

        plugin = self._plugins[name]

        try:
            # Call the plugin's cleanup method
            plugin.on_unload()

            # Remove from registries
            self._registry.unregister_plugin_instance(name)

            # Remove from our tracking
            del self._plugins[name]

            logger.info(f"Unloaded plugin: {name}")
            return True

        except Exception as e:
            logger.error(f"Error unloading plugin '{name}': {e}")
            return False

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """
        Get a loaded plugin instance by name.

        Args:
            name: Plugin name

        Returns:
            Plugin instance or None if not found
        """
        return self._plugins.get(name)

    def list_plugins(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all loaded plugins.

        Returns:
            Dictionary mapping plugin names to their metadata
        """
        return {
            name: {
                "version": plugin.version,
                "description": plugin.description,
                "author": plugin.author,
                "priority": plugin.priority,
            }
            for name, plugin in self._plugins.items()
        }

    @property
    def registry(self) -> PluginRegistry:
        """
        Get the plugin registry.

        Returns:
            The PluginRegistry instance
        """
        return self._registry

    @property
    def is_loaded(self) -> bool:
        """Check if plugins have been loaded."""
        return self._loaded

    @property
    def plugin_count(self) -> int:
        """Get the number of loaded plugins."""
        return len(self._plugins)


# =============================================================================
# Convenience Functions
# =============================================================================

def get_plugin_manager() -> PluginManager:
    """
    Get the singleton PluginManager instance.

    Returns:
        The PluginManager instance
    """
    return PluginManager.get_instance()


def init_plugins(
    config_plugins: Optional[List[str]] = None,
    force_reload: bool = False
) -> List[str]:
    """
    Initialize the plugin system.

    This should be called once during application startup, after
    the core registries have been initialized.

    Args:
        config_plugins: Optional list of plugin specs from configuration
        force_reload: Force reload even if already loaded

    Returns:
        List of loaded plugin names
    """
    manager = get_plugin_manager()
    return manager.load_plugins(config_plugins, force_reload)


def list_plugins() -> Dict[str, Dict[str, Any]]:
    """
    List all loaded plugins.

    Returns:
        Dictionary of plugin information
    """
    return get_plugin_manager().list_plugins()


def get_plugin(name: str) -> Optional[Plugin]:
    """
    Get a specific plugin by name.

    Args:
        name: Plugin name

    Returns:
        Plugin instance or None
    """
    return get_plugin_manager().get_plugin(name)