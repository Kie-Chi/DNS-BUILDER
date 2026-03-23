"""
DNS Builder Plugin Discovery Mechanisms

This module provides multiple ways to discover and load plugins:

1. Entry Points - Plugins declare themselves via pyproject.toml
2. Configuration File - Users specify plugins in their config.yml
3. Environment Variable - Plugins specified via DNSB_PLUGINS env var

Entry Points Example (pyproject.toml):
    [project.entry-points."dnsb.plugins"]
    coredns = "dnsb_coredns:CoreDNSPlugin"

Config File Example (config.yml):
    plugins:
      - "dnsb_coredns:CoreDNSPlugin"
      - "my_plugin.module:MyPlugin"

Environment Variable Example:
    export DNSB_PLUGINS="dnsb_coredns:CoreDNSPlugin,my_plugin:MyPlugin"
"""

import importlib
import logging
import os
from typing import List, Type, Optional, Dict, Any

from .base import Plugin

logger = logging.getLogger(__name__)


class PluginDiscovery:
    """
    Plugin discovery class with multiple discovery strategies.

    Discovery order:
    1. Entry points
    2. Configuration file specified plugins
    3. Environment variable specified plugins
    """
    ENTRY_POINT_GROUP = "dnsb.plugins"

    @classmethod
    def discover_all(
        cls,
        config_plugins: Optional[List[str]] = None
    ) -> List[Type[Plugin]]:
        """
        Discover all available plugins from all sources.

        Args:
            config_plugins: List of plugin specs from configuration file
        """
        plugins: List[Type[Plugin]] = []
        discovered_names: set = set()

        for plugin_cls in cls._discover_from_entry_points():
            if plugin_cls.name not in discovered_names:
                plugins.append(plugin_cls)
                discovered_names.add(plugin_cls.name)
                logger.debug(
                    f"Discovered plugin via entry points: {plugin_cls.name}"
                )

        if config_plugins:
            for plugin_cls in cls._discover_from_config(config_plugins):
                if plugin_cls.name not in discovered_names:
                    plugins.append(plugin_cls)
                    discovered_names.add(plugin_cls.name)
                    logger.debug(
                        f"Discovered plugin from config: {plugin_cls.name}"
                )

        for plugin_cls in cls._discover_from_env():
            if plugin_cls.name not in discovered_names:
                plugins.append(plugin_cls)
                discovered_names.add(plugin_cls.name)
                logger.debug(
                    f"Discovered plugin from environment: {plugin_cls.name}"
                )

        # Sort by priority (lower = earlier loading)
        plugins.sort(key=lambda p: p.priority)
        return plugins

    @classmethod
    def _discover_from_entry_points(cls) -> List[Type[Plugin]]:
        """
        Discover plugins from Python entry points.
        """
        plugins: List[Type[Plugin]] = []

        try:
            import importlib.metadata as metadata
        except ImportError:
            # Fallback for older Python versions
            try:
                import importlib_metadata as metadata
            except ImportError:
                logger.debug(
                    "importlib.metadata not available, skipping entry point discovery"
                )
                return plugins

        try:
            entry_points = metadata.entry_points(group=cls.ENTRY_POINT_GROUP)
            for ep in entry_points:
                try:
                    plugin_cls = ep.load()
                    if isinstance(plugin_cls, type) and issubclass(plugin_cls, Plugin):
                        plugins.append(plugin_cls)
                    else:
                        logger.warning(
                            f"Entry point '{ep.name}' is not a valid Plugin class, got: {type(plugin_cls)}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to load plugin from entry point '{ep.name}': {e}"
                    )
        except Exception as e:
            logger.debug(f"Error reading entry points: {e}")

        return plugins

    @classmethod
    def _discover_from_config(
        cls,
        plugin_specs: List[str]
    ) -> List[Type[Plugin]]:
        """
        Discover plugins from configuration file specifications.
        Supports formats:
        - "module.path:ClassName" - Specific class in module
        - "module.path" - Auto-discover Plugin subclass in module
        """
        plugins: List[Type[Plugin]] = []

        for spec in plugin_specs:
            try:
                plugin_cls = cls._load_plugin_class(spec)
                if plugin_cls:
                    plugins.append(plugin_cls)
            except Exception as e:
                logger.warning(f"Failed to load plugin from config '{spec}': {e}")

        return plugins

    @classmethod
    def _discover_from_env(cls) -> List[Type[Plugin]]:
        """
        Discover plugins from environment variable.
        Format: DNSB_PLUGINS=plugin1.module:Class1,plugin2.module:Class2
        """
        plugins: List[Type[Plugin]] = []

        env_plugins = os.environ.get("DNSB_PLUGINS", "")
        if not env_plugins:
            return plugins

        for spec in env_plugins.split(","):
            spec = spec.strip()
            if not spec:
                continue

            try:
                plugin_cls = cls._load_plugin_class(spec)
                if plugin_cls:
                    plugins.append(plugin_cls)
            except Exception as e:
                logger.warning(
                    f"Failed to load plugin from environment '{spec}': {e}"
                )

        return plugins

    @staticmethod
    def _load_plugin_class(spec: str) -> Optional[Type[Plugin]]:
        """
        Load a Plugin class from a specification string.
        Args:
            spec: Plugin specification in format "module.path:ClassName"
                  or "module.path" for auto-discovery
        """
        # Parse the specification
        if ":" in spec:
            module_path, class_name = spec.rsplit(":", 1)
        else:
            module_path = spec
            class_name = None

        # Import the module
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            logger.warning(f"Cannot import module '{module_path}': {e}")
            return None

        # Load specific class if named
        if class_name:
            plugin_cls = getattr(module, class_name, None)
            if plugin_cls is None:
                logger.warning(
                    f"Class '{class_name}' not found in module '{module_path}'"
                )
                return None

            if not (isinstance(plugin_cls, type) and issubclass(plugin_cls, Plugin)):
                logger.warning(
                    f"'{class_name}' in '{module_path}' is not a Plugin subclass"
                )
                return None

            return plugin_cls

        # Auto-discover Plugin subclass
        for name in dir(module):
            obj = getattr(module, name)

            # Skip non-classes and Plugin base class itself
            if not isinstance(obj, type):
                continue
            if obj is Plugin:
                continue

            # Check if it's a Plugin subclass with a valid name
            if issubclass(obj, Plugin) and obj.name:
                return obj

        logger.warning(f"No valid Plugin subclass found in '{module_path}'")
        return None


def discover_plugins(
    config_plugins: Optional[List[str]] = None
) -> List[Type[Plugin]]:
    """
    Convenience function to discover all plugins.

    Args:
        config_plugins: Optional list of plugin specs from configuration
    """
    return PluginDiscovery.discover_all(config_plugins)