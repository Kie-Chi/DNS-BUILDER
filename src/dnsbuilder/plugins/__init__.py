"""
DNS Builder Plugin System

This package provides the plugin architecture for DNS Builder, allowing
users to extend the framework with custom DNS server implementations.

Quick Start:
    # In your application startup
    from dnsbuilder.plugins import init_plugins
    init_plugins()

    # Check loaded plugins
    from dnsbuilder.plugins import list_plugins
    print(list_plugins())

Creating a Plugin:
    from dnsbuilder.plugins import Plugin, PluginRegistry

    class MyDNSPlugin(Plugin):
        name = "mydns"
        version = "1.0.0"
        description = "My custom DNS server support"

        def on_load(self, registry: PluginRegistry):
            registry.register_image("mydns", MyDNSImage)
            registry.register_behavior("mydns", "forward", MyDNSForwardBehavior)

Plugin Discovery Methods:
    1. Entry Points (recommended for published plugins):
       Add to your pyproject.toml:
       [project.entry-points."dnsb.plugins"]
       mydns = "my_plugin_module:MyDNSPlugin"

    2. Configuration File:
       Add to your config.yml:
       plugins:
         - "my_plugin_module:MyDNSPlugin"

    3. Environment Variable:
       export DNSB_PLUGINS="my_plugin_module:MyDNSPlugin"
"""

from .base import (
    Plugin,
    PluginRegistry,
    PluginInfo,
)
from .discovery import (
    PluginDiscovery,
    discover_plugins,
)
from .manager import (
    PluginManager,
    get_plugin_manager,
    init_plugins,
    list_plugins,
    get_plugin,
)

__all__ = [
    # Core classes
    "Plugin",
    "PluginRegistry",
    "PluginInfo",
    # Discovery
    "PluginDiscovery",
    "discover_plugins",
    # Manager
    "PluginManager",
    "get_plugin_manager",
    "init_plugins",
    "list_plugins",
    "get_plugin",
]