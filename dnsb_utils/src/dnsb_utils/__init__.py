"""
DNS Builder Utils Plugin

This plugin provides utility helper functions for auto scripts.
Helpers are automatically injected into the auto script execution environment.

Usage:
    In config.yml:

    plugins:
      - "dnsb_utils:UtilsPlugin"

    Then in auto scripts:

    builds:
      my-dns:
        auto:
          setup: |
            # Use zone_from_file helper
            config['behavior'] = zone_from_file("zones/example.zone")

Available Helpers:
    - zone_from_file(file_path, zone_name=None): Parse zone file to behavior lines
"""

import logging
from typing import Dict, Any

from dnsbuilder.plugins import Plugin, PluginRegistry

logger = logging.getLogger(__name__)

__version__ = "0.1.0"


class UtilsPlugin(Plugin):
    """
    Utils Plugin for DNS Builder.

    Provides helper functions for auto scripts.
    """

    # Plugin metadata
    name = "utils"
    version = __version__
    description = "Utility helpers for DNS Builder auto scripts"
    author = "Xikai"
    priority = 0  # High priority (load early so helpers are available)

    def on_load(self, registry: PluginRegistry):
        """
        Register utility helpers.

        Args:
            registry: The plugin registry to register with
        """
        logger.info("[UtilsPlugin] Loading utils plugin...")

        # Import and register helpers
        from .helpers import zone_from_file

        registry.register_auto_helper("zone_from_file", zone_from_file)

        logger.info(
            "[UtilsPlugin] Registered helpers: zone_from_file"
        )

    def on_unload(self):
        """Cleanup when plugin is unloaded."""
        logger.info("[UtilsPlugin] Unloading utils plugin...")


# Export for entry points
__all__ = [
  'UtilsPlugin',
  '__version__'
]